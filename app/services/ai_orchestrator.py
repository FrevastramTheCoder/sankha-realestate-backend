"""NyumbaSalama AI orchestration without hallucinated listing or GIS facts."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.accommodation_tools import (
    MIN_SUPPORTED_BUDGET,
    SearchPreferences,
    merge_preferences,
    parse_preferences,
    ranking_documentation,
    search_accommodations,
)
from app.services.conversation_store import ConversationStore
from app.services.geo_knowledge import places_near
from app.services.gis import GeoService, haversine_km


logger = logging.getLogger("nyumbasalama.ai")


class NyumbaSalamaAI:
    """Tool-oriented accommodation advisor with persistent conversation state."""

    def __init__(self, geo: GeoService, store: Optional[ConversationStore] = None) -> None:
        self.geo = geo
        self.store = store or ConversationStore()

    async def respond(
        self,
        message: str,
        db: Session,
        conversation_id: Optional[str] = None,
        history: Optional[Sequence[Dict[str, str]]] = None,
        user_location: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        clean_message = message.strip()
        conversation_id = self.store.ensure_id(conversation_id)
        session = self.store.get(conversation_id, db)

        preferences = SearchPreferences()
        # Reconstruct from history first (frontend may send it), then DB state wins.
        for item in (history or [])[-20:]:
            if item.get("role") == "user" and item.get("content"):
                turn = parse_preferences(item["content"], preferences)
                preferences = merge_preferences(preferences, turn, item["content"])
        if session.get("preferences"):
            stored = session["preferences"]
            if isinstance(stored, dict):
                stored = SearchPreferences.from_dict(stored)
            preferences = merge_preferences(stored, preferences, "")

        current = parse_preferences(clean_message, preferences)
        preferences = merge_preferences(preferences, current, clean_message)

        if user_location and not preferences.university and not preferences.location:
            preferences.location = {
                "name": user_location.get("name") or "Your location",
                "lat": user_location["lat"],
                "lng": user_location["lng"],
                "type": "coordinate",
                "source": "request",
                "precision": "provided_coordinate",
            }

        search_executed = False
        result_count = 0
        try:
            if current.budget_below_minimum or preferences.budget_below_minimum:
                result = self._budget_too_low(preferences)
            elif current.intent == "greeting" and not self._has_search_signal(preferences):
                result = self._greeting(preferences.language)
            elif current.intent == "help" and not self._has_search_signal(preferences):
                result = self._help(preferences.language)
            elif current.intent in {"distance_query", "route_query"}:
                result = await self._distance_response(current, session, preferences.language)
            elif current.intent == "comparison":
                result = await self._comparison_response(preferences, current, db, session)
            elif self._is_university_information_request(current, preferences, clean_message):
                result = self._university_response(preferences if preferences.university else current)
            elif current.intent == "location_search" and not self._has_search_signal(preferences):
                result = self._location_response(current)
            elif (
                current.location
                and current.intent == "general_student_advice"
                and not self._has_search_signal(preferences)
            ):
                result = self._location_response(current)
            elif self._is_search_ready(preferences):
                result = await self._accommodation_response(preferences, db, session)
                search_executed = True
                result_count = len(result.get("results") or [])
            elif self._needs_follow_up(preferences):
                result = self._follow_up(preferences)
            else:
                result = self._general_response(preferences)
        except Exception as exc:
            logger.exception("chat turn failed conversation_id=%s", conversation_id)
            result = self._service_error(preferences, exc)

        session["preferences"] = preferences
        session["last_message"] = clean_message
        session["places"] = list(
            {
                (p.get("key") or p.get("name")): p
                for p in (session.get("places") or []) + (current.places or preferences.places or [])
            }.values()
        )
        if result.get("results"):
            session["last_results"] = result["results"]

        public_state = preferences.as_public_state()
        result.update(
            {
                "conversation_id": conversation_id,
                "session_id": conversation_id,
                "preferences": preferences.as_dict(),
                "state": public_state,
                "search_executed": search_executed or bool(result.get("search_executed")),
                "result_count": result_count if search_executed else len(result.get("results") or []),
                "ranking": ranking_documentation(),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

        self.store.save(
            conversation_id,
            session,
            db,
            user_message=clean_message,
            assistant_message=result.get("message") or result.get("reply"),
            response_payload={
                "intent": result.get("intent"),
                "state": public_state,
                "result_count": result.get("result_count"),
                "search_executed": result.get("search_executed"),
            },
        )
        self.store.trim()
        return result

    @staticmethod
    def _is_university_information_request(
        current: SearchPreferences,
        preferences: SearchPreferences,
        message: str,
    ) -> bool:
        text = message.casefold()
        university = current.university or preferences.university
        if not university:
            return False
        # Pure location question about the campus — not a housing slot fill.
        if NyumbaSalamaAI._has_search_signal(current):
            return False
        return bool(
            any(word in text for word in ("where", "iko", "about", "karibu", "maeneo", "campus", "chuo", "wapi"))
            and current.room_type is None
            and current.budget_max is None
            and current.budget_min is None
            and current.max_travel_time_minutes is None
        )

    @staticmethod
    def _has_search_signal(preferences: SearchPreferences) -> bool:
        return bool(
            preferences.room_type
            or preferences.budget_min is not None
            or preferences.budget_max is not None
            or preferences.amenities
            or preferences.max_travel_time_minutes is not None
            or preferences.radius_km is not None
            or preferences.available_only
        )

    @staticmethod
    def _is_search_ready(preferences: SearchPreferences) -> bool:
        """Search when destination + budget + travel constraint are known."""

        if preferences.budget_below_minimum:
            return False
        has_anchor = bool(preferences.university or preferences.location)
        has_budget = preferences.budget_max is not None or preferences.budget_min is not None
        has_travel = preferences.max_travel_time_minutes is not None or preferences.radius_km is not None
        return bool(has_anchor and has_budget and has_travel)

    @staticmethod
    def _missing_slots(preferences: SearchPreferences) -> List[str]:
        missing: List[str] = []
        if not preferences.university and not preferences.location:
            missing.append("anchor")
        if preferences.budget_max is None and preferences.budget_min is None:
            missing.append("budget")
        # Ask travel only once after budget+anchor; never re-ask when already set.
        elif preferences.max_travel_time_minutes is None and preferences.radius_km is None:
            if preferences.university or preferences.location:
                missing.append("travel")
        return missing

    @staticmethod
    def _needs_follow_up(preferences: SearchPreferences) -> bool:
        if preferences.budget_below_minimum:
            return False
        missing = NyumbaSalamaAI._missing_slots(preferences)
        if not missing:
            return False
        # If no housing signal at all, still allow gentle follow-up for university-only context.
        if preferences.university and not NyumbaSalamaAI._has_search_signal(preferences):
            return True
        if preferences.intent == "accommodation_search" or NyumbaSalamaAI._has_search_signal(preferences):
            return True
        return False

    @staticmethod
    def _greeting(language: str) -> Dict[str, Any]:
        if language == "en":
            text = (
                "Hello. I am NyumbaSalama AI. I can search database listings, resolve Dar locations, "
                "and calculate real route results. Tell me your university, budget, and travel time."
            )
        else:
            text = (
                "Habari. Mimi ni NyumbaSalama AI. Naweza kutafuta listings za database, kutambua maeneo ya Dar "
                "na kukokotoa route halisi. Niambie chuo, budget na muda wa safari."
            )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "greeting",
            "results": [],
            "recommendations": [],
            "map": None,
            "tools_used": [],
        }

    @staticmethod
    def _help(language: str) -> Dict[str, Any]:
        if language == "en":
            text = (
                'Try: Find single rooms under 80k near CBE within 20 minutes; '
                "How far is Sinza from UDSM? I return only database listings and provider-calculated routes."
            )
        else:
            text = (
                'Jaribu: Nataka single room karibu na CBE chini ya 80k ndani ya dakika 20; '
                "Sinza mpaka UDSM ni km ngapi? Natumia listings za database na route kutoka provider tu."
            )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "help",
            "results": [],
            "recommendations": [],
            "map": None,
            "tools_used": [],
        }

    @staticmethod
    def _budget_too_low(preferences: SearchPreferences) -> Dict[str, Any]:
        amount = preferences.rejected_budget or 0
        text = (
            f"Kwa sasa NyumbaSalama inatafuta vyumba kuanzia TZS {MIN_SUPPORTED_BUDGET:,} kwa mwezi. "
            f"Tafadhali ongeza budget yako hadi angalau TZS {MIN_SUPPORTED_BUDGET:,}."
        )
        if preferences.language == "en":
            text = (
                f"NyumbaSalama currently searches listings from TZS {MIN_SUPPORTED_BUDGET:,} per month. "
                f"Please raise your budget to at least TZS {MIN_SUPPORTED_BUDGET:,}."
            )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "budget_validation",
            "results": [],
            "recommendations": [],
            "map": None,
            "tools_used": [],
            "rejected_budget": amount,
        }

    @staticmethod
    def _follow_up(preferences: SearchPreferences) -> Dict[str, Any]:
        language = preferences.language
        missing = NyumbaSalamaAI._missing_slots(preferences)

        # Never re-ask slots that are already filled.
        if "anchor" in missing:
            text = (
                "Unatafuta karibu na chuo gani au eneo gani?"
                if language != "en"
                else "Which university or area should I search near?"
            )
        elif "budget" in missing:
            text = (
                f"Budget yako ni kiasi gani kwa mwezi? (kuanzia TZS {MIN_SUPPORTED_BUDGET:,})"
                if language != "en"
                else f"What is your monthly budget? (from TZS {MIN_SUPPORTED_BUDGET:,})"
            )
        elif "travel" in missing:
            text = (
                "Ungependa iwe ndani ya dakika ngapi kutoka chuoni?"
                if language != "en"
                else "How many minutes from campus would you prefer?"
            )
        else:
            text = (
                "Niambie room type unayotaka au endelea na search."
                if language != "en"
                else "Tell me the room type you want, or I can search with what I have."
            )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "follow_up",
            "results": [],
            "recommendations": [],
            "map": None,
            "tools_used": [],
            "missing_slots": missing,
        }

    @staticmethod
    def _service_error(preferences: SearchPreferences, exc: Exception) -> Dict[str, Any]:
        uni = (preferences.university or {}).get("name") if preferences.university else None
        budget = preferences.budget_max
        travel = preferences.max_travel_time_minutes
        lines = ["⚠️ Nimehifadhi taarifa zako:", ""]
        if uni:
            lines.append(f"🏫 {uni}")
        if budget is not None:
            lines.append(f"💰 TZS {int(budget):,} kwa mwezi")
        if travel is not None:
            lines.append(f"🚗 Ndani ya dakika {int(travel)}")
        lines.extend(
            [
                "",
                "Kuna tatizo la muda katika huduma ya kutafuta listings. Tafadhali jaribu tena.",
                "",
                "Taarifa zako hazijapotea.",
            ]
        )
        text = "\n".join(lines)
        logger.error("service error detail: %s", exc)
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "error",
            "results": [],
            "recommendations": [],
            "map": None,
            "tools_used": [],
            "error": True,
            "retryable": True,
        }

    async def _distance_response(
        self, current: SearchPreferences, session: Dict[str, Any], language: str
    ) -> Dict[str, Any]:
        places = list(current.places)
        if len(places) < 2:
            previous = session.get("places", [])
            by_key = {place.get("key"): place for place in previous}
            by_key.update({place.get("key"): place for place in places})
            places = list(by_key.values())
        if len(places) < 2:
            text = (
                "Taja maeneo yote mawili, kwa mfano: Sinza mpaka UDSM ni km ngapi?"
                if language != "en"
                else "Please name both places, for example: How far is Sinza from UDSM?"
            )
            return {
                "message": text,
                "reply": text,
                "response": text,
                "intent": current.intent,
                "results": [],
                "recommendations": [],
                "map": None,
                "tools_used": ["resolve_location"],
            }

        origin, destination = places[0], places[1]
        straight = haversine_km(origin, destination)
        route = await self.geo.route(origin, destination, current.mode)
        origin_name = origin.get("name", "Origin")
        destination_name = destination.get("name", "Destination")
        if language == "en":
            text = f"{origin_name} to {destination_name} is {straight:.2f} km straight-line."
            if route.get("status") == "ok":
                text += (
                    f" The {route['mode']} route is {route['distance_km']:.2f} km and about "
                    f"{route['duration_minutes']:.0f} minutes. Traffic may change the actual travel time."
                )
            else:
                text += " I could not calculate the road route right now, so I will not estimate road distance or travel time."
        else:
            text = f"{origin_name} hadi {destination_name} ni {straight:.2f} km kwa umbali wa moja kwa moja."
            if route.get("status") == "ok":
                text += (
                    f" Route ya {route['mode']} ni {route['distance_km']:.2f} km na takriban dakika "
                    f"{route['duration_minutes']:.0f}. Traffic inaweza kubadilisha muda halisi."
                )
            else:
                text += " Sikuweza kukokotoa route ya barabarani sasa, hivyo sitakisia umbali au muda wa safari."
        markers = [
            {"kind": "origin", "name": origin_name, "lat": origin["lat"], "lng": origin["lng"]},
            {
                "kind": "destination",
                "name": destination_name,
                "lat": destination["lat"],
                "lng": destination["lng"],
            },
        ]
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": current.intent,
            "results": [],
            "recommendations": [],
            "map": {"markers": markers, "routes": [route] if route.get("status") == "ok" else []},
            "distance": {"straight_line_km": round(straight, 3), "route": route},
            "route": route,
            "tools_used": ["resolve_location", "calculate_geodesic_distance", "calculate_route"],
            "warnings": [] if route.get("status") == "ok" else [route.get("error", "Road route unavailable.")],
        }

    def _university_response(self, current: SearchPreferences) -> Dict[str, Any]:
        university = current.university
        if not university:
            text = (
                "Which university or campus do you mean?"
                if current.language == "en"
                else "Unamaanisha chuo gani au campus gani?"
            )
            return {
                "message": text,
                "reply": text,
                "response": text,
                "intent": "university_search",
                "results": [],
                "recommendations": [],
                "map": None,
                "tools_used": ["search_university"],
            }
        nearby = places_near(university, radius_km=8, types={"neighborhood"}, exclude={university.get("key")}, limit=8)
        names = ", ".join(f"{place['name']} ({distance:.1f} km straight-line)" for place, distance in nearby)
        if current.language == "en":
            text = (
                f"{university['name']} is in {university.get('district') or 'Dar es Salaam'}. "
                f"Nearby curated areas include {names or 'no curated area match'}. "
                "These are centroid distances, not road travel times."
            )
        else:
            text = (
                f"{university['name']} iko {university.get('district') or 'Dar es Salaam'}. "
                f"Maeneo ya karibu kwenye layer yetu ni {names or 'hakuna eneo lililothibitishwa kwenye layer'}. "
                "Hizi ni straight-line za centroid, si muda wa barabarani."
            )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "university_search",
            "university": university,
            "location": university,
            "results": [],
            "recommendations": [],
            "map": {
                "markers": [
                    {
                        "kind": "university",
                        "name": university["name"],
                        "lat": university["lat"],
                        "lng": university["lng"],
                    }
                ],
                "routes": [],
            },
            "tools_used": ["search_university", "calculate_geodesic_distance"],
        }

    def _location_response(self, current: SearchPreferences) -> Dict[str, Any]:
        place = current.location or current.university or (current.places[0] if current.places else None)
        if not place:
            text = (
                "Sijaweza kuthibitisha hilo eneo."
                if current.language != "en"
                else "I could not confidently resolve that location."
            )
            return {
                "message": text,
                "reply": text,
                "response": text,
                "intent": "location_search",
                "results": [],
                "recommendations": [],
                "map": None,
                "tools_used": ["resolve_location"],
            }
        nearby = places_near(place, radius_km=8, types={"neighborhood", "ward"}, exclude={place.get("key")}, limit=6)
        nearby_text = ", ".join(f"{item['name']} ({distance:.1f} km)" for item, distance in nearby)
        if current.language == "en":
            text = f"{place['name']} is in {place.get('district') or 'Dar es Salaam'}"
            if place.get("ward"):
                text += f", ward {place['ward']}"
            text += "."
            if nearby_text:
                text += f" Nearby curated areas by straight-line distance: {nearby_text}."
        else:
            text = f"{place['name']} iko {place.get('district') or 'Dar es Salaam'}"
            if place.get("ward"):
                text += f", kata ya {place['ward']}"
            text += "."
            if nearby_text:
                text += f" Maeneo ya karibu kwa umbali wa moja kwa moja: {nearby_text}."
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "location_search",
            "location": place,
            "results": [],
            "recommendations": [],
            "map": {
                "markers": [{"kind": "place", "name": place["name"], "lat": place["lat"], "lng": place["lng"]}],
                "routes": [],
            },
            "tools_used": ["resolve_location", "calculate_geodesic_distance"],
        }

    async def _accommodation_response(
        self, preferences: SearchPreferences, db: Session, session: Dict[str, Any]
    ) -> Dict[str, Any]:
        uni = (preferences.university or {}).get("name") if preferences.university else None
        loc = (preferences.location or {}).get("name") if preferences.location else None
        anchor_name = uni or loc or "eneo lako"
        budget = preferences.budget_max
        travel = preferences.max_travel_time_minutes

        try:
            result = await search_accommodations(db, preferences, self.geo, limit=5)
        except Exception as exc:
            logger.exception("search_accommodations failed")
            return self._service_error(preferences, exc)

        results = result["results"]
        intro_parts = []
        if preferences.language != "en":
            intro_parts.append("Sawa 👍 Nimepata vigezo vyako:\n")
            if uni or loc:
                intro_parts.append(f"🏫 {anchor_name}")
            if budget is not None:
                intro_parts.append(f"💰 Hadi TZS {int(budget):,} kwa mwezi")
            if travel is not None:
                intro_parts.append(f"🚗 Ndani ya dakika {int(travel)}")
            if preferences.room_type:
                intro_parts.append(f"🛏️ {preferences.room_type}")
            intro_parts.append("\nNatafuta listings zinazopatikana zinazokidhi vigezo hivyo...")
        else:
            intro_parts.append("Got it. Searching with:\n")
            if uni or loc:
                intro_parts.append(f"🏫 {anchor_name}")
            if budget is not None:
                intro_parts.append(f"💰 Up to TZS {int(budget):,}/month")
            if travel is not None:
                intro_parts.append(f"🚗 Within {int(travel)} minutes")
            if preferences.room_type:
                intro_parts.append(f"🛏️ {preferences.room_type}")

        if not results:
            if preferences.language == "en":
                text = (
                    "I could not find a listing matching all criteria in the accommodation database right now.\n\n"
                    f"Your filters:\n🏫 {anchor_name}\n"
                    + (f"💰 Up to TZS {int(budget):,}\n" if budget is not None else "")
                    + (f"🚗 Within {int(travel)} minutes\n" if travel is not None else "")
                    + "\nYou can try increasing budget, increasing travel time, or searching nearby areas."
                )
            else:
                text = (
                    "Sijapata chumba kinachokidhi vigezo vyote kwa sasa.\n\n"
                    f"Vigezo vyako:\n🏫 {anchor_name}\n"
                    + (f"💰 Hadi TZS {int(budget):,}\n" if budget is not None else "")
                    + (f"🚗 Ndani ya dakika {int(travel)}\n" if travel is not None else "")
                    + "\nUnaweza kujaribu:\n• kuongeza budget\n• kuongeza muda wa safari\n"
                    f"• kutafuta maeneo mengine karibu na {anchor_name}"
                )
            if result.get("warnings"):
                text += "\n\n" + " ".join(result["warnings"])
            # If routing failed for all candidates, keep state and offer retry.
            if result.get("route_failures") and not results and travel is not None:
                return self._service_error(preferences, RuntimeError("routing unavailable for candidates"))
        else:
            text = "\n".join(intro_parts) + "\n\n"
            if preferences.language == "en":
                text += f"I found {len(results)} database listing(s) near {anchor_name}."
            else:
                text += f"Nimepata listing {len(results)} kutoka kwenye database karibu na {anchor_name}."
            for index, item in enumerate(results[:3], start=1):
                text += "\n\n" + self._format_listing(index, item, preferences.language)
            if result.get("warnings"):
                text += "\n\nNote: " + " ".join(result["warnings"])

        anchor = preferences.university or preferences.location
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "accommodation_search",
            "university": preferences.university,
            "location": preferences.location,
            "results": results,
            "recommendations": results,
            "matched_properties": results,
            "map": self._map_payload(results, anchor),
            "warnings": result.get("warnings", []),
            "search_executed": True,
            "result_count": len(results),
            "tools_used": [
                "search_university" if preferences.university else "resolve_location",
                "search_accommodations",
                "check_availability",
                "calculate_geodesic_distance",
                "calculate_route",
                "rank_accommodations",
            ],
        }

    @staticmethod
    def _format_listing(index: int, item: Dict[str, Any], language: str) -> str:
        availability = item.get("availability_status", "unknown")
        road = f"{item['road_distance_km']:.2f} km" if item.get("road_distance_km") is not None else "not available"
        duration = f"{item['duration_minutes']:.0f} min" if item.get("duration_minutes") is not None else "not available"
        amenities = ", ".join(item.get("amenities") or []) or "not provided"
        return (
            f"{index}. {item['title']} | TZS {item['price']:,.0f}/month\n"
            f"   Location: {item['location']} | Room: {item.get('room_type') or 'not provided'}\n"
            f"   Straight-line: {item.get('straight_line_distance_km', 'not available')} km | Road: {road} | Time: {duration}\n"
            f"   Amenities: {amenities} | Availability: {availability}\n"
            f"   Verification: {item.get('verification_status') or 'not recorded'} | Rating: {item.get('rating') or 'not recorded'}\n"
            f"   Why recommended: {'; '.join(item.get('why') or [])}."
        )

    @staticmethod
    def _map_payload(results: List[Dict[str, Any]], anchor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        markers: List[Dict[str, Any]] = []
        if anchor and anchor.get("lat") is not None:
            markers.append(
                {
                    "kind": "university" if anchor.get("type") in {"university", "college"} else "origin",
                    "name": anchor.get("name", "Origin"),
                    "lat": anchor["lat"],
                    "lng": anchor["lng"],
                }
            )
        routes: List[Dict[str, Any]] = []
        for item in results:
            coordinates = item.get("coordinates")
            if coordinates:
                markers.append(
                    {
                        "kind": "accommodation",
                        "id": str(item["property_id"]),
                        "name": item["title"],
                        "lat": coordinates["lat"],
                        "lng": coordinates["lng"],
                        "price": item["price"],
                    }
                )
            route = item.get("route") or {}
            if route.get("status") == "ok":
                routes.append({"property_id": str(item["property_id"]), **route})
        return {"markers": markers, "routes": routes[:5]}

    async def _comparison_response(
        self,
        preferences: SearchPreferences,
        current: SearchPreferences,
        db: Session,
        session: Dict[str, Any],
    ) -> Dict[str, Any]:
        identifiers = re.findall(
            r"(?:property|listing|hostel|option)?\s*#?(\d+)\b",
            " ".join(place.get("name", "") for place in current.places),
        )
        if len(identifiers) < 2:
            identifiers = re.findall(
                r"(?:property|listing|hostel|option)?\s*#?(\d+)\b", session.get("last_message", "")
            )
        if len(identifiers) < 2 and session.get("last_results"):
            identifiers = [str(item["property_id"]) for item in session["last_results"][:2]]
        if len(identifiers) < 2:
            text = (
                "Taja listing IDs mbili, au sema 'compare these' baada ya kupokea options."
                if current.language != "en"
                else "Provide two listing IDs, or say 'compare these' after receiving options."
            )
            return {
                "message": text,
                "reply": text,
                "response": text,
                "intent": "comparison",
                "results": [],
                "recommendations": [],
                "map": None,
                "tools_used": [],
            }
        if session.get("last_results"):
            search = {"results": session["last_results"], "warnings": []}
        else:
            search = await search_accommodations(db, preferences, self.geo, limit=20)
        listings = [item for item in search["results"] if str(item["property_id"]) in identifiers]
        if len(listings) < 2:
            text = (
                "Sijapata listing IDs hizo mbili kwenye database ya sasa."
                if current.language != "en"
                else "I could not find both listing IDs in the current accommodation database."
            )
            return {
                "message": text,
                "reply": text,
                "response": text,
                "intent": "comparison",
                "results": [],
                "recommendations": [],
                "map": None,
                "tools_used": ["get_accommodation"],
            }
        best = max(listings, key=lambda item: item.get("score", 0))
        text = "Ulinganisho: " if current.language != "en" else "Comparison: "
        text += " | ".join(
            f"{item['title']} TZS {item['price']:,.0f}, availability {item.get('availability_status', 'unknown')}, score {item.get('score', 0):.2f}"
            for item in listings
        )
        text += (
            f". Kwa data iliyopo, {best['title']} ina score ya juu; hii si guarantee."
            if current.language != "en"
            else f". Based on the available data, {best['title']} ranks higher; this is not a guarantee."
        )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "comparison",
            "results": listings,
            "recommendations": listings,
            "matched_properties": listings,
            "map": self._map_payload(listings, preferences.university or preferences.location),
            "warnings": search.get("warnings", []),
            "tools_used": ["get_accommodation", "calculate_route", "rank_accommodations"],
        }

    @staticmethod
    def _general_response(preferences: SearchPreferences) -> Dict[str, Any]:
        text = (
            "Before renting, verify the exact address, total monthly cost, water/electricity arrangements, "
            "security, contract terms, and visit the property."
            if preferences.language == "en"
            else "Kabla ya kupanga, hakikisha address halisi, gharama zote za mwezi, maji/umeme, usalama, "
            "masharti ya mkataba na tembelea eneo."
        )
        return {
            "message": text,
            "reply": text,
            "response": text,
            "intent": "general_student_advice",
            "results": [],
            "recommendations": [],
            "map": None,
            "tools_used": [],
        }

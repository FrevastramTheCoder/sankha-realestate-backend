"""Database-backed accommodation tools for NyumbaSalama AI.

Every listing in a response comes from the existing SQLAlchemy ``Property``
table and every route value comes from ``GeoService``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.models import Property
from app.services.geo_knowledge import normalize, resolve_places
from app.services.gis import GeoService, haversine_km
from app.services.swahili_parser import (
    MIN_SUPPORTED_BUDGET,
    institution_override,
    parse_budget,
    parse_radius,
    parse_travel_time,
)


logger = logging.getLogger("nyumbasalama.accommodation")


ROOM_TYPE_ALIASES = {
    "single": "single room",
    "single room": "single room",
    "chumba kimoja": "single room",
    "shared": "shared room",
    "shared room": "shared room",
    "roommate": "shared room",
    "hostel": "hostel",
    "hostel room": "hostel",
    "bedsitter": "bedsitter",
    "self contained": "self-contained",
    "self-contained": "self-contained",
    "apartment": "apartment",
    "flat": "apartment",
    "studio": "studio",
    "house": "house",
    "nyumba": "house",
    "room": "room",
    "chumba": "room",
}

AMENITY_ALIASES = {
    "wifi": {"wifi", "wi fi", "internet"},
    "water": {"water", "maji"},
    "electricity": {"electricity", "umeme", "power"},
    "security": {"security", "usalama", "guard", "ulinzi"},
    "parking": {"parking", "maegesho"},
    "furnished": {"furnished", "samani", "fenicha"},
    "private bathroom": {"private bathroom", "bafu binafsi", "self contained"},
}


@dataclass
class SearchPreferences:
    university: Optional[Dict[str, Any]] = None
    location: Optional[Dict[str, Any]] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    room_type: Optional[str] = None
    amenities: List[str] = field(default_factory=list)
    max_travel_time_minutes: Optional[float] = None
    radius_km: Optional[float] = None
    mode: str = "driving"
    intent: str = "general_student_advice"
    language: str = "sw"
    places: List[Dict[str, Any]] = field(default_factory=list)
    available_only: bool = False
    self_contained: Optional[bool] = None
    furnished: Optional[bool] = None
    budget_below_minimum: bool = False
    rejected_budget: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "university": self.university,
            "university_key": self.university.get("key") if self.university else None,
            "institution": self.university.get("name") if self.university else None,
            "location": self.location,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "currency": "TZS",
            "period": "month",
            "room_type": self.room_type,
            "amenities": list(self.amenities),
            "max_travel_time_minutes": self.max_travel_time_minutes,
            "max_travel_minutes": self.max_travel_time_minutes,
            "radius_km": self.radius_km,
            "mode": self.mode,
            "transport_mode": self.mode,
            "intent": self.intent,
            "language": self.language,
            "available_only": self.available_only,
            "self_contained": self.self_contained,
            "furnished": self.furnished,
            "budget_below_minimum": self.budget_below_minimum,
            "rejected_budget": self.rejected_budget,
        }

    def as_public_state(self) -> Dict[str, Any]:
        data = self.as_dict()
        return {
            "intent": data.get("intent"),
            "institution": {
                "id": (self.university or {}).get("key"),
                "name": (self.university or {}).get("name"),
                "latitude": (self.university or {}).get("lat"),
                "longitude": (self.university or {}).get("lng"),
            }
            if self.university
            else None,
            "location": self.location,
            "budget_min": self.budget_min if self.budget_min is not None else MIN_SUPPORTED_BUDGET,
            "budget_max": self.budget_max,
            "currency": "TZS",
            "period": "month",
            "room_type": self.room_type,
            "self_contained": self.self_contained,
            "furnished": self.furnished,
            "max_travel_minutes": self.max_travel_time_minutes,
            "transport_mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SearchPreferences":
        if not data:
            return cls()
        university = data.get("university")
        return cls(
            university=university if isinstance(university, dict) else None,
            location=data.get("location") if isinstance(data.get("location"), dict) else None,
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            room_type=data.get("room_type"),
            amenities=list(data.get("amenities") or []),
            max_travel_time_minutes=data.get("max_travel_time_minutes") or data.get("max_travel_minutes"),
            radius_km=data.get("radius_km"),
            mode=data.get("mode") or data.get("transport_mode") or "driving",
            intent=data.get("intent") or "general_student_advice",
            language=data.get("language") or "sw",
            places=list(data.get("places") or []),
            available_only=bool(data.get("available_only")),
            self_contained=data.get("self_contained"),
            furnished=data.get("furnished"),
            budget_below_minimum=bool(data.get("budget_below_minimum")),
            rejected_budget=data.get("rejected_budget"),
        )


def detect_room_type(message: str) -> Optional[str]:
    text = normalize(message)
    for alias in sorted(ROOM_TYPE_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text):
            return ROOM_TYPE_ALIASES[alias]
    return None


def detect_amenities(message: str) -> List[str]:
    text = normalize(message)
    found: List[str] = []
    for canonical, aliases in AMENITY_ALIASES.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(normalize(alias))}(?![a-z0-9])", text) for alias in aliases):
            found.append(canonical)
    return found


def detect_language(message: str) -> str:
    text = normalize(message)
    swahili = (
        "nina",
        "natafuta",
        "karibu",
        "chumba",
        "nyumba",
        "bei",
        "nataka",
        "ni",
        "wapi",
        "maeneo",
        "sasa",
        "dakika",
        "bajeti",
        "elfu",
        "laki",
    )
    english = ("find", "room", "house", "hostel", "near", "budget", "where", "available", "how", "minutes", "area")
    has_sw = any(re.search(rf"\b{re.escape(word)}\b", text) for word in swahili)
    has_en = any(re.search(rf"\b{re.escape(word)}\b", text) for word in english)
    if has_sw and has_en:
        return "mixed"
    if has_en:
        return "en"
    if has_sw:
        return "sw"
    return "unknown"


def _has_any(text: str, words: Iterable[str]) -> bool:
    return any(bool(re.search(rf"\b{re.escape(word.strip())}\b", text)) for word in words)


def detect_intent(message: str, places: Sequence[Dict[str, Any]], preferences_hint: Optional[SearchPreferences] = None) -> str:
    text = normalize(message)
    if _has_any(text, ("hello", "hi", "habari", "jambo", "hujambo", "mambo")):
        return "greeting"
    if _has_any(text, ("help", "msaada", "nisaidie", "saidia")):
        return "help"
    if _has_any(text, ("compare", "linganisha", "kati ya", "which one is better")):
        return "comparison"
    if _has_any(text, ("how far", "umbali", "km ngapi", "kilomita", "route", "directions", "kutoka", "from ")):
        return "route_query" if _has_any(text, ("route", "directions", "how long", "muda", "dakika")) else "distance_query"

    housing = _has_any(
        text,
        (
            "room",
            "chumba",
            "hostel",
            "accommodation",
            "housing",
            "nyumba",
            "rent",
            "pango",
            "kupanga",
            "kodisha",
            "bedsitter",
            "single",
            "shared",
            "bajeti",
            "budget",
            "elfu",
            "laki",
            "nataka",
            "natafuta",
        ),
    )
    availability = _has_any(
        text,
        ("available", "availability", "zipo", "ipo sasa", "inapatikana", "vilivyopo", "currently", "present"),
    )
    nearby = _has_any(text, ("near", "karibu", "maeneo gani", "area gani", "around", "nearby", "wapi"))
    budget = parse_budget(message)
    travel = parse_travel_time(message)

    # Slot answers during an active housing conversation.
    if preferences_hint and (budget[0] is not None or budget[1] is not None or travel is not None):
        return "accommodation_search"

    if housing or availability or budget[0] is not None or budget[1] is not None or travel is not None:
        return "accommodation_search"
    if places and nearby:
        return "location_search"
    if places and _has_any(text, ("student", "mwanafunzi", "good area", "eneo zuri", "inafaa")):
        return "general_student_advice"
    return "general_student_advice"


def _apply_budget_floor(budget_min: Optional[int], budget_max: Optional[int]) -> Tuple[Optional[int], Optional[int], bool, Optional[int]]:
    """Enforce minimum supported monthly budget without silently raising user values."""

    rejected = None
    below = False
    if budget_max is not None and budget_max < MIN_SUPPORTED_BUDGET:
        rejected = budget_max
        below = True
        budget_max = None
    if budget_min is not None and budget_min < MIN_SUPPORTED_BUDGET:
        rejected = budget_min if rejected is None else rejected
        below = True
        budget_min = None
    if budget_max is not None and budget_min is None:
        budget_min = MIN_SUPPORTED_BUDGET
    return budget_min, budget_max, below, rejected


def parse_preferences(message: str, active: Optional[SearchPreferences] = None) -> SearchPreferences:
    text = normalize(message)
    places = resolve_places(message)
    university = next((place for place in places if place.get("type") in {"university", "college"}), None)
    location = next((place for place in places if place.get("type") not in {"university", "college"}), None)
    budget_min, budget_max = parse_budget(message)
    budget_min, budget_max, below, rejected = _apply_budget_floor(budget_min, budget_max)
    language = detect_language(message)
    amenities = detect_amenities(message)
    room_type = detect_room_type(message)
    self_contained = True if "self-contained" in (room_type or "") or "self contained" in text else None
    furnished = True if "furnished" in amenities else None
    return SearchPreferences(
        university=university,
        location=location,
        budget_min=budget_min,
        budget_max=budget_max,
        room_type=room_type,
        amenities=amenities,
        max_travel_time_minutes=parse_travel_time(message),
        radius_km=parse_radius(message),
        mode="walking" if re.search(r"\bwalk(?:ing)?\b|kwa miguu", text) else "driving",
        intent=detect_intent(message, places, active),
        language=language if language != "unknown" else "sw",
        places=places,
        available_only=_has_any(
            text,
            ("available", "availability", "zipo", "ipo sasa", "inapatikana", "vilivyopo", "currently", "present"),
        ),
        self_contained=self_contained,
        furnished=furnished,
        budget_below_minimum=below,
        rejected_budget=rejected,
    )


def merge_preferences(base: SearchPreferences, update: SearchPreferences, message: str = "") -> SearchPreferences:
    """Merge a new user turn without discarding known conversation context."""

    merged = replace(base, amenities=list(base.amenities), places=list(base.places))
    for name in (
        "budget_min",
        "budget_max",
        "room_type",
        "max_travel_time_minutes",
        "radius_km",
        "self_contained",
        "furnished",
    ):
        value = getattr(update, name)
        if value is not None:
            setattr(merged, name, value)

    if update.budget_below_minimum:
        merged.budget_below_minimum = True
        merged.rejected_budget = update.rejected_budget
    elif update.budget_max is not None or update.budget_min is not None:
        merged.budget_below_minimum = False
        merged.rejected_budget = None

    if update.amenities:
        merged.amenities = list(dict.fromkeys([*merged.amenities, *update.amenities]))
    if update.mode and update.mode != "driving":
        merged.mode = update.mode
    if update.language and update.language != "unknown":
        merged.language = update.language
    if update.available_only:
        merged.available_only = True

    # Institution/location updates: replace only when user supplies a new one.
    if update.university is not None:
        if not base.university or institution_override(message) or update.university.get("key") != (base.university or {}).get("key"):
            merged.university = update.university
    if update.location is not None:
        merged.location = update.location

    if update.places:
        if update.intent in {"distance_query", "route_query"}:
            by_key = {place.get("key"): place for place in merged.places}
            by_key.update({place.get("key"): place for place in update.places})
            merged.places = list(by_key.values())
        else:
            # Keep prior places while adding new ones; do not wipe context.
            by_key = {place.get("key"): place for place in merged.places}
            by_key.update({place.get("key"): place for place in update.places})
            merged.places = list(by_key.values())

    # Prefer accommodation_search once housing slots appear.
    if update.intent == "accommodation_search" or (
        update.intent not in {"greeting", "help", "distance_query", "route_query", "comparison", "location_search"}
        and (
            merged.budget_max is not None
            or merged.budget_min is not None
            or merged.max_travel_time_minutes is not None
            or merged.room_type
        )
    ):
        merged.intent = "accommodation_search"
    elif update.intent and update.intent != "general_student_advice":
        merged.intent = update.intent
    elif base.intent == "accommodation_search":
        merged.intent = "accommodation_search"
    else:
        merged.intent = update.intent or base.intent

    if merged.budget_max is not None and merged.budget_min is None:
        merged.budget_min = MIN_SUPPORTED_BUDGET

    return merged


def parse_amenities(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item) for item in value]
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                raw_values = [str(item) for item in decoded]
            else:
                raw_values = re.split(r"[,;|]", text)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_values = re.split(r"[,;|]", text)
    else:
        raw_values = [str(value)]
    return [item.strip() for item in raw_values if item.strip()]


def _canonical_amenities(values: Iterable[str]) -> Set[str]:
    canonical: Set[str] = set()
    for value in values:
        normalized = normalize(value)
        canonical.add(
            next(
                (
                    key
                    for key, aliases in AMENITY_ALIASES.items()
                    if normalized in {normalize(alias) for alias in aliases} or key == normalized
                ),
                normalized,
            )
        )
    return canonical


def _availability(record: Property) -> str:
    value = getattr(record, "availability_status", None)
    if value is None:
        value = getattr(record, "status", None)
    if value is None or not str(value).strip():
        return "unknown"
    normalized = normalize(str(value))
    if normalized in {"available", "inapatikana", "vacant", "open", "active"}:
        return "available"
    if normalized in {
        "unavailable",
        "unavailable now",
        "rented",
        "occupied",
        "im ekodishwa",
        "imekodishwa",
        "closed",
    }:
        return "unavailable"
    return "unknown"


def _verification(record: Property) -> Optional[str]:
    value = getattr(record, "verification_status", None)
    if value is None:
        verified = getattr(record, "verified", None)
        return "verified" if verified is True else None
    return str(value) if str(value).strip() else None


def _coordinates(record: Property) -> Optional[Dict[str, float]]:
    try:
        lat = float(getattr(record, "latitude", None))
        lng = float(getattr(record, "longitude", None))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {"lat": lat, "lng": lng}


def _room_type(record: Property, amenities: Sequence[str]) -> Optional[str]:
    value = getattr(record, "room_type", None) or getattr(record, "property_type", None)
    if value:
        normalized = normalize(str(value))
        for alias, canonical in ROOM_TYPE_ALIASES.items():
            if normalized == normalize(alias):
                return canonical
        return str(value)
    stored_text = normalize(f"{record.title or ''} {record.description or ''}")
    for phrase, canonical in (
        ("single room", "single room"),
        ("shared room", "shared room"),
        ("hostel", "hostel"),
        ("bedsitter", "bedsitter"),
        ("self contained", "self-contained"),
        ("apartment", "apartment"),
        ("studio", "studio"),
        ("room", "room"),
        ("chumba", "room"),
    ):
        if phrase in stored_text:
            return canonical
    return None


def _matches_room_type(record: Property, requested: Optional[str], amenities: Sequence[str]) -> bool:
    if not requested:
        return True
    requested = ROOM_TYPE_ALIASES.get(normalize(requested), requested)
    actual = _room_type(record, amenities)
    if not actual:
        # Do not drop listings that never stored room_type when user asked generically.
        if requested == "room":
            return True
        return False
    if requested == "room":
        return actual in {"room", "single room", "shared room", "hostel", "self-contained", "bedsitter"}
    return normalize(actual) == normalize(requested)


def _budget_score(price: float, preferences: SearchPreferences) -> float:
    if preferences.budget_max is not None:
        if price > preferences.budget_max:
            return 0.0
        return min(1.0, price / max(1, preferences.budget_max))
    if preferences.budget_min is not None:
        return 1.0 if price >= preferences.budget_min else 0.0
    return 0.5


def _score_listing(
    item: Dict[str, Any], preferences: SearchPreferences, requested_amenities: Set[str]
) -> Tuple[float, Dict[str, float]]:
    budget = _budget_score(float(item["price"]), preferences)
    if item.get("duration_minutes") is not None:
        commute = max(0.0, 1.0 - min(float(item["duration_minutes"]) / 60.0, 1.0))
    elif item.get("straight_line_distance_km") is not None:
        commute = max(0.0, 1.0 - min(float(item["straight_line_distance_km"]) / 15.0, 1.0))
    else:
        commute = 0.35
    room = 1.0 if preferences.room_type and item.get("room_type") else 0.5
    listing_amenities = _canonical_amenities(item.get("amenities", []))
    amenity = len(requested_amenities & listing_amenities) / len(requested_amenities) if requested_amenities else 0.5
    rating = float(item.get("rating") or 0)
    quality = min(1.0, rating / 5.0) if rating else 0.35
    if item.get("verification_status") and normalize(str(item["verification_status"])) in {"verified", "approved"}:
        quality = min(1.0, quality * 0.7 + 0.3)
    availability = 1.0 if item.get("availability_status") == "available" else 0.35
    components = {
        "budget_fit": round(budget, 4),
        "commute": round(commute, 4),
        "room_type": room,
        "amenities": round(amenity, 4),
        "quality": round(quality, 4),
        "availability": availability,
    }
    # Travel time first when user set a commute constraint.
    if preferences.max_travel_time_minutes is not None:
        score = (
            commute * 0.35
            + budget * 0.25
            + availability * 0.15
            + room * 0.10
            + amenity * 0.10
            + quality * 0.05
        )
    else:
        score = (
            budget * 0.25
            + commute * 0.25
            + room * 0.15
            + amenity * 0.15
            + quality * 0.10
            + availability * 0.10
        )
    return round(score, 4), components


def _why(item: Dict[str, Any], preferences: SearchPreferences) -> List[str]:
    reasons: List[str] = []
    if preferences.budget_max is not None and item["price"] <= preferences.budget_max:
        reasons.append("within the requested budget")
    if preferences.budget_min is not None and item["price"] >= preferences.budget_min:
        reasons.append("meets the minimum budget")
    if preferences.room_type and item.get("room_type"):
        reasons.append("matches the stored room type")
    if preferences.amenities:
        matched = _canonical_amenities(item.get("amenities", [])) & set(preferences.amenities)
        if matched:
            reasons.append("has listed " + ", ".join(sorted(matched)))
    if item.get("duration_minutes") is not None:
        reasons.append(f"route is {item['duration_minutes']:.0f} minutes by {item.get('mode', 'driving')}")
    elif item.get("straight_line_distance_km") is not None:
        reasons.append(f"{item['straight_line_distance_km']:.2f} km straight-line from the anchor")
    if item.get("availability_status") == "available":
        reasons.append("marked available in the listing record")
    elif item.get("availability_status") == "unknown":
        reasons.append("availability is not recorded")
    return reasons or ["returned from the accommodation database"]


def _serialize_record(record: Property, coordinates: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    amenities = parse_amenities(getattr(record, "amenities", None))
    property_type = getattr(record, "property_type", None)
    return {
        "property_id": record.id,
        "title": record.title,
        "description": record.description,
        "price": float(record.price),
        "rental_period": getattr(record, "rental_period", None) or "monthly",
        "location": record.location,
        "neighborhood": getattr(record, "neighborhood", None),
        "ward": getattr(record, "ward", None),
        "district": getattr(record, "district", None),
        "university": record.university,
        "property_type": property_type,
        "room_type": _room_type(record, amenities),
        "amenities": amenities,
        "image_url": record.image_url,
        "images": parse_amenities(getattr(record, "images", None)),
        "contact": getattr(record, "contact", None),
        "rating": getattr(record, "rating", None),
        "review_count": getattr(record, "review_count", None),
        "verification_status": _verification(record),
        "availability_status": _availability(record),
        "coordinates": coordinates,
        "coordinate_precision": "stored_listing_coordinate" if _coordinates(record) else "approximate_place_centroid",
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


async def _listing_coordinates(record: Property, geo: GeoService) -> Optional[Dict[str, float]]:
    stored = _coordinates(record)
    if stored:
        return stored
    location = getattr(record, "location", None)
    if not location:
        return None
    resolved = await geo.resolve(str(location))
    if resolved.get("status") != "resolved":
        return None
    return {"lat": float(resolved["lat"]), "lng": float(resolved["lng"])}


def _approx_radius_km(preferences: SearchPreferences) -> float:
    """Stage-1 spatial prefilter radius before routing."""

    if preferences.radius_km is not None:
        return float(preferences.radius_km)
    if preferences.max_travel_time_minutes is not None:
        # Rough driving envelope: ~0.6 km/min with buffer, min 3 km, max 25 km.
        return max(3.0, min(25.0, float(preferences.max_travel_time_minutes) * 0.6 + 2.0))
    return 12.0


async def search_accommodations(
    db: Session,
    preferences: SearchPreferences,
    geo: GeoService,
    limit: int = 5,
) -> Dict[str, Any]:
    """Two-stage search: DB/spatial filter, then routing on a shortlist."""

    anchor = preferences.university or preferences.location
    requested_amenities = _canonical_amenities(preferences.amenities)
    warnings: List[str] = []
    records = db.query(Property).order_by(Property.created_at.desc(), Property.id.desc()).all()

    stage1: List[Tuple[Property, Dict[str, Any], Optional[Dict[str, float]]]] = []
    unknown_availability = False
    unavailable_count = 0
    approx_radius = _approx_radius_km(preferences)

    for record in records:
        availability = _availability(record)
        if availability == "unknown":
            unknown_availability = True
        if availability == "unavailable":
            unavailable_count += 1
            continue
        if preferences.available_only and availability != "available":
            continue

        price = float(record.price)
        # Supported housing floor.
        if price < MIN_SUPPORTED_BUDGET:
            continue
        if preferences.budget_min is not None and price < preferences.budget_min:
            continue
        if preferences.budget_max is not None and price > preferences.budget_max:
            continue

        amenities = parse_amenities(getattr(record, "amenities", None))
        if not _matches_room_type(record, preferences.room_type, amenities):
            continue
        if requested_amenities and not requested_amenities.issubset(_canonical_amenities(amenities)):
            continue

        coordinates = _coordinates(record)
        item_preview = _serialize_record(record, coordinates)
        if anchor and coordinates:
            straight = haversine_km(anchor, coordinates)
            item_preview["straight_line_distance_km"] = round(straight, 3)
            if straight > approx_radius:
                continue
        stage1.append((record, item_preview, coordinates))

    # Prefer closer candidates when anchor exists; cap routing work.
    if anchor:
        stage1.sort(key=lambda row: row[1].get("straight_line_distance_km") if row[1].get("straight_line_distance_km") is not None else 9999)
    route_limit = 40
    stage1 = stage1[:route_limit]

    candidates: List[Dict[str, Any]] = []
    route_failures = 0

    async def _enrich(record: Property, item: Dict[str, Any], coordinates: Optional[Dict[str, float]]) -> Optional[Dict[str, Any]]:
        nonlocal route_failures
        coords = coordinates
        if coords is None and anchor:
            coords = await _listing_coordinates(record, geo)
            if coords:
                item["coordinates"] = coords
                item["straight_line_distance_km"] = round(haversine_km(anchor, coords), 3)
                if item["straight_line_distance_km"] > approx_radius:
                    return None

        if anchor and coords:
            route = await geo.route(anchor, coords, preferences.mode)
            item["route"] = route
            item["route_status"] = route.get("status")
            item["mode"] = preferences.mode
            item["road_distance_km"] = route.get("distance_km")
            item["duration_minutes"] = route.get("duration_minutes")
            if preferences.max_travel_time_minutes is not None:
                if route.get("status") != "ok":
                    route_failures += 1
                    return None
                if float(route["duration_minutes"]) > preferences.max_travel_time_minutes:
                    return None
        elif anchor:
            item["route_status"] = "unavailable"
            item["road_distance_km"] = None
            item["duration_minutes"] = None
            if preferences.radius_km is not None or preferences.max_travel_time_minutes is not None:
                return None

        item["score"], item["score_components"] = _score_listing(item, preferences, requested_amenities)
        item["why"] = _why(item, preferences)
        return item

    # Resolve missing coords + routes with limited concurrency.
    semaphore = asyncio.Semaphore(5)

    async def _bounded(row: Tuple[Property, Dict[str, Any], Optional[Dict[str, float]]]):
        async with semaphore:
            return await _enrich(*row)

    enriched = await asyncio.gather(*[_bounded(row) for row in stage1], return_exceptions=True)
    for result in enriched:
        if isinstance(result, Exception):
            logger.warning("listing enrich failed: %s", result)
            route_failures += 1
            continue
        if result:
            candidates.append(result)

    if preferences.available_only and not candidates and unknown_availability:
        warnings.append("No listing is explicitly marked available; existing records remain unknown until updated.")
    if not preferences.available_only and unknown_availability and candidates:
        warnings.append(
            "Some returned records have unknown availability because the database does not record a current status."
        )
    if anchor and any(item.get("route_status") != "ok" for item in candidates):
        warnings.append("Road distance and travel time are shown only when the routing engine returns them.")
    if route_failures and preferences.max_travel_time_minutes is not None and not candidates:
        warnings.append("Routing was unavailable for candidate listings, so travel-time filtering could not complete.")
    if unavailable_count:
        warnings.append(f"{unavailable_count} unavailable listing(s) were excluded.")

    candidates.sort(
        key=lambda item: (
            -item.get("score", 0),
            item.get("duration_minutes") is None,
            item.get("duration_minutes") if item.get("duration_minutes") is not None else float("inf"),
            item.get("road_distance_km") is None,
            item.get("road_distance_km") or float("inf"),
            item["price"],
            item.get("property_id") or 0,
        )
    )
    return {
        "results": candidates[: max(1, min(limit, 20))],
        "total": len(candidates),
        "anchor": anchor,
        "warnings": list(dict.fromkeys(warnings)),
        "ranking": ranking_documentation(),
        "search_executed": True,
        "stage1_count": len(stage1),
        "route_failures": route_failures,
    }


def get_accommodation(db: Session, property_id: int) -> Optional[Dict[str, Any]]:
    record = db.query(Property).filter(Property.id == property_id).first()
    return _serialize_record(record, _coordinates(record)) if record else None


def check_availability(db: Session, property_id: int) -> Optional[Dict[str, Any]]:
    record = db.query(Property).filter(Property.id == property_id).first()
    if not record:
        return None
    return {
        "property_id": record.id,
        "availability_status": _availability(record),
        "source": "database",
        "is_currently_available": _availability(record) == "available",
    }


def summarize_prices(db: Session) -> Dict[str, Any]:
    prices = [float(value[0]) for value in db.query(Property.price).all() if value[0] is not None]
    if not prices:
        return {"status": "unavailable", "source": "database", "count": 0}
    return {
        "status": "actual_listing_range",
        "source": "database",
        "count": len(prices),
        "min_price": min(prices),
        "max_price": max(prices),
        "currency": "TZS",
        "rental_period": "monthly",
        "is_estimate": False,
    }


def ranking_documentation() -> Dict[str, Any]:
    return {
        "method": "transparent weighted score",
        "weights": {
            "travel_time": 0.35,
            "budget_fit": 0.25,
            "availability": 0.15,
            "room_type": 0.10,
            "amenities": 0.10,
            "quality": 0.05,
        },
        "notes": [
            "Road distance and duration are used only when the configured routing engine returns status=ok.",
            "Unknown availability is never presented as available.",
            "Missing rating, verification, amenities, or coordinates reduce confidence rather than being invented.",
            f"Listings below TZS {MIN_SUPPORTED_BUDGET:,} monthly are excluded from housing search.",
        ],
    }


# Re-export parsers for tests and other modules.
__all__ = [
    "SearchPreferences",
    "parse_budget",
    "parse_travel_time",
    "parse_radius",
    "parse_preferences",
    "merge_preferences",
    "search_accommodations",
    "get_accommodation",
    "check_availability",
    "summarize_prices",
    "ranking_documentation",
    "MIN_SUPPORTED_BUDGET",
]

"""Deterministic geographic services used by NyumbaSalama.

Local place data is used first so common Dar es Salaam queries are fast and
do not spend a geocoder request.  Coordinates from the curated place layer
represent place/campus centroids; they are labelled as approximate and are
not presented as an exact address.  Unknown places can be resolved through
Nominatim, while road distance and duration always come from a routing
engine.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import httpx

from app.services.geo_knowledge import PLACES, normalize, resolve_places


logger = logging.getLogger("nyumbasalama.gis")

CoordinateInput = Union[str, Dict[str, Any]]


DAR_ES_SALAAM_BOUNDS = {
    "min_lat": -7.25,
    "max_lat": -6.35,
    "min_lng": 38.85,
    "max_lng": 39.65,
}


def haversine_km(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Return geodesic distance in kilometres between two coordinates."""

    lat1, lng1, lat2, lng2 = map(
        math.radians,
        (float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])),
    )
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def _valid_coordinate(lat: Any, lng: Any) -> bool:
    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        return False

    return (
        math.isfinite(lat_value)
        and math.isfinite(lng_value)
        and -90 <= lat_value <= 90
        and -180 <= lng_value <= 180
    )


def _inside_dar(lat: float, lng: float) -> bool:
    return (
        DAR_ES_SALAAM_BOUNDS["min_lat"] <= lat <= DAR_ES_SALAAM_BOUNDS["max_lat"]
        and DAR_ES_SALAAM_BOUNDS["min_lng"] <= lng <= DAR_ES_SALAAM_BOUNDS["max_lng"]
    )


class ExpiringCache:
    """Small process-local TTL cache suitable for geocoder and route reads."""

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 1000) -> None:
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_size = max(10, max_size)
        self._values: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        item = self._values.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= time.monotonic():
            self._values.pop(key, None)
            return None
        return copy.deepcopy(value)

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        if len(self._values) >= self.max_size and key not in self._values:
            oldest_key = min(self._values, key=lambda current: self._values[current][0])
            self._values.pop(oldest_key, None)
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        self._values[key] = (time.monotonic() + max(1, ttl), copy.deepcopy(value))


@dataclass
class ResolvedLocation:
    status: str
    query: str
    name: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    source: Optional[str] = None
    precision: Optional[str] = None
    confidence: Optional[float] = None
    place_type: Optional[str] = None
    district: Optional[str] = None
    ward: Optional[str] = None
    key: Optional[str] = None
    error: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None

    def as_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": self.status,
            "query": self.query,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "source": self.source,
            "precision": self.precision,
            "confidence": self.confidence,
            "type": self.place_type,
            "district": self.district,
            "ward": self.ward,
            "key": self.key,
        }
        if self.error:
            result["error"] = self.error
        if self.candidates:
            result["candidates"] = self.candidates
        return result


def _local_place(place: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "resolved",
        "query": place.get("name", ""),
        "name": place.get("name"),
        "lat": float(place["lat"]),
        "lng": float(place["lng"]),
        "source": "curated_place_layer",
        "precision": "approximate_place_centroid",
        "confidence": 0.85,
        "type": place.get("type"),
        "district": place.get("district"),
        "ward": place.get("ward") or None,
        "key": place.get("key"),
    }


class GeoService:
    """Geocoding, reverse geocoding, and routing tool implementation."""

    def __init__(
        self,
        geocoder_url: Optional[str] = None,
        routing_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.geocoder_url = (
            geocoder_url or os.getenv("GEOCODER_BASE_URL", "https://nominatim.openstreetmap.org")
        ).rstrip("/")
        self.routing_url = (
            routing_url or os.getenv("ROUTING_BASE_URL", "https://router.project-osrm.org")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv("GEO_HTTP_TIMEOUT", "6"))
        self.geocoding_enabled = os.getenv("GEOCODING_ENABLED", "true").lower() == "true"
        self.routing_enabled = os.getenv("ROUTING_ENABLED", "true").lower() == "true"
        self.user_agent = os.getenv(
            "GEOCODER_USER_AGENT", "NyumbaSalama/1.0 (+https://nyumbasalama.com/contact)"
        )
        self.cache = ExpiringCache(
            ttl_seconds=int(os.getenv("GEO_CACHE_TTL_SECONDS", "86400")),
            max_size=int(os.getenv("GEO_CACHE_MAX_SIZE", "1000")),
        )
        self._nominatim_lock = asyncio.Lock()
        self._last_nominatim_request = 0.0

    @staticmethod
    def _place_candidates(query: str) -> List[Dict[str, Any]]:
        normalized_query = normalize(query)
        if not normalized_query:
            return []

        exact: List[Dict[str, Any]] = []
        for place in PLACES.values():
            names = [place.get("name", "")] + list(place.get("aliases") or [])
            if any(normalize(name) == normalized_query for name in names if name):
                exact.append(place)
        if exact:
            return exact
        return resolve_places(query)

    @staticmethod
    def _coordinate_from_input(value: CoordinateInput) -> Optional[Dict[str, Any]]:
        if isinstance(value, dict):
            lat = value.get("lat", value.get("latitude"))
            lng = value.get("lng", value.get("lon", value.get("longitude")))
            if _valid_coordinate(lat, lng):
                return {
                    "status": "resolved",
                    "query": "coordinates",
                    "name": value.get("name") or "Provided coordinates",
                    "lat": float(lat),
                    "lng": float(lng),
                    "source": "request",
                    "precision": "provided_coordinate",
                    "confidence": 1.0,
                    "type": "coordinate",
                }
            return None

        if not isinstance(value, str):
            return None

        match = re.match(
            r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$",
            value,
        )
        if not match:
            return None
        lat, lng = float(match.group(1)), float(match.group(2))
        if not _valid_coordinate(lat, lng):
            return None
        return {
            "status": "resolved",
            "query": value,
            "name": "Provided coordinates",
            "lat": lat,
            "lng": lng,
            "source": "request",
            "precision": "provided_coordinate",
            "confidence": 1.0,
            "type": "coordinate",
        }

    async def resolve(self, query: CoordinateInput) -> Dict[str, Any]:
        """Resolve a name or coordinate pair without inventing a location."""

        if isinstance(query, dict):
            coordinate = self._coordinate_from_input(query)
            if coordinate:
                return coordinate
            return ResolvedLocation(
                status="invalid", query="coordinates", error="Invalid latitude or longitude."
            ).as_dict()

        if not isinstance(query, str) or not query.strip():
            return ResolvedLocation(status="invalid", query="", error="Location is required.").as_dict()

        coordinate = self._coordinate_from_input(query)
        if coordinate:
            return coordinate

        normalized_query = normalize(query)
        cache_key = f"geocode:{normalized_query}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        candidates = self._place_candidates(query)
        if candidates:
            # The curated layer has already handled exact aliases and longer
            # names before broad matching, so the first result is deterministic.
            result = _local_place(candidates[0])
            self.cache.set(cache_key, result)
            return result

        if not self.geocoding_enabled:
            result = ResolvedLocation(
                status="not_found",
                query=query,
                error="This location is not in the curated Dar es Salaam layer.",
            ).as_dict()
            self.cache.set(cache_key, result, ttl_seconds=300)
            return result

        result = await self._nominatim_geocode(query)
        self.cache.set(cache_key, result, ttl_seconds=86400 if result["status"] == "resolved" else 300)
        return result

    async def _nominatim_geocode(self, query: str) -> Dict[str, Any]:
        params = {
            "q": f"{query}, Dar es Salaam, Tanzania",
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": "5",
            "bounded": "1",
            "viewbox": "38.85,-6.35,39.65,-7.25",
        }
        payload = await self._request_json(
            f"{self.geocoder_url}/search", params=params, nominatim=True
        )
        if payload is None:
            return ResolvedLocation(
                status="unavailable",
                query=query,
                error="The geocoding service is unavailable right now.",
            ).as_dict()

        candidates: List[Dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            try:
                lat = float(item["lat"])
                lng = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not _inside_dar(lat, lng):
                continue
            candidates.append(
                {
                    "name": item.get("display_name", query),
                    "lat": lat,
                    "lng": lng,
                    "type": item.get("type"),
                    "importance": float(item.get("importance") or 0),
                }
            )

        if not candidates:
            return ResolvedLocation(
                status="not_found",
                query=query,
                error="No confidently matching Dar es Salaam location was found.",
            ).as_dict()

        candidates.sort(key=lambda item: item["importance"], reverse=True)
        best = candidates[0]
        return {
            "status": "resolved",
            "query": query,
            "name": best["name"],
            "lat": best["lat"],
            "lng": best["lng"],
            "source": "nominatim",
            "precision": "geocoder_result",
            "confidence": min(0.9, max(0.55, best["importance"] or 0.55)),
            "type": best.get("type"),
            "district": None,
            "ward": None,
            "candidates": candidates[:5],
        }

    async def reverse(self, lat: float, lng: float) -> Dict[str, Any]:
        if not _valid_coordinate(lat, lng):
            return ResolvedLocation(
                status="invalid", query="coordinates", error="Invalid latitude or longitude."
            ).as_dict()

        local_candidates = []
        point = {"lat": float(lat), "lng": float(lng)}
        for place in PLACES.values():
            distance = haversine_km(point, {"lat": place["lat"], "lng": place["lng"]})
            if distance <= 2.5:
                local_candidates.append((distance, place))
        if local_candidates:
            local_candidates.sort(key=lambda item: item[0])
            result = _local_place(local_candidates[0][1])
            result["query"] = f"{lat},{lng}"
            result["precision"] = "nearest_curated_place"
            result["distance_to_place_km"] = round(local_candidates[0][0], 3)
            return result

        if not self.geocoding_enabled:
            return ResolvedLocation(
                status="not_found", query=f"{lat},{lng}", error="No local reverse-geocode match found."
            ).as_dict()

        payload = await self._request_json(
            f"{self.geocoder_url}/reverse",
            params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": "1"},
            nominatim=True,
        )
        if not isinstance(payload, dict) or not payload.get("display_name"):
            return ResolvedLocation(
                status="unavailable",
                query=f"{lat},{lng}",
                error="The reverse-geocoding service is unavailable right now.",
            ).as_dict()
        return {
            "status": "resolved",
            "query": f"{lat},{lng}",
            "name": payload["display_name"],
            "lat": float(lat),
            "lng": float(lng),
            "source": "nominatim",
            "precision": "reverse_geocoder_result",
            "confidence": 0.75,
            "type": payload.get("type"),
            "district": (payload.get("address") or {}).get("suburb"),
            "ward": None,
        }

    async def route(
        self,
        origin: CoordinateInput,
        destination: CoordinateInput,
        mode: str = "driving",
    ) -> Dict[str, Any]:
        """Return route truth from OSRM or an explicitly configured engine."""

        if not self.routing_enabled:
            return self._route_unavailable("Routing is disabled by configuration.")

        profile = self._routing_profile(mode)
        supported_modes = {
            item.strip().lower()
            for item in os.getenv("ROUTING_SUPPORTED_MODES", "driving").split(",")
            if item.strip()
        }
        if profile not in supported_modes:
            return self._route_unavailable(
                f"Routing mode '{mode}' is not configured. Available modes: {', '.join(sorted(supported_modes))}."
            )

        origin_result = await self.resolve(origin)
        destination_result = await self.resolve(destination)
        if origin_result.get("status") != "resolved":
            return self._route_unavailable("Origin could not be confidently resolved.", origin_result, destination_result)
        if destination_result.get("status") != "resolved":
            return self._route_unavailable(
                "Destination could not be confidently resolved.", origin_result, destination_result
            )

        origin_point = {"lat": origin_result["lat"], "lng": origin_result["lng"]}
        destination_point = {"lat": destination_result["lat"], "lng": destination_result["lng"]}
        cache_key = (
            f"route:{profile}:{origin_point['lat']:.5f},{origin_point['lng']:.5f}:"
            f"{destination_point['lat']:.5f},{destination_point['lng']:.5f}"
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        route_base_url = os.getenv(f"ROUTING_{profile.upper()}_BASE_URL", self.routing_url).rstrip("/")
        url = (
            f"{route_base_url}/route/v1/{profile}/"
            f"{origin_point['lng']},{origin_point['lat']};"
            f"{destination_point['lng']},{destination_point['lat']}"
        )
        payload = await self._request_json(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        if not isinstance(payload, dict) or payload.get("code") != "Ok" or not payload.get("routes"):
            result = self._route_unavailable("The routing engine could not calculate this route.", origin_result, destination_result)
            self.cache.set(cache_key, result, ttl_seconds=120)
            return result

        selected = payload["routes"][0]
        distance_meters = float(selected.get("distance") or 0)
        duration_seconds = float(selected.get("duration") or 0)
        result = {
            "status": "ok",
            "mode": profile,
            "source": "osrm",
            "distance_meters": round(distance_meters, 1),
            "distance_km": round(distance_meters / 1000, 3),
            "duration_seconds": round(duration_seconds, 1),
            "duration_minutes": round(duration_seconds / 60, 1),
            "geometry": selected.get("geometry"),
            "route_geometry": selected.get("geometry"),
            "origin": origin_result,
            "destination": destination_result,
        }
        self.cache.set(cache_key, result, ttl_seconds=int(os.getenv("ROUTE_CACHE_TTL_SECONDS", "1800")))
        return result

    @staticmethod
    def _routing_profile(mode: str) -> str:
        normalized = normalize(mode or "driving")
        return {
            "car": "driving",
            "drive": "driving",
            "driving": "driving",
            "walk": "walking",
            "walking": "walking",
            "bike": "cycling",
            "bicycle": "cycling",
            "cycling": "cycling",
        }.get(normalized, normalized or "driving")

    @staticmethod
    def _route_unavailable(
        error: str,
        origin: Optional[Dict[str, Any]] = None,
        destination: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "unavailable",
            "source": None,
            "distance_meters": None,
            "distance_km": None,
            "duration_seconds": None,
            "duration_minutes": None,
            "geometry": None,
            "route_geometry": None,
            "error": error,
            "origin": origin,
            "destination": destination,
        }

    async def _request_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        nominatim: bool = False,
    ) -> Optional[Any]:
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        attempts = 2
        for attempt in range(attempts):
            try:
                if nominatim:
                    async with self._nominatim_lock:
                        elapsed = time.monotonic() - self._last_nominatim_request
                        delay = max(0.0, 1.0 - elapsed)
                        if delay:
                            await asyncio.sleep(delay)
                        self._last_nominatim_request = time.monotonic()
                        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
                            response = await client.get(url, params=params)
                else:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
                        response = await client.get(url, params=params)

                if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as error:
                if attempt == attempts - 1:
                    logger.warning("Geospatial HTTP request failed: %s", type(error).__name__)
                    return None
        return None

    @staticmethod
    def universities() -> List[Dict[str, Any]]:
        official_names = {
            "udsm": "University of Dar es Salaam",
            "aru": "Ardhi University",
            "ifm": "Institute of Finance Management",
            "muhas": "Muhimbili University of Health and Allied Sciences",
            "dit": "Dar es Salaam Institute of Technology",
            "cbe": "College of Business Education",
            "duce": "Dar es Salaam University College of Education",
            "nit": "National Institute of Transport",
            "out": "Open University of Tanzania",
            "hkmu": "Hubert Kairuki Memorial University",
            "isw": "Institute of Social Work",
            "dmi": "Dar es Salaam Maritime Institute",
            "mzumbe_dar": "Mzumbe University Dar es Salaam Campus",
        }
        records = []
        for place in PLACES.values():
            if place.get("type") not in {"university", "college"}:
                continue
            nearby_keys = place.get("neighbors") or []
            nearby_name = PLACES.get(nearby_keys[0], {}).get("name") if nearby_keys else None
            records.append(
                {
                    "key": place.get("key"),
                    "official_name": official_names.get(place.get("key"), place.get("name")),
                    "name": place.get("name"),
                    "aliases": place.get("aliases", []),
                    "address": place.get("description"),
                    "lat": place.get("lat"),
                    "lng": place.get("lng"),
                    "campus": place.get("name"),
                    "municipality": place.get("district"),
                    "ward": place.get("ward"),
                    "neighborhood": nearby_name,
                    "coordinate_source": "curated_place_layer",
                    "coordinate_precision": "approximate_place_centroid",
                }
            )
        return records


geo_service = GeoService()

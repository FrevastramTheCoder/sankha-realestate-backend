"""Deterministic geocoding, distance, routing, and spatial search APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.accommodation_tools import SearchPreferences, parse_preferences, ranking_documentation, search_accommodations
from app.services.gis import GeoService, geo_service, haversine_km


router = APIRouter(prefix="/geo", tags=["GIS"])


class CoordinateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Union[str, CoordinateInput]
    destination: Union[str, CoordinateInput]
    mode: str = Field(default="driving", min_length=2, max_length=20)


class AccommodationSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(default="", max_length=2000)
    university: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    budget_min: int | None = Field(default=None, ge=0, le=10_000_000)
    budget_max: int | None = Field(default=None, ge=0, le=10_000_000)
    room_type: str | None = Field(default=None, max_length=60)
    amenities: List[str] = Field(default_factory=list, max_length=20)
    max_travel_time_minutes: float | None = Field(default=None, ge=1, le=240)
    radius_km: float | None = Field(default=None, ge=0.1, le=100)
    mode: str = Field(default="driving", min_length=2, max_length=20)
    available_only: bool = False
    limit: int = Field(default=5, ge=1, le=20)


def _input_value(value: Union[str, CoordinateInput]) -> Union[str, Dict[str, float]]:
    return value.model_dump() if isinstance(value, CoordinateInput) else value


@router.get("/geocode")
async def geocode_location(q: str = Query(..., min_length=2, max_length=160)):
    result = await geo_service.resolve(q)
    if result.get("status") != "resolved":
        raise HTTPException(status_code=404, detail=result.get("error") or "Location could not be resolved.")
    return result


@router.get("/reverse")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    result = await geo_service.reverse(lat, lng)
    if result.get("status") != "resolved":
        raise HTTPException(status_code=404, detail=result.get("error") or "Coordinates could not be resolved.")
    return result


@router.get("/universities")
async def list_universities(q: str | None = Query(default=None, max_length=120)):
    universities = geo_service.universities()
    if q:
        query = q.casefold().strip()
        universities = [
            university
            for university in universities
            if query in university["name"].casefold()
            or query in university["official_name"].casefold()
            or any(query in alias.casefold() for alias in university.get("aliases", []))
        ]
    return {"universities": universities, "total": len(universities)}


@router.get("/ranking")
async def ranking_rules():
    return ranking_documentation()


@router.get("/distance")
async def calculate_distance(
    origin: str = Query(..., min_length=2, max_length=160),
    destination: str = Query(..., min_length=2, max_length=160),
    mode: str = Query(default="driving", min_length=2, max_length=20),
):
    origin_result = await geo_service.resolve(origin)
    destination_result = await geo_service.resolve(destination)
    if origin_result.get("status") != "resolved" or destination_result.get("status") != "resolved":
        raise HTTPException(status_code=404, detail="Both origin and destination must be confidently resolved.")
    origin_point = {"lat": origin_result["lat"], "lng": origin_result["lng"]}
    destination_point = {"lat": destination_result["lat"], "lng": destination_result["lng"]}
    straight = haversine_km(origin_point, destination_point)
    route = await geo_service.route(origin, destination, mode)
    return {
        "origin": origin_result,
        "destination": destination_result,
        "straight_line_km": round(straight, 3),
        "route": route,
        "road_distance_km": route.get("distance_km"),
        "duration_minutes": route.get("duration_minutes"),
    }


@router.post("/route")
async def calculate_route(request: RouteRequest):
    result = await geo_service.route(_input_value(request.origin), _input_value(request.destination), request.mode)
    if result.get("status") != "ok":
        raise HTTPException(status_code=503, detail=result.get("error") or "Route unavailable.")
    return result


@router.get("/route")
async def calculate_route_get(
    origin: str = Query(..., min_length=2, max_length=160),
    destination: str = Query(..., min_length=2, max_length=160),
    mode: str = Query(default="driving", min_length=2, max_length=20),
):
    result = await geo_service.route(origin, destination, mode)
    if result.get("status") != "ok":
        raise HTTPException(status_code=503, detail=result.get("error") or "Route unavailable.")
    return result


@router.post("/accommodations/search")
async def search_listings(request: AccommodationSearchRequest, db: Session = Depends(get_db)):
    preferences = parse_preferences(request.message) if request.message else SearchPreferences()
    if request.university:
        resolved = await geo_service.resolve(request.university)
        if resolved.get("status") != "resolved":
            raise HTTPException(status_code=404, detail="University could not be resolved.")
        preferences.university = resolved
    if request.location:
        resolved = await geo_service.resolve(request.location)
        if resolved.get("status") != "resolved":
            raise HTTPException(status_code=404, detail="Location could not be resolved.")
        preferences.location = resolved
    for field_name in ("budget_min", "budget_max", "room_type", "max_travel_time_minutes", "radius_km", "mode", "available_only"):
        value = getattr(request, field_name)
        if value is not None:
            setattr(preferences, field_name, value)
    if request.amenities:
        preferences.amenities = request.amenities
    return await search_accommodations(db, preferences, geo_service, request.limit)

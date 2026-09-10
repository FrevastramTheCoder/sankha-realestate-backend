"""Clean accommodation search and detail APIs."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.accommodation_tools import SearchPreferences, check_availability, get_accommodation, parse_preferences, search_accommodations, summarize_prices
from app.services.gis import geo_service


router = APIRouter(tags=["Accommodations"])


async def _preferences(
    q: Optional[str],
    university: Optional[str],
    location: Optional[str],
    min_price: Optional[int],
    max_price: Optional[int],
    room_type: Optional[str],
    amenities: List[str],
    radius_km: Optional[float],
    max_travel_time: Optional[float],
    mode: str,
    available_only: bool,
) -> SearchPreferences:
    preferences = parse_preferences(q or "") if q else SearchPreferences()
    if university:
        resolved = await geo_service.resolve(university)
        if resolved.get("status") != "resolved":
            raise HTTPException(status_code=404, detail="University could not be confidently resolved.")
        preferences.university = resolved
    if location:
        resolved = await geo_service.resolve(location)
        if resolved.get("status") != "resolved":
            raise HTTPException(status_code=404, detail="Location could not be confidently resolved.")
        preferences.location = resolved
    if min_price is not None:
        preferences.budget_min = min_price
    if max_price is not None:
        preferences.budget_max = max_price
    if room_type:
        preferences.room_type = room_type
    if amenities:
        preferences.amenities = amenities
    if radius_km is not None:
        preferences.radius_km = radius_km
    if max_travel_time is not None:
        preferences.max_travel_time_minutes = max_travel_time
    preferences.mode = mode
    preferences.available_only = available_only or preferences.available_only
    return preferences


@router.get("/accommodations")
async def list_accommodations(
    q: Optional[str] = Query(default=None, max_length=2000),
    university: Optional[str] = Query(default=None, max_length=120),
    location: Optional[str] = Query(default=None, max_length=120),
    min_price: Optional[int] = Query(default=None, ge=0, le=10_000_000),
    max_price: Optional[int] = Query(default=None, ge=0, le=10_000_000),
    room_type: Optional[str] = Query(default=None, max_length=60),
    amenities: List[str] = Query(default=[]),
    radius_km: Optional[float] = Query(default=None, ge=0.1, le=100),
    max_travel_time: Optional[float] = Query(default=None, ge=1, le=240),
    mode: str = Query(default="driving", min_length=2, max_length=20),
    available_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    preferences = await _preferences(q, university, location, min_price, max_price, room_type, amenities, radius_km, max_travel_time, mode, available_only)
    return await search_accommodations(db, preferences, geo_service, limit)


@router.get("/search")
async def search_endpoint(
    q: str = Query(..., min_length=1, max_length=2000),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    preferences = parse_preferences(q)
    return await search_accommodations(db, preferences, geo_service, limit)


@router.get("/accommodations/price-summary")
async def accommodation_price_summary(db: Session = Depends(get_db)):
    return summarize_prices(db)


@router.get("/accommodations/{property_id}/availability")
async def accommodation_availability(property_id: int, db: Session = Depends(get_db)):
    result = check_availability(db, property_id)
    if not result:
        raise HTTPException(status_code=404, detail="Accommodation not found.")
    return result


@router.get("/accommodations/{property_id}")
async def accommodation_detail(property_id: int, db: Session = Depends(get_db)):
    result = get_accommodation(db, property_id)
    if not result:
        raise HTTPException(status_code=404, detail="Accommodation not found.")
    return result

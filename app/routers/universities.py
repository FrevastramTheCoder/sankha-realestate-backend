"""University/campus discovery endpoints backed by the curated place layer."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.gis import geo_service


router = APIRouter(tags=["Universities"])


def _universities():
    return geo_service.universities()


@router.get("/universities")
async def get_universities(q: str | None = Query(default=None, max_length=120)):
    records = _universities()
    if q:
        query = q.casefold().strip()
        records = [
            record for record in records
            if query in record["key"].casefold()
            or query in record["name"].casefold()
            or query in record["official_name"].casefold()
            or any(query in alias.casefold() for alias in record.get("aliases", []))
        ]
    return {"universities": records, "total": len(records)}


@router.get("/universities/{university_id}")
async def get_university(university_id: str):
    normalized = university_id.casefold().strip()
    record = next(
        (
            item for item in _universities()
            if item["key"].casefold() == normalized
            or item["name"].casefold() == normalized
            or item["official_name"].casefold() == normalized
            or any(alias.casefold() == normalized for alias in item.get("aliases", []))
        ),
        None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="University or campus not found.")
    return record

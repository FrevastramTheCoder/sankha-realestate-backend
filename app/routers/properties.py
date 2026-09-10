from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models import Property
from app.dependencies import get_current_user_required
from app.services.accommodation_tools import parse_amenities

router = APIRouter(prefix="/properties", tags=["properties"])

class PropertyResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    price: float
    location: str
    university: Optional[str] = None
    property_type: Optional[str] = None
    amenities: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    image_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: Optional[str] = None


def serialize_property(property: Property):
    images = parse_amenities(getattr(property, "images", None))
    if not images and property.image_url:
        images = [property.image_url]
    return {
        "id": property.id,
        "title": property.title,
        "description": property.description,
        "price": property.price,
        "location": property.location,
        "university": property.university,
        "property_type": property.property_type,
        "amenities": parse_amenities(property.amenities),
        "images": images,
        "bedrooms": property.bedrooms,
        "bathrooms": property.bathrooms,
        "image_url": property.image_url,
        "latitude": property.latitude,
        "longitude": property.longitude,
        "room_type": getattr(property, "room_type", None),
        "rental_period": getattr(property, "rental_period", None) or "monthly",
        "availability_status": getattr(property, "availability_status", None) or "unknown",
        "verification_status": getattr(property, "verification_status", None),
        "rating": getattr(property, "rating", None),
        "review_count": getattr(property, "review_count", None),
        "contact": getattr(property, "contact", None),
        "neighborhood": getattr(property, "neighborhood", None),
        "ward": getattr(property, "ward", None),
        "district": getattr(property, "district", None),
        "type": getattr(property, "room_type", None) or property.property_type,
        "status": getattr(property, "availability_status", None) or "UNKNOWN",
        "agent": {"name": "Property owner", "phone": getattr(property, "contact", None)},
        "created_at": property.created_at.isoformat() if property.created_at else None,
    }

@router.get("/")
async def get_properties(
    q: Optional[str] = Query(None, description="Search query"),
    limit: int = Query(20, ge=1, le=50, description="Number of results"),
    db: Session = Depends(get_db)
):
    try:
        query = db.query(Property)
        
        # Filter by search query
        if q:
            q_lower = q.lower()
            query = query.filter(
                Property.title.contains(q) | 
                Property.description.contains(q) |
                Property.location.contains(q)
            )
        
        properties = query.limit(limit).all()
        
        return {
            "properties": [serialize_property(p) for p in properties],
            "total": query.count()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{property_id}")
async def get_property(
    property_id: int,
    db: Session = Depends(get_db)
):
    try:
        property = db.query(Property).filter(Property.id == property_id).first()
        if not property:
            raise HTTPException(status_code=404, detail="Property not found")
        
        return serialize_property(property)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def create_property(
    title: str,
    description: Optional[str] = None,
    price: float = 0,
    location: str = "",
    university: str = "",
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    current_user: dict = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    try:
        new_property = Property(
            title=title,
            description=description,
            price=price,
            location=location,
            university=university,
            latitude=latitude,
            longitude=longitude,
            created_at=datetime.now()
        )
        db.add(new_property)
        db.commit()
        db.refresh(new_property)
        
        return {
            "message": "Property created successfully",
            "property": {
                "id": new_property.id,
                "title": new_property.title,
                "description": new_property.description,
                "price": new_property.price,
                "location": new_property.location,
                "university": new_property.university,
                "latitude": new_property.latitude,
                "longitude": new_property.longitude
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

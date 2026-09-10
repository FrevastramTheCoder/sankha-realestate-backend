from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/reviews", tags=["reviews"])

class Review(BaseModel):
    id: int
    property_id: int
    user_id: str
    rating: int
    comment: str
    created_at: str

sample_reviews = [
    {"id": 1, "property_id": 1, "user_id": "user1", "rating": 5, "comment": "Chumba kizuri sana!", "created_at": datetime.now().isoformat()},
]

@router.get("/")
async def get_reviews(property_id: Optional[int] = None):
    try:
        if property_id:
            reviews = [r for r in sample_reviews if r["property_id"] == property_id]
        else:
            reviews = sample_reviews
        return {"reviews": reviews, "total": len(reviews)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/favorites", tags=["favorites"])

class Favorite(BaseModel):
    id: int
    user_id: str
    property_id: int

sample_favorites = []

@router.get("/")
async def get_favorites(user_id: Optional[str] = None):
    try:
        if user_id:
            favs = [f for f in sample_favorites if f["user_id"] == user_id]
        else:
            favs = sample_favorites
        return {"favorites": favs, "total": len(favs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

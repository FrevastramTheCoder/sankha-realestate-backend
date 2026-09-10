from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
async def get_users(db: Session = Depends(get_db)):
    try:
        users = db.query(User).all()
        return {
            "users": [
                {
                    "id": u.id,
                    "name": u.name,
                    "email": u.email,
                    "phone": u.phone,
                    "role": u.role,
                    "created_at": u.created_at.isoformat() if u.created_at else None
                }
                for u in users
            ],
            "total": len(users)
        }
    except Exception as e:
        return {"users": [], "total": 0}
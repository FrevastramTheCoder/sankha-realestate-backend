from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user_required
from app.models import Property, User

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(current_user: dict, db: Session) -> User:
    user = db.query(User).filter(User.id == current_user.get("id")).first()
    if not user or str(user.role).lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

@router.get("/")
async def get_admin_dashboard(
    current_user: dict = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    require_admin(current_user, db)
    return {
        "message": "Admin dashboard",
        "stats": {
            "total_users": db.query(User).count(),
            "total_properties": db.query(Property).count(),
            "total_reviews": 0,
        }
    }

@router.get("/users")
async def get_admin_users(
    current_user: dict = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    require_admin(current_user, db)
    users = db.query(User).order_by(User.created_at.desc()).all()
    return {
        "data": [
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "role": user.role,
                "is_approved": user.is_approved,
                "can_upload": user.can_upload,
                "is_banned": user.is_banned,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            for user in users
        ],
        "total": len(users),
    }


@router.get("/stats")
async def get_admin_stats(
    current_user: dict = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    require_admin(current_user, db)
    return {
        "totalUsers": db.query(User).count(),
        "totalProperties": db.query(Property).count(),
        "totalVideos": 0,
    }


@router.get("/properties")
async def get_admin_properties(
    current_user: dict = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    require_admin(current_user, db)
    properties = db.query(Property).order_by(Property.created_at.desc()).all()
    return {
        "data": [serialize_admin_property(property) for property in properties],
        "total": len(properties),
    }


def serialize_admin_property(property: Property):
    return {
        "id": str(property.id),
        "title": property.title,
        "price": property.price,
        "location": property.location,
        "university": property.university,
        "status": "AVAILABLE",
        "createdAt": property.created_at.isoformat() if property.created_at else None,
    }

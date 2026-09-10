from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
import bcrypt

from app.database import get_db
from app.models import User
from app.dependencies import create_access_token, get_current_user_required

router = APIRouter(prefix="/auth", tags=["auth"])

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

@router.post("/register")
async def register(data: dict, db: Session = Depends(get_db)):
    try:
        full_name = data.get("fullName") or data.get("full_name") or data.get("name")
        email = (data.get("email") or "").strip().lower()
        phone_number = data.get("phoneNumber") or data.get("phone_number") or data.get("phone")
        password = data.get("password")
        requested_role = str(data.get("role", "student")).lower()
        role = requested_role if requested_role in {"student", "agent", "property_owner"} else "student"
        
        if not full_name:
            raise HTTPException(status_code=400, detail="Full name is required")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        if not password:
            raise HTTPException(status_code=400, detail="Password is required")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        # Check if user exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Create user
        hashed_password = hash_password(password)
        user_id = str(uuid.uuid4())
        
        new_user = User(
            id=user_id,
            name=full_name,
            email=email,
            phone=phone_number,
            password=hashed_password,
            role=role,
            created_at=datetime.now()
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return {
            "success": True,
            "message": "Account created successfully",
            "user": {
                "id": new_user.id,
                "name": new_user.name,
                "email": new_user.email,
                "phone": new_user.phone,
                "role": new_user.role
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/login")
async def login(data: dict, db: Session = Depends(get_db)):
    try:
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password are required")
        
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not verify_password(password, user.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_access_token({
            "sub": user.id,
            "email": user.email,
            "role": user.role,
        })
        
        return {
            "success": True,
            "message": "Login successful",
            "token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "role": user.role,
                "avatar": user.avatar
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/me")
async def get_current_user(
    current_user: dict = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "message": "User profile",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "avatar": user.avatar,
        }
    }

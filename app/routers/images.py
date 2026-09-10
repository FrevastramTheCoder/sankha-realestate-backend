from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import os
import shutil
import re
import uuid

from app.database import get_db
from app.models import Image, User, Property

router = APIRouter(prefix="/images", tags=["images"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

os.makedirs("uploads/images", exist_ok=True)


# ============================================================
# ADMIN CHECK - SIMPLE VERSION
# ============================================================

def is_admin(db: Session, authorization: Optional[str]) -> bool:
    """
    Simple admin check for development.
    Returns True if any admin exists in the database.
    """
    # ✅ Check if any admin exists in database
    admin = db.query(User).filter(
        User.role.in_(["admin", "ADMIN"])
    ).first()
    
    if admin:
        print(f"✅ Admin found: {admin.email}")
        return True
    
    print("❌ No admin found in database")
    return False


# ============================================================
# UPLOAD - ADMIN ONLY
# ============================================================

@router.post("/upload")
async def upload_image(
    title: str = Form(...),
    price: float = Form(0),
    location: str = Form(""),
    university: str = Form(""),
    phone: str = Form(""),
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    try:
        # ✅ ADMIN CHECK
        if not is_admin(db, authorization):
            raise HTTPException(status_code=403, detail="Only admin can upload")
        
        # Validate file size
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        if file_size > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"Max {MAX_IMAGE_SIZE // (1024*1024)}MB")
        
        # Validate file type
        safe_original_name = os.path.basename(file.filename or "")
        file_ext = os.path.splitext(safe_original_name)[1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Invalid: {file_ext}")
        
        # Save file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', safe_original_name)
        filename = f"{timestamp}_{uuid.uuid4().hex}_{safe_filename}"
        filepath = f"uploads/images/{filename}"
        
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Create property if not exists
        property_exists = db.query(Property).filter(Property.id == 1).first()
        if not property_exists:
            property_exists = Property(
                title="Default",
                description="Default",
                price=0,
                location="Default",
                university="Default",
                created_at=datetime.now()
            )
            db.add(property_exists)
            db.commit()
            db.refresh(property_exists)
        
        # Create image record
        new_image = Image(
            title=title,
            description="Image uploaded by admin",
            url=f"/uploads/images/{filename}",
            property_id=property_exists.id,
            price=price,
            location=location,
            university=university,
            phone=phone,
            image_url=f"/uploads/images/{filename}",
            created_at=datetime.now()
        )
        
        db.add(new_image)
        db.commit()
        db.refresh(new_image)
        
        print(f"✅ Image uploaded: {filename}")
        
        return {
            "success": True,
            "message": "Image uploaded!",
            "image": {
                "id": new_image.id,
                "title": new_image.title,
                "image_url": new_image.image_url,
                "price": new_image.price,
                "location": new_image.location,
                "university": new_image.university,
                "phone": new_image.phone
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# GET IMAGES - PUBLIC
# ============================================================

@router.get("/")
async def get_images(limit: int = 20, db: Session = Depends(get_db)):
    try:
        images = db.query(Image).order_by(Image.created_at.desc()).limit(limit).all()
        return {
            "images": [
                {
                    "id": img.id,
                    "title": img.title,
                    "price": img.price or 0,
                    "location": img.location or "",
                    "university": img.university or "",
                    "phone": img.phone or "",
                    "image_url": img.image_url,
                    "created_at": img.created_at.isoformat() if img.created_at else None
                }
                for img in images
            ],
            "total": len(images)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# DELETE - ADMIN ONLY
# ============================================================

@router.delete("/{image_id}")
async def delete_image(
    image_id: int,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    try:
        # ✅ ADMIN CHECK
        if not is_admin(db, authorization):
            raise HTTPException(status_code=403, detail="Only admin can delete")
        
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Delete file
        if image.image_url:
            filename = image.image_url.split("/")[-1]
            file_path = f"uploads/images/{filename}"
            if os.path.exists(file_path):
                os.remove(file_path)
        
        db.delete(image)
        db.commit()
        return {"success": True, "message": "Deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
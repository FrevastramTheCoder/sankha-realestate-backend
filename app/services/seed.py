from sqlalchemy.orm import Session
from app.models import User
import bcrypt
import uuid
from datetime import datetime

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def seed_admin(db: Session):
    """Create admin user if not exists"""
    try:
        # Check if admin already exists
        admin = db.query(User).filter(User.email == "admin@nyumbasalama.com").first()
        
        if admin:
            print("Admin user already exists, skipping seed")
            return
        
        # Create admin if not exists
        print("Creating admin user")
        admin_id = str(uuid.uuid4())
        hashed_password = hash_password("Admin@123")
        
        new_admin = User(
            id=admin_id,
            name="Admin",
            email="admin@nyumbasalama.com",
            phone="0712345679",
            password=hashed_password,
            role="admin",
            is_approved=True,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        db.add(new_admin)
        db.commit()
        print("Admin user created successfully")
        
    except Exception as e:
        db.rollback()
        print(f"Error creating admin: {str(e)}")


from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

# ============================================================
# BASE
# ============================================================

Base = declarative_base()


# ============================================================
# USER MODEL
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    phone = Column(String(20), nullable=True)
    password = Column(String(255), nullable=False)
    role = Column(String(20), default="student")
    is_approved = Column(Boolean, default=False)
    can_upload = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    avatar = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ============================================================
# PROPERTY MODEL
# ============================================================

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    location = Column(String(200), nullable=False)
    university = Column(String(100), nullable=True)
    property_type = Column(String(50), nullable=True)
    amenities = Column(Text, nullable=True)
    image_url = Column(String(255), nullable=True)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


# ============================================================
# IMAGE / LISTING MODEL
# ============================================================

class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    url = Column(String(255), nullable=False)
    property_id = Column(Integer, nullable=False)
    price = Column(Float, default=0)
    location = Column(String(200), nullable=True)
    university = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    image_url = Column(String(255), nullable=True)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

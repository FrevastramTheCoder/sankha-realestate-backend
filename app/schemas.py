from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    phone_number: Optional[str] = None
    password: str
    role: Optional[str] = "student"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    phone_number: Optional[str]
    role: str
    created_at: datetime
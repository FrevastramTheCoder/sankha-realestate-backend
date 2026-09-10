from datetime import datetime, timedelta
import os
import secrets
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from typing import Optional, Dict, Any

from app.config import settings

# Configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
_runtime_secret = secrets.token_urlsafe(32)


def _secret_key() -> str:
    configured = os.getenv("JWT_SECRET") or settings.JWT_SECRET
    if configured:
        return configured
    return _runtime_secret

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, _secret_key(), algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token with longer expiry
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, _secret_key(), algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT token
    """
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user_required(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """
    Dependency for protected routes - returns current user or raises 401
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # You can fetch user from database here
        # For now, return basic user info
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": payload.get("role", "student"),
            "authenticated": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user_optional(token: str = Depends(oauth2_scheme)) -> Optional[Dict[str, Any]]:
    """
    Dependency for optional authentication - returns user or None
    """
    if not token:
        return None
    
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": payload.get("role", "student"),
            "authenticated": True
        }
    except Exception:
        return None

def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """
    Alias for get_current_user_required for backward compatibility
    """
    return get_current_user_required(token)

# For testing purposes
def get_test_user():
    """
    Get a test user for development
    """
    return {
        "id": "test-user-123",
        "email": "test@example.com",
        "name": "Test User",
        "role": "student",
        "authenticated": True
    }

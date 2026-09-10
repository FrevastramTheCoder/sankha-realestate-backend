import uuid
import json
from datetime import datetime, timedelta
from typing import Optional
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def sanitize_user(user: dict) -> dict:
    safe_user = user.copy()
    safe_user.pop("password", None)
    return safe_user

def parse_json_field(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value

def json_field_to_str(value):
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value

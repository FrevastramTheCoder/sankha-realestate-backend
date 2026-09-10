"""Public NyumbaSalama AI chat API."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.ai_orchestrator import NyumbaSalamaAI
from app.services.gis import geo_service


router = APIRouter(tags=["AI"])
ai = NyumbaSalamaAI(geo_service)
_rate_limits: Dict[str, List[float]] = {}
_RATE_LIMIT = 30
_RATE_WINDOW_SECONDS = 60


class ChatHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4000)


class UserLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=120)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=100)
    # Kept as an input alias for existing frontend clients during migration.
    session_id: Optional[str] = Field(default=None, max_length=100)
    user_location: Optional[UserLocation] = None
    history: List[ChatHistoryItem] = Field(default_factory=list, max_length=20)


def _check_rate_limit(request: Request) -> None:
    now = time.monotonic()
    client_key = request.client.host if request.client else "unknown"
    recent = [stamp for stamp in _rate_limits.get(client_key, []) if now - stamp < _RATE_WINDOW_SECONDS]
    if len(recent) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many AI requests. Please try again shortly.")
    recent.append(now)
    _rate_limits[client_key] = recent


async def _chat(request: ChatRequest, http_request: Request, db: Session) -> Dict[str, Any]:
    _check_rate_limit(http_request)
    conversation_id = request.conversation_id or request.session_id
    return await ai.respond(
        message=request.message,
        db=db,
        conversation_id=conversation_id,
        history=[item.model_dump() for item in request.history],
        user_location=request.user_location.model_dump() if request.user_location else None,
    )


@router.post("/ai/chat")
async def ai_chat(request: ChatRequest, http_request: Request, db: Session = Depends(get_db)):
    return await _chat(request, http_request, db)


@router.post("/chat")
async def chat_compatibility(request: ChatRequest, http_request: Request, db: Session = Depends(get_db)):
    """Compatibility path for the existing frontend and older clients."""

    return await _chat(request, http_request, db)


@router.get("/ai/conversations/{conversation_id}")
async def get_conversation_state(conversation_id: str, db: Session = Depends(get_db)):
    """Restore structured conversation state after refresh."""

    state = ai.store.get_state_dict(conversation_id, db)
    session = ai.store.get(conversation_id, db)
    return {
        "conversation_id": conversation_id,
        "session_id": conversation_id,
        "state": state,
        "preferences": session.get("preferences").as_dict()
        if session.get("preferences") is not None and hasattr(session.get("preferences"), "as_dict")
        else session.get("preferences"),
        "has_state": state is not None,
    }


@router.get("/ai/health")
async def ai_health():
    return {
        "status": "online",
        "service": "NyumbaSalama AI",
        "architecture": "deterministic tools with conversation orchestration",
        "chat_endpoint": "/api/ai/chat",
        "deterministic_tools": [
            "resolve_university",
            "resolve_location",
            "search_accommodations",
            "check_availability",
            "calculate_distance",
            "calculate_route",
            "rank_accommodations",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/chat/health")
async def chat_health_compatibility():
    return await ai_health()

"""Persistent conversation state backed by PostgreSQL/SQLite."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Conversation, ConversationMessage, ConversationState
from app.services.accommodation_tools import SearchPreferences


class ConversationStore:
    """Database-backed conversation memory with in-process fallback cache."""

    def __init__(self, max_sessions: int = 500, ttl_seconds: int = 86_400) -> None:
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def ensure_id(self, conversation_id: Optional[str] = None) -> str:
        return conversation_id or str(uuid.uuid4())

    def get(self, conversation_id: str, db: Optional[Session] = None) -> Dict[str, Any]:
        now = time.monotonic()
        if conversation_id in self._cache:
            session = self._cache[conversation_id]
            session["last_seen"] = now
            if db is not None:
                self._hydrate_from_db(conversation_id, session, db)
            return session

        session: Dict[str, Any] = {
            "last_results": [],
            "places": [],
            "preferences": None,
            "messages": [],
            "last_seen": now,
        }
        if db is not None:
            self._hydrate_from_db(conversation_id, session, db)
        self._cache[conversation_id] = session
        return session

    def _hydrate_from_db(self, conversation_id: str, session: Dict[str, Any], db: Session) -> None:
        try:
            row = db.query(ConversationState).filter(ConversationState.conversation_id == conversation_id).first()
            if not row:
                return
            payload = json.loads(row.state_json or "{}")
            if payload.get("preferences") and session.get("preferences") is None:
                session["preferences"] = SearchPreferences.from_dict(payload["preferences"])
            if payload.get("places") and not session.get("places"):
                session["places"] = payload["places"]
            if payload.get("last_results") and not session.get("last_results"):
                session["last_results"] = payload["last_results"]
        except Exception:
            # Corrupt/legacy rows must not break chat.
            return

    def save(
        self,
        conversation_id: str,
        session: Dict[str, Any],
        db: Optional[Session],
        *,
        user_message: Optional[str] = None,
        assistant_message: Optional[str] = None,
        response_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        session["last_seen"] = time.monotonic()
        self._cache[conversation_id] = session
        if db is None:
            return

        try:
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conversation:
                conversation = Conversation(id=conversation_id)
                db.add(conversation)

            preferences: Optional[SearchPreferences] = session.get("preferences")
            state_payload = {
                "preferences": preferences.as_dict() if isinstance(preferences, SearchPreferences) else preferences,
                "places": session.get("places") or [],
                "last_results": session.get("last_results") or [],
            }

            state_row = db.query(ConversationState).filter(ConversationState.conversation_id == conversation_id).first()
            if not state_row:
                state_row = ConversationState(conversation_id=conversation_id, state_json="{}")
                db.add(state_row)
            state_row.state_json = json.dumps(state_payload, default=str)
            state_row.updated_at = datetime.utcnow()
            conversation.updated_at = datetime.utcnow()

            if user_message:
                db.add(
                    ConversationMessage(
                        conversation_id=conversation_id,
                        role="user",
                        content=user_message,
                    )
                )
            if assistant_message:
                db.add(
                    ConversationMessage(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=assistant_message,
                        payload_json=json.dumps(response_payload or {}, default=str)[:20000],
                    )
                )
            db.commit()
        except Exception:
            db.rollback()

    def get_state_dict(self, conversation_id: str, db: Session) -> Optional[Dict[str, Any]]:
        session = self.get(conversation_id, db)
        preferences = session.get("preferences")
        if isinstance(preferences, SearchPreferences):
            return preferences.as_public_state()
        if isinstance(preferences, dict):
            return preferences
        return None

    def trim(self) -> None:
        now = time.monotonic()
        expired = [
            key for key, value in self._cache.items() if now - value.get("last_seen", now) > self.ttl_seconds
        ]
        for key in expired:
            self._cache.pop(key, None)
        if len(self._cache) > self.max_sessions:
            oldest = sorted(self._cache, key=lambda key: self._cache[key].get("last_seen", 0))
            for key in oldest[: len(self._cache) - self.max_sessions]:
                self._cache.pop(key, None)

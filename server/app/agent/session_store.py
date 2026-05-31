from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.product_repository import SearchConstraints


@dataclass
class SessionState:
    constraints: SearchConstraints = field(default_factory=SearchConstraints)
    pending_constraints: SearchConstraints | None = None
    pending_clarification: str | None = None
    last_product_ids: list[str] = field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState()
        return self._sessions[session_id]

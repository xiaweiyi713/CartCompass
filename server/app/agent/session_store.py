from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from app.config import SESSION_MAX_ENTRIES, SESSION_TTL_SECONDS
from app.rag.product_repository import SearchConstraints


@dataclass
class SessionState:
    constraints: SearchConstraints = field(default_factory=SearchConstraints)
    pending_constraints: SearchConstraints | None = None
    pending_clarification: str | None = None
    last_product_ids: list[str] = field(default_factory=list)


class SessionStore:
    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS, max_entries: int = SESSION_MAX_ENTRIES) -> None:
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._sessions: OrderedDict[str, tuple[float, SessionState]] = OrderedDict()

    def get(self, session_id: str) -> SessionState:
        now = time.time()
        self._prune(now)
        entry = self._sessions.pop(session_id, None)
        if entry:
            _, state = entry
        else:
            state = SessionState()
        self._sessions[session_id] = (now, state)
        self._enforce_limit()
        return state

    def size(self) -> int:
        self._prune(time.time())
        return len(self._sessions)

    def _prune(self, now: float) -> None:
        expired = [session_id for session_id, (seen_at, _) in self._sessions.items() if now - seen_at > self.ttl_seconds]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def _enforce_limit(self) -> None:
        while len(self._sessions) > self.max_entries:
            self._sessions.popitem(last=False)

from __future__ import annotations

from dataclasses import dataclass, field

from .utils import now_iso


@dataclass(slots=True)
class MemoryEvent:
    name: str
    payload: dict[str, object]
    created_at: str = field(default_factory=now_iso)

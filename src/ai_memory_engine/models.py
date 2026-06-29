from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .utils import now_iso


class MemoryKind(str, Enum):
    DECISION = "decision"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    FACT = "fact"
    TASK_CONTEXT = "task-context"
    OPEN_QUESTION = "open-question"


@dataclass(slots=True)
class MemorySource:
    session_id: str
    turn_index: int
    timestamp: str = field(default_factory=now_iso)


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    title: str
    kind: MemoryKind
    summary: str
    subject: str = ""
    value: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    sources: list[MemorySource] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    importance_score: float = 0.5
    updated_at: str = field(default_factory=now_iso)
    path: str | None = None


@dataclass(slots=True)
class MemoryCandidate:
    memory_id: str
    title: str
    kind: MemoryKind
    summary: str
    subject: str = ""
    value: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    confidence: float = 1.0
    importance_score: float = 0.5


@dataclass(slots=True)
class DocumentChunk:
    chunk_id: str
    memory_id: str
    path: str
    text: str
    chunk_hash: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    memory: MemoryRecord
    score: float
    reason: str


@dataclass(slots=True)
class PreparedTurn:
    turn_token: str
    user_message: str
    session_id: str
    project_path: str = ""
    retrieved_memories: list[SearchResult] = field(default_factory=list)
    related_entities: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    context_block: str = ""

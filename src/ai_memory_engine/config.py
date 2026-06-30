from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from shlex import split as shlex_split


def _parse_env_list(value: str) -> tuple[str, ...]:
    return tuple(item for item in (part.strip() for part in value.replace("\n", ",").split(",")) if item)


@dataclass(slots=True)
class EnginePaths:
    project_root: Path
    knowledge_root: Path
    journal_root: Path
    state_root: Path
    duckdb_path: Path
    vector_root: Path
    graph_root: Path
    manifest_path: Path
    pending_turns_root: Path

    @classmethod
    def for_project(cls, project_root: Path) -> "EnginePaths":
        state_root = project_root / ".ai-memory-engine"
        return cls(
            project_root=project_root,
            knowledge_root=project_root / "knowledge",
            journal_root=project_root / "journal",
            state_root=state_root,
            duckdb_path=state_root / "analytics.duckdb",
            vector_root=state_root / "vector",
            graph_root=state_root / "graph",
            manifest_path=state_root / "index_manifest.json",
            pending_turns_root=state_root / "pending_turns",
        )


@dataclass(slots=True)
class EngineConfig:
    paths: EnginePaths
    vector_backend: str = "lancedb"
    graph_backend: str = "ladybug"
    embedding_dimensions: int = 256
    default_top_k: int = 5
    ai_assist_command: tuple[str, ...] = ()
    ai_assist_timeout_seconds: int = 15
    locked_memory_ids: tuple[str, ...] = ()

    @classmethod
    def for_project(cls, project_root: str | Path) -> "EngineConfig":
        root = Path(project_root).resolve()
        command = os.environ.get("AI_MEMORY_ENGINE_ASSIST_COMMAND", "").strip()
        parsed_command = tuple(shlex_split(command, posix=os.name != "nt")) if command else ()
        timeout = int(os.environ.get("AI_MEMORY_ENGINE_ASSIST_TIMEOUT_SECONDS", "15"))
        locked_memory_ids = _parse_env_list(os.environ.get("AI_MEMORY_ENGINE_LOCKED_MEMORY_IDS", ""))
        return cls(
            paths=EnginePaths.for_project(root),
            ai_assist_command=parsed_command,
            ai_assist_timeout_seconds=timeout,
            locked_memory_ids=locked_memory_ids,
        )

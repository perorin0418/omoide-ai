from __future__ import annotations

import json
import subprocess

from .config import EngineConfig
from .models import MemoryCandidate, MemoryKind


class OptionalAIAssistant:
    def __init__(self, config: EngineConfig) -> None:
        self._command = tuple(config.ai_assist_command)
        self._timeout_seconds = config.ai_assist_timeout_seconds

    def refine_candidates(
        self,
        *,
        user_message: str,
        assistant_message: str,
        candidates: list[MemoryCandidate],
    ) -> list[MemoryCandidate]:
        if not self._command or not candidates:
            return candidates

        payload = {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "candidates": [self._candidate_to_json(candidate) for candidate in candidates],
        }
        try:
            completed = subprocess.run(
                self._command,
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout_seconds,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return candidates

        try:
            response = json.loads(completed.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return candidates

        refined_rows = response.get("candidates", response if isinstance(response, list) else [])
        if not isinstance(refined_rows, list):
            return candidates

        refined: list[MemoryCandidate] = []
        for row in refined_rows:
            candidate = self._candidate_from_json(row)
            if candidate is not None:
                refined.append(candidate)
        return refined or candidates

    def _candidate_to_json(self, candidate: MemoryCandidate) -> dict[str, object]:
        return {
            "memory_id": candidate.memory_id,
            "title": candidate.title,
            "kind": candidate.kind.value,
            "summary": candidate.summary,
            "subject": candidate.subject,
            "value": candidate.value,
            "category": candidate.category,
            "tags": candidate.tags,
            "details": candidate.details,
            "confidence": candidate.confidence,
            "importance_score": candidate.importance_score,
        }

    def _candidate_from_json(self, row: object) -> MemoryCandidate | None:
        if not isinstance(row, dict):
            return None
        try:
            return MemoryCandidate(
                memory_id=str(row["memory_id"]),
                title=str(row["title"]),
                kind=MemoryKind(str(row["kind"])),
                summary=str(row["summary"]),
                subject=str(row.get("subject", "")),
                value=str(row.get("value", "")),
                category=str(row.get("category", "general")),
                tags=[str(item) for item in row.get("tags", [])],
                details=[str(item) for item in row.get("details", [])],
                confidence=float(row.get("confidence", 1.0)),
                importance_score=float(row.get("importance_score", 0.5)),
            )
        except (KeyError, TypeError, ValueError):
            return None

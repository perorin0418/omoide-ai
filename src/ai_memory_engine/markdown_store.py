from __future__ import annotations

from pathlib import Path
import re

from .frontmatter import dump_frontmatter, split_frontmatter
from .models import MemoryRecord, MemorySource, MemoryKind
from .utils import now_iso, slugify


class MarkdownMemoryStore:
    def __init__(self, knowledge_root: Path) -> None:
        self.knowledge_root = knowledge_root
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.knowledge_root.mkdir(parents=True, exist_ok=True)

    def list_records(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for path in sorted(self.knowledge_root.rglob("*.md")):
            records.append(self.load_path(path))
        return records

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        for record in self.list_records():
            if record.memory_id == memory_id:
                return record
        return None

    def load_path(self, path: Path) -> MemoryRecord:
        metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
        title, summary, details = self._parse_body(body)
        sources = [
            MemorySource(
                session_id=item["session_id"],
                turn_index=int(item["turn"]),
                timestamp=item.get("timestamp", now_iso()),
            )
            for item in metadata.get("sources", [])
        ]
        kind = MemoryKind(metadata.get("kind", MemoryKind.FACT.value))
        return MemoryRecord(
            memory_id=metadata.get(
                "memory_id", slugify(str(path.relative_to(self.knowledge_root).with_suffix("")))
            ),
            title=title or path.stem.replace("-", " ").title(),
            kind=kind,
            summary=summary,
            subject=metadata.get("subject", ""),
            value=metadata.get("value", ""),
            category=metadata.get("category", self._default_category_for_path(path)),
            tags=list(metadata.get("tags", [])),
            sources=sources,
            details=details,
            importance_score=float(metadata.get("importance_score", 0.5)),
            updated_at=metadata.get("updated_at", now_iso()),
            path=str(path),
        )

    def upsert_record(self, record: MemoryRecord) -> Path:
        path = self.knowledge_root / self._resolve_relative_directory(record) / f"{slugify(record.memory_id)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "memory_id": record.memory_id,
            "kind": record.kind.value,
            "subject": record.subject,
            "value": record.value,
            "category": record.category or self._default_category_for_path(path),
            "tags": sorted(set(record.tags)),
            "sources": [
                {"session_id": item.session_id, "turn": item.turn_index, "timestamp": item.timestamp}
                for item in record.sources
            ],
            "importance_score": record.importance_score,
            "updated_at": record.updated_at,
        }
        body = self._render_body(record)
        if record.path and Path(record.path).resolve() != path.resolve():
            Path(record.path).unlink(missing_ok=True)
        path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")
        return path

    def delete_record(self, memory_id: str) -> Path | None:
        record = self.get_record(memory_id)
        if record and record.path:
            path = Path(record.path)
            path.unlink(missing_ok=True)
            return path
        return None

    def clear_records(self) -> list[Path]:
        deleted_paths: list[Path] = []
        for path in sorted(self.knowledge_root.rglob("*.md")):
            path.unlink(missing_ok=True)
            deleted_paths.append(path)
        self.ensure_layout()
        return deleted_paths

    def _resolve_relative_directory(self, record: MemoryRecord) -> Path:
        explicit = self._sanitize_explicit_directory(record.category)
        if explicit is not None:
            return explicit
        if "user-profile" in record.tags or record.subject.startswith("user_"):
            if "product" in record.tags or record.subject.startswith("user_current_"):
                return Path("user-profile") / "products"
            if record.kind == MemoryKind.PREFERENCE or record.subject == "user_preference":
                return Path("user-profile") / "preferences"
            return Path("user-profile")
        if record.kind == MemoryKind.PREFERENCE:
            return Path("user-profile") / "preferences"
        if record.kind == MemoryKind.DECISION:
            return Path("decisions")
        if record.kind == MemoryKind.CONSTRAINT:
            return Path("constraints")
        if record.kind == MemoryKind.TASK_CONTEXT:
            return Path("work-context") / "tasks"
        if record.kind == MemoryKind.OPEN_QUESTION:
            return Path("work-context") / "open-questions"
        return Path("reference")

    def _sanitize_explicit_directory(self, category: str) -> Path | None:
        normalized = category.strip().replace("\\", "/")
        if not normalized or normalized in {"general", "domain", "architecture", "aws", "oracle"}:
            return None
        if "/" not in normalized:
            return None
        parts = [slugify(part, "section") for part in normalized.split("/") if part.strip()]
        return Path(*parts) if parts else None

    def _default_category_for_path(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.knowledge_root)
        except ValueError:
            return "general"
        parent = relative.parent
        if not parent.parts:
            return "general"
        return "/".join(parent.parts)

    def _parse_body(self, body: str) -> tuple[str, str, list[str]]:
        lines = [line.rstrip() for line in body.strip().splitlines()]
        title = ""
        summary = ""
        details: list[str] = []
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("- Summary:"):
                summary = line.split(":", 1)[1].strip()
            elif line.startswith("- Value:"):
                continue
            elif line.startswith("- ") and not line.startswith("- Kind:"):
                details.append(line[2:].strip())
            elif line and not summary and not line.startswith("## "):
                summary = line.strip()
        return title, summary, details

    def _render_body(self, record: MemoryRecord) -> str:
        lines = [
            f"# {record.title}",
            "",
            f"- Kind: {record.kind.value}",
            f"- Summary: {record.summary}",
        ]
        if record.value:
            lines.append(f"- Value: {record.value}")
        for detail in record.details:
            lines.append(f"- {detail}")
        return "\n".join(lines)

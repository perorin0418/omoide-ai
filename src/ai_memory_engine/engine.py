from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from .ai_assist import OptionalAIAssistant
from .analytics import DuckDBAnalyticsStore
from .config import EngineConfig
from .embeddings import HashingEmbeddingProvider
from .entity_extraction import InMemoryGraphStore, LadybugGraphStore, SimpleEntityExtractor
from .events import MemoryEvent
from .extractors import RuleBasedMemoryExtractor
from .journal_store import DailyJournalStore
from .markdown_store import MarkdownMemoryStore
from .models import MemoryCandidate, MemoryKind, MemoryRecord, MemorySource, PreparedTurn, SearchResult
from .retrieval import HybridRetriever
from .synchronizer import Synchronizer
from .utils import cosine_similarity, jaccard_overlap, now_iso, slugify
from .vector_store import InMemoryVectorStore, LanceDBVectorStore


class MemoryEngine:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.paths = config.paths
        self.store = MarkdownMemoryStore(self.paths.knowledge_root)
        self.journal = DailyJournalStore(self.paths.journal_root)
        self.paths.pending_turns_root.mkdir(parents=True, exist_ok=True)
        self.embedder = HashingEmbeddingProvider(config.embedding_dimensions)
        self.entity_extractor = SimpleEntityExtractor()
        self.extractor = RuleBasedMemoryExtractor()
        self.ai_assistant = OptionalAIAssistant(config)
        self._initialize_runtime(synchronize=True)

    def AddKnowledge(self, **kwargs: object) -> dict[str, object]:
        return self.add_knowledge(**kwargs)

    def UpdateKnowledge(self, memory_id: str, summary: str, details: list[str] | None = None) -> dict[str, object]:
        return self.update_knowledge(memory_id, summary, details)

    def DeleteKnowledge(self, memory_id: str) -> dict[str, object]:
        return self.delete_knowledge(memory_id)

    def Search(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.search(query, top_k=top_k, session_id=session_id)

    def SemanticSearch(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.semantic_search(query, top_k=top_k, session_id=session_id)

    def GraphSearch(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.graph_search(query, top_k=top_k, session_id=session_id)

    def HybridSearch(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.hybrid_search(query, top_k=top_k, session_id=session_id)

    def Synchronize(self) -> dict[str, list[str]]:
        return self.synchronize()

    def RebuildIndex(self) -> dict[str, list[str]]:
        return self.rebuild_index()

    def ResetMemory(self) -> dict[str, object]:
        return self.reset_memory()

    def add_knowledge(
        self,
        *,
        title: str,
        summary: str,
        kind: str = MemoryKind.FACT.value,
        tags: list[str] | None = None,
        category: str = "general",
        details: list[str] | None = None,
        memory_id: str | None = None,
        subject: str = "",
        value: str = "",
        importance_score: float = 0.5,
    ) -> dict[str, object]:
        memory_id = memory_id or slugify(title)
        record = MemoryRecord(
            memory_id=memory_id,
            title=title,
            kind=MemoryKind(kind),
            summary=summary,
            subject=subject,
            value=value,
            category=category,
            tags=tags or [],
            details=details or [],
            importance_score=importance_score,
            updated_at=now_iso(),
        )
        path = self.store.upsert_record(record)
        sync_result = self.synchronizer.synchronize([path])
        return {"memory_id": record.memory_id, "path": str(path), "sync": sync_result}

    def update_knowledge(self, memory_id: str, summary: str, details: list[str] | None = None) -> dict[str, object]:
        existing = self.store.get_record(memory_id)
        if not existing:
            raise KeyError(f"Unknown memory_id: {memory_id}")
        existing.summary = summary
        if details:
            existing.details = sorted(set(existing.details).union(details))
        existing.updated_at = now_iso()
        path = self.store.upsert_record(existing)
        sync_result = self.synchronizer.synchronize([path])
        return {"memory_id": memory_id, "path": str(path), "sync": sync_result}

    def delete_knowledge(self, memory_id: str) -> dict[str, object]:
        path = self.store.delete_record(memory_id)
        fallback = Path(self.paths.knowledge_root / f"{memory_id}.md")
        sync_result = self.synchronizer.synchronize([path or fallback])
        return {"memory_id": memory_id, "deleted": bool(path), "sync": sync_result}

    def search(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.hybrid_search(query, top_k=top_k, session_id=session_id)

    def semantic_search(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.retriever.semantic_search(query, top_k or self.config.default_top_k, session_id=session_id)

    def graph_search(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.retriever.graph_search(query, top_k or self.config.default_top_k, session_id=session_id)

    def hybrid_search(self, query: str, top_k: int | None = None, session_id: str = "") -> list[SearchResult]:
        return self.retriever.hybrid_search(query, top_k or self.config.default_top_k, session_id=session_id)

    def synchronize(self) -> dict[str, list[str]]:
        return self.synchronizer.synchronize()

    def rebuild_index(self) -> dict[str, list[str]]:
        return self.synchronizer.rebuild()

    def reset_memory(self) -> dict[str, object]:
        deleted_records = self.store.clear_records()
        sync_result = self.synchronizer.synchronize(deleted_records) if deleted_records else {"updated": [], "deleted": []}
        cleared_pending = self._clear_pending_turns()
        self.close()
        self.paths.duckdb_path.unlink(missing_ok=True)
        self.paths.manifest_path.unlink(missing_ok=True)
        shutil.rmtree(self.paths.vector_root, ignore_errors=True)
        shutil.rmtree(self.paths.graph_root, ignore_errors=True)
        self._initialize_runtime(synchronize=False)
        self.analytics.log_event(
            MemoryEvent(
                "MemoryReset",
                {
                    "deleted_memory_files": len(deleted_records),
                    "deleted_pending_turns": len(cleared_pending),
                },
            )
        )
        return {
            "deleted_memory_files": [str(path) for path in deleted_records],
            "deleted_pending_turns": [str(path) for path in cleared_pending],
            "sync": sync_result,
            "reset": True,
        }

    def close(self) -> None:
        self.analytics.close()
        graph_close = getattr(self.graph_store, "close", None)
        if callable(graph_close):
            graph_close()

    def memory_prepare_turn(
        self,
        *,
        user_message: str,
        session_id: str,
        project_path: str = "",
        repo: str = "",
        branch: str = "",
        cwd: str = "",
        top_k: int | None = None,
    ) -> PreparedTurn:
        results, memory_mode = self._prepare_turn_memories(user_message, session_id, top_k=top_k)
        token = uuid.uuid4().hex
        related_entities = self.entity_extractor.extract(user_message)
        open_questions = [result.memory.summary for result in results if result.memory.kind == MemoryKind.OPEN_QUESTION]
        context_block = self.retriever.build_context_block(results, open_questions, memory_mode=memory_mode)
        pending_path = self.paths.pending_turns_root / f"{token}.json"
        pending_path.write_text(
            json.dumps(
                {
                    "turn_token": token,
                    "session_id": session_id,
                    "user_message": user_message,
                    "project_path": project_path,
                    "repo": repo,
                    "branch": branch,
                    "cwd": cwd,
                    "memory_mode": memory_mode,
                    "configured_memory_ids": list(self.config.locked_memory_ids),
                    "created_at": now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return PreparedTurn(
            turn_token=token,
            user_message=user_message,
            session_id=session_id,
            project_path=project_path,
            memory_mode=memory_mode,
            configured_memory_ids=list(self.config.locked_memory_ids),
            retrieved_memories=results,
            related_entities=related_entities,
            open_questions=open_questions,
            context_block=context_block,
        )

    def memory_finalize_turn(
        self,
        *,
        turn_token: str,
        assistant_message: str,
        tool_results: object | None = None,
        final_status: str = "completed",
    ) -> dict[str, object]:
        pending = self._load_pending_turn(turn_token)
        resolved_tool_results = tool_results or {}
        self.analytics.save_turn(
            turn_token=turn_token,
            session_id=pending["session_id"],
            user_message=pending["user_message"],
            assistant_message=assistant_message,
            tool_results=resolved_tool_results,
            final_status=final_status,
            project_path=pending.get("project_path", ""),
            repo=pending.get("repo", ""),
            branch=pending.get("branch", ""),
            cwd=pending.get("cwd", ""),
        )
        journal_path = self.journal.append_turn(
            created_at=pending.get("created_at", now_iso()),
            turn_token=turn_token,
            session_id=pending["session_id"],
            user_message=pending["user_message"],
            assistant_message=assistant_message,
            tool_results=resolved_tool_results,
            final_status=final_status,
            project_path=pending.get("project_path", ""),
            repo=pending.get("repo", ""),
            branch=pending.get("branch", ""),
            cwd=pending.get("cwd", ""),
        )
        self.analytics.log_event(
            MemoryEvent(
                "ConversationStored",
                {
                    "turn_token": turn_token,
                    "session_id": pending["session_id"],
                    "project_path": pending.get("project_path", ""),
                },
            )
        )
        if self.config.locked_memory_ids:
            self.analytics.log_event(
                MemoryEvent(
                    "MemoryPromotionSkipped",
                    {
                        "turn_token": turn_token,
                        "session_id": pending["session_id"],
                        "memory_mode": "locked",
                        "configured_memory_ids": list(self.config.locked_memory_ids),
                    },
                )
            )
            self._delete_pending_turn(turn_token)
            return {
                "turn_token": turn_token,
                "candidate_count": 0,
                "memory_changes": [],
                "conflicts": [],
                "journal_path": str(journal_path),
                "sync": {"updated": [], "deleted": []},
                "memory_mode": "locked",
                "skipped_memory_promotion": True,
                "configured_memory_ids": list(self.config.locked_memory_ids),
            }

        candidates = self.extractor.extract(pending["user_message"], assistant_message)
        candidates = self.ai_assistant.refine_candidates(
            user_message=pending["user_message"],
            assistant_message=assistant_message,
            candidates=candidates,
        )

        changed_paths: list[Path] = []
        actions: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []
        turn_index = self._next_turn_index(pending["session_id"])

        for candidate in candidates:
            outcome, record = self._resolve_candidate(candidate, pending["session_id"], turn_index)
            if record is None or outcome == "ignore":
                actions.append({"memory_id": candidate.memory_id, "action": "ignore"})
                continue
            path = self.store.upsert_record(record)
            changed_paths.append(path)
            action_item = {"memory_id": record.memory_id, "action": outcome, "path": str(path)}
            actions.append(action_item)
            if outcome == "conflict":
                conflicts.append(action_item)
                self.analytics.log_event(
                    MemoryEvent(
                        "KnowledgeConflict",
                        {"memory_id": record.memory_id, "candidate_summary": candidate.summary, "path": str(path)},
                    )
                )
            else:
                event_name = "KnowledgeAdded" if outcome == "add" else "KnowledgeUpdated"
                self.analytics.log_event(MemoryEvent(event_name, {"memory_id": record.memory_id, "path": str(path)}))

        sync_result = self.synchronizer.synchronize(changed_paths) if changed_paths else {"updated": [], "deleted": []}
        self._delete_pending_turn(turn_token)
        return {
            "turn_token": turn_token,
            "candidate_count": len(candidates),
            "memory_changes": actions,
            "conflicts": conflicts,
            "journal_path": str(journal_path),
            "sync": sync_result,
            "memory_mode": pending.get("memory_mode", "dynamic"),
            "skipped_memory_promotion": False,
            "configured_memory_ids": list(pending.get("configured_memory_ids", [])),
        }

    def _prepare_turn_memories(
        self,
        user_message: str,
        session_id: str,
        *,
        top_k: int | None = None,
    ) -> tuple[list[SearchResult], str]:
        if self.config.locked_memory_ids:
            results = self._locked_memory_results()
            self.analytics.log_event(
                MemoryEvent(
                    "LockedMemoryUsed",
                    {
                        "session_id": session_id,
                        "memory_ids": list(self.config.locked_memory_ids),
                    },
                )
            )
            return results, "locked"
        return self.hybrid_search(user_message, top_k=top_k, session_id=session_id), "dynamic"

    def _locked_memory_results(self) -> list[SearchResult]:
        results: list[SearchResult] = []
        missing_ids: list[str] = []
        total = len(self.config.locked_memory_ids)
        for index, memory_id in enumerate(self.config.locked_memory_ids):
            record = self.store.get_record(memory_id)
            if record is None:
                missing_ids.append(memory_id)
                continue
            results.append(SearchResult(record, float(total - index), "locked"))
        if missing_ids:
            missing = ", ".join(missing_ids)
            raise KeyError(f"Unknown locked memory_id(s): {missing}")
        return results

    def _resolve_candidate(
        self,
        candidate: MemoryCandidate,
        session_id: str,
        turn_index: int,
    ) -> tuple[str, MemoryRecord | None]:
        source = MemorySource(session_id=session_id, turn_index=turn_index)
        existing = self.store.get_record(candidate.memory_id)
        if existing is None:
            existing = self._find_semantic_match(candidate)
        if existing is None:
            record = MemoryRecord(
                memory_id=candidate.memory_id,
                title=candidate.title,
                kind=candidate.kind,
                summary=candidate.summary,
                subject=candidate.subject,
                value=candidate.value,
                category=candidate.category,
                tags=candidate.tags,
                sources=[source],
                details=candidate.details,
                importance_score=candidate.importance_score,
                updated_at=now_iso(),
            )
            return "add", record

        if self._is_conflict(existing, candidate):
            note = (
                f"Conflict noted on {now_iso()}: candidate value '{candidate.value or candidate.summary}' "
                f"did not match current value '{existing.value or existing.summary}'."
            )
            if note not in existing.details:
                existing.details.append(note)
            existing.sources.append(source)
            existing.updated_at = now_iso()
            return "conflict", existing

        changed = False
        if existing.summary != candidate.summary:
            existing.details.append(f"Previous summary: {existing.summary}")
            existing.summary = candidate.summary
            changed = True
        if candidate.subject and existing.subject != candidate.subject:
            existing.subject = candidate.subject
            changed = True
        if candidate.value and existing.value != candidate.value:
            existing.value = candidate.value
            changed = True
        combined_details = sorted(set(existing.details).union(candidate.details))
        if combined_details != existing.details:
            existing.details = combined_details
            changed = True
        combined_tags = sorted(set(existing.tags).union(candidate.tags))
        if combined_tags != existing.tags:
            existing.tags = combined_tags
            changed = True
        if candidate.importance_score > existing.importance_score:
            existing.importance_score = candidate.importance_score
            changed = True
        existing.sources.append(source)
        existing.updated_at = now_iso()
        return ("update" if changed else "ignore"), existing

    def _find_semantic_match(self, candidate: MemoryCandidate) -> MemoryRecord | None:
        best_record: MemoryRecord | None = None
        best_score = 0.0
        candidate_embedding = self.embedder.embed(candidate.summary)
        for record in self.store.list_records():
            if candidate.subject and record.subject and candidate.subject != record.subject:
                continue
            score = cosine_similarity(candidate_embedding, self.embedder.embed(record.summary))
            tag_score = jaccard_overlap(candidate.tags, record.tags)
            combined = (score * 0.8) + (tag_score * 0.2)
            if combined > best_score:
                best_score = combined
                best_record = record
        return best_record if best_score >= 0.78 else None

    def _is_conflict(self, existing: MemoryRecord, candidate: MemoryCandidate) -> bool:
        if existing.subject and candidate.subject and existing.subject != candidate.subject:
            return False
        if existing.value and candidate.value and existing.value != candidate.value:
            return True
        if existing.kind != candidate.kind:
            return False
        if existing.title == candidate.title and existing.summary != candidate.summary and candidate.value:
            return True
        return False

    def _next_turn_index(self, session_id: str) -> int:
        return self.analytics.count_turns(session_id) + 1

    def _load_pending_turn(self, turn_token: str) -> dict[str, str]:
        path = self.paths.pending_turns_root / f"{turn_token}.json"
        if not path.exists():
            raise KeyError(f"Unknown turn_token: {turn_token}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _delete_pending_turn(self, turn_token: str) -> None:
        path = self.paths.pending_turns_root / f"{turn_token}.json"
        path.unlink(missing_ok=True)

    def _clear_pending_turns(self) -> list[Path]:
        deleted_paths: list[Path] = []
        for path in sorted(self.paths.pending_turns_root.glob("*.json")):
            path.unlink(missing_ok=True)
            deleted_paths.append(path)
        self.paths.pending_turns_root.mkdir(parents=True, exist_ok=True)
        return deleted_paths

    def _initialize_runtime(self, *, synchronize: bool) -> None:
        self.analytics = DuckDBAnalyticsStore(self.paths.duckdb_path)
        self.vector_store = self._build_vector_store()
        self.graph_store = self._build_graph_store()
        self.synchronizer = Synchronizer(
            store=self.store,
            embedder=self.embedder,
            vector_store=self.vector_store,
            graph_store=self.graph_store,
            analytics=self.analytics,
            manifest_path=self.paths.manifest_path,
            entity_extractor=self.entity_extractor,
        )
        self.retriever = HybridRetriever(
            store=self.store,
            embedder=self.embedder,
            vector_store=self.vector_store,
            graph_store=self.graph_store,
            entity_extractor=self.entity_extractor,
            analytics=self.analytics,
        )
        if synchronize:
            self.synchronizer.synchronize(force_graph=self.graph_store.needs_bootstrap())

    def _build_vector_store(self) -> InMemoryVectorStore | LanceDBVectorStore:
        if self.config.vector_backend != "lancedb":
            raise ValueError(f"Unsupported vector backend: {self.config.vector_backend}")
        return LanceDBVectorStore(self.paths.vector_root)

    def _build_graph_store(self) -> InMemoryGraphStore | LadybugGraphStore:
        if self.config.graph_backend not in {"ladybug", "kuzu"}:
            raise ValueError(f"Unsupported graph backend: {self.config.graph_backend}")
        return LadybugGraphStore(self.paths.graph_root)

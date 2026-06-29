from __future__ import annotations

import json
from pathlib import Path

from .analytics import DuckDBAnalyticsStore
from .chunking import chunk_markdown
from .embeddings import HashingEmbeddingProvider
from .entity_extraction import InMemoryGraphStore, KuzuGraphStore, SimpleEntityExtractor
from .events import MemoryEvent
from .markdown_store import MarkdownMemoryStore
from .vector_store import InMemoryVectorStore, LanceDBVectorStore
from .utils import stable_hash


class Synchronizer:
    def __init__(
        self,
        *,
        store: MarkdownMemoryStore,
        embedder: HashingEmbeddingProvider,
        vector_store: InMemoryVectorStore | LanceDBVectorStore,
        graph_store: InMemoryGraphStore | KuzuGraphStore,
        analytics: DuckDBAnalyticsStore,
        manifest_path: Path,
        entity_extractor: SimpleEntityExtractor,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.analytics = analytics
        self.manifest_path = manifest_path
        self.entity_extractor = entity_extractor
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def synchronize(self, changed_paths: list[Path] | None = None) -> dict[str, list[str]]:
        manifest = self._load_manifest()
        if changed_paths is None:
            relevant = {path.resolve() for path in self.store.knowledge_root.rglob("*.md")}
            relevant.update(Path(path) for path in manifest.keys())
        else:
            relevant = {path.resolve() for path in changed_paths}

        updated: list[str] = []
        deleted: list[str] = []

        for path in sorted(relevant):
            path_key = str(path)
            if not path.exists():
                if path_key in manifest:
                    self.vector_store.delete_document(path_key)
                    self.graph_store.delete_document(path_key)
                    deleted.append(path_key)
                    self.analytics.log_event(MemoryEvent("KnowledgeDeleted", {"path": path_key}))
                    manifest.pop(path_key, None)
                continue

            text = path.read_text(encoding="utf-8")
            document_hash = stable_hash(text)
            if manifest.get(path_key, {}).get("document_hash") == document_hash:
                continue

            record = self.store.load_path(path)
            chunks = chunk_markdown(path, record.memory_id, text)
            existing_chunks: dict[str, str] = manifest.get(path_key, {}).get("chunks", {})
            new_chunks = {chunk.chunk_id: chunk for chunk in chunks}
            removed_chunk_ids = [chunk_id for chunk_id in existing_chunks if chunk_id not in new_chunks]
            changed_chunks = [chunk for chunk in chunks if existing_chunks.get(chunk.chunk_id) != chunk.chunk_hash]
            embeddings = [self.embedder.embed(chunk.text) for chunk in changed_chunks]

            if removed_chunk_ids:
                self.vector_store.delete_chunks(removed_chunk_ids)
            if changed_chunks:
                self.vector_store.upsert_chunks(changed_chunks, embeddings)

            entities = self.entity_extractor.extract(f"{record.title}\n{record.summary}\n{text}", path_key)
            self.graph_store.delete_document(path_key)
            self.graph_store.upsert_memory(record.memory_id, path_key, entities)

            event_name = "KnowledgeAdded" if path_key not in manifest else "KnowledgeUpdated"
            self.analytics.log_event(MemoryEvent(event_name, {"path": path_key, "memory_id": record.memory_id}))
            self.analytics.log_event(
                MemoryEvent(
                    "EmbeddingCreated",
                    {
                        "path": path_key,
                        "chunks_updated": len(changed_chunks),
                        "chunks_deleted": len(removed_chunk_ids),
                        "chunks_total": len(chunks),
                    },
                )
            )
            self.analytics.log_event(MemoryEvent("GraphUpdated", {"path": path_key, "entities": entities}))

            manifest[path_key] = {
                "memory_id": record.memory_id,
                "document_hash": document_hash,
                "chunks": {chunk.chunk_id: chunk.chunk_hash for chunk in chunks},
            }
            updated.append(path_key)

        self._save_manifest(manifest)
        return {"updated": updated, "deleted": deleted}

    def rebuild(self) -> dict[str, list[str]]:
        manifest = self._load_manifest()
        for path in list(manifest):
            self.vector_store.delete_document(path)
            self.graph_store.delete_document(path)
        self._save_manifest({})
        return self.synchronize()

    def _load_manifest(self) -> dict[str, dict[str, object]]:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _save_manifest(self, manifest: dict[str, dict[str, object]]) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

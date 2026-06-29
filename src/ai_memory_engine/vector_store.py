from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DocumentChunk
from .utils import cosine_similarity


@dataclass(slots=True)
class VectorHit:
    memory_id: str
    path: str
    text: str
    score: float
    metadata: dict[str, Any]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def upsert_chunks(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        for chunk, embedding in zip(chunks, embeddings):
            self._rows[chunk.chunk_id] = {
                "memory_id": chunk.memory_id,
                "path": chunk.path,
                "text": chunk.text,
                "embedding": embedding,
                "metadata": chunk.metadata,
            }

    def delete_document(self, path: str) -> None:
        self._rows = {key: value for key, value in self._rows.items() if value["path"] != path}

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self._rows.pop(chunk_id, None)

    def search(self, embedding: list[float], top_k: int) -> list[VectorHit]:
        hits = [
            VectorHit(
                memory_id=row["memory_id"],
                path=row["path"],
                text=row["text"],
                score=cosine_similarity(embedding, row["embedding"]),
                metadata=row["metadata"],
            )
            for row in self._rows.values()
        ]
        hits.sort(key=lambda item: item.score, reverse=True)
        return [hit for hit in hits[:top_k] if hit.score > 0]


class LanceDBVectorStore:
    def __init__(self, root: Path) -> None:
        try:
            import lancedb
        except ImportError as exc:
            raise RuntimeError("lancedb is required for the LanceDB adapter") from exc
        self._lancedb = lancedb
        root.mkdir(parents=True, exist_ok=True)
        self._db = self._lancedb.connect(str(root))
        try:
            self._table = self._db.open_table("memory_chunks")
        except Exception:
            self._table = None

    def upsert_chunks(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        rows = []
        for chunk, embedding in zip(chunks, embeddings):
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "memory_id": chunk.memory_id,
                    "path": chunk.path,
                    "text": chunk.text,
                    "vector": embedding,
                }
            )
        if rows:
            if self._table is None:
                self._table = self._db.create_table("memory_chunks", rows, mode="overwrite")
                return
            self.delete_chunks([row["chunk_id"] for row in rows])
            self._table.add(rows)

    def delete_document(self, path: str) -> None:
        if self._table is None:
            return
        safe_path = path.replace("'", "''")
        self._table.delete(f"path = '{safe_path}'")

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids or self._table is None:
            return
        safe_ids = [chunk_id.replace("'", "''") for chunk_id in chunk_ids]
        self._table.delete(" OR ".join(f"chunk_id = '{chunk_id}'" for chunk_id in safe_ids))

    def search(self, embedding: list[float], top_k: int) -> list[VectorHit]:
        if self._table is None:
            return []
        rows = self._table.search(embedding, vector_column_name="vector").limit(top_k).to_list()
        return [
            VectorHit(
                memory_id=row["memory_id"],
                path=row["path"],
                text=row["text"],
                score=1.0 / (1.0 + float(row.get("_distance", 0.0))),
                metadata={"path": row["path"], "memory_id": row["memory_id"]},
            )
            for row in rows
        ]

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .utils import tokenize


KEYWORDS = {
    "python",
    "markdown",
    "mcp",
    "lancedb",
    "kuzu",
    "duckdb",
    "copilot",
    "claude",
    "github",
    "aws",
    "oracle",
}


class SimpleEntityExtractor:
    def extract(self, text: str, path: str = "") -> list[str]:
        entities = {token for token in tokenize(text) if token in KEYWORDS or len(token) >= 6}
        if path:
            entities.add(Path(path).stem.lower())
        return sorted(entities)


@dataclass(slots=True)
class GraphHit:
    memory_id: str
    score: float
    entities: list[str]


class InMemoryGraphStore:
    def __init__(self) -> None:
        self._memory_entities: dict[str, set[str]] = {}
        self._path_lookup: dict[str, str] = {}

    def upsert_memory(self, memory_id: str, path: str, entities: list[str]) -> None:
        self._memory_entities[memory_id] = set(entities)
        self._path_lookup[memory_id] = path

    def delete_document(self, path: str) -> None:
        for memory_id, memory_path in list(self._path_lookup.items()):
            if memory_path == path:
                self._memory_entities.pop(memory_id, None)
                self._path_lookup.pop(memory_id, None)

    def search(self, query_entities: list[str], top_k: int) -> list[GraphHit]:
        query = set(query_entities)
        hits: list[GraphHit] = []
        for memory_id, entities in self._memory_entities.items():
            overlap = query.intersection(entities)
            if overlap:
                hits.append(GraphHit(memory_id=memory_id, score=float(len(overlap)), entities=sorted(overlap)))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]


class KuzuGraphStore:
    def __init__(self, root: Path) -> None:
        try:
            import kuzu
        except ImportError as exc:
            raise RuntimeError("kuzu is required for the Kuzu adapter") from exc
        root.mkdir(parents=True, exist_ok=True)
        self._kuzu = kuzu
        self._database_path = root / "memory.kuzu"
        with self._connect() as conn:
            conn.execute("CREATE NODE TABLE IF NOT EXISTS Memory(id STRING, path STRING, PRIMARY KEY(id));")
            conn.execute("CREATE NODE TABLE IF NOT EXISTS Entity(name STRING, PRIMARY KEY(name));")
            conn.execute("CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Memory TO Entity);")

    def upsert_memory(self, memory_id: str, path: str, entities: list[str]) -> None:
        self.delete_document(path)
        escaped_path = self._escape(path)
        escaped_memory_id = self._escape(memory_id)
        with self._connect() as conn:
            conn.execute(f"MERGE (m:Memory {{id: '{escaped_memory_id}', path: '{escaped_path}'}});")
            for entity in entities:
                escaped = self._escape(entity)
                conn.execute(f"MERGE (e:Entity {{name: '{escaped}'}});")
                conn.execute(
                    f"MATCH (m:Memory {{id: '{escaped_memory_id}'}}), (e:Entity {{name: '{escaped}'}}) MERGE (m)-[:MENTIONS]->(e);"
                )

    def delete_document(self, path: str) -> None:
        escaped = self._escape(path)
        with self._connect() as conn:
            conn.execute(f"MATCH (m:Memory {{path: '{escaped}'}})-[r:MENTIONS]->() DELETE r;")
            conn.execute(f"MATCH (m:Memory {{path: '{escaped}'}}) DELETE m;")

    def search(self, query_entities: list[str], top_k: int) -> list[GraphHit]:
        hits: dict[str, GraphHit] = {}
        with self._connect() as conn:
            for entity in query_entities:
                escaped = self._escape(entity)
                result = conn.execute(
                    f"MATCH (m:Memory)-[:MENTIONS]->(e:Entity {{name: '{escaped}'}}) RETURN m.id, e.name;"
                )
                rows = result.get_all()
                for memory_id, entity_name in rows:
                    if memory_id not in hits:
                        hits[memory_id] = GraphHit(memory_id=memory_id, score=0.0, entities=[])
                    hits[memory_id].score += 1.0
                    hits[memory_id].entities.append(str(entity_name))
        ordered = sorted(hits.values(), key=lambda item: item.score, reverse=True)
        return ordered[:top_k]

    def close(self) -> None:
        return None

    def _escape(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "''")

    @contextmanager
    def _connect(self):
        db = self._kuzu.Database(str(self._database_path))
        conn = self._kuzu.Connection(db)
        try:
            yield conn
        finally:
            conn.close()
            db.close()

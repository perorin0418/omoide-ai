from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import duckdb

from .events import MemoryEvent


class DuckDBAnalyticsStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as conn:
            self._ensure_schema(conn)

    @contextmanager
    def _connect(self):
        conn = duckdb.connect(str(self.path))
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                turn_token TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                assistant_message TEXT,
                tool_results TEXT,
                final_status TEXT,
                project_path TEXT,
                repo TEXT,
                branch TEXT,
                cwd TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute("ALTER TABLE conversation_turns ADD COLUMN IF NOT EXISTS project_path TEXT;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                name TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_logs (
                session_id TEXT,
                query TEXT NOT NULL,
                result_count INTEGER NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_usage_stats (
                memory_id TEXT PRIMARY KEY,
                retrieval_count BIGINT NOT NULL DEFAULT 0,
                last_query TEXT,
                last_session_id TEXT,
                last_score DOUBLE,
                last_retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def save_turn(
        self,
        *,
        turn_token: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        tool_results: object,
        final_status: str,
        project_path: str,
        repo: str,
        branch: str,
        cwd: str,
    ) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_turns
                (turn_token, session_id, user_message, assistant_message, tool_results, final_status, project_path, repo, branch, cwd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    turn_token,
                    session_id,
                    user_message,
                    assistant_message,
                    json.dumps(tool_results, ensure_ascii=False),
                    final_status,
                    project_path,
                    repo,
                    branch,
                    cwd,
                ],
            )

    def log_event(self, event: MemoryEvent) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT INTO memory_events (name, payload) VALUES (?, ?)",
                [event.name, json.dumps(event.payload, ensure_ascii=False)],
            )

    def log_search(self, session_id: str, query: str, result_count: int, details: object) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT INTO search_logs (session_id, query, result_count, details) VALUES (?, ?, ?, ?)",
                [session_id, query, result_count, json.dumps(details, ensure_ascii=False)],
            )

    def record_memory_usage(self, memory_id: str, session_id: str, query: str, score: float) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO memory_usage_stats (memory_id, retrieval_count, last_query, last_session_id, last_score)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    retrieval_count = memory_usage_stats.retrieval_count + 1,
                    last_query = excluded.last_query,
                    last_session_id = excluded.last_session_id,
                    last_score = excluded.last_score,
                    last_retrieved_at = now()
                """,
                [memory_id, query, session_id, score],
            )

    def count_turns(self, session_id: str) -> int:
        with self._connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT COUNT(*) FROM conversation_turns WHERE session_id = ?",
                [session_id],
            ).fetchone()
        return int(rows[0]) if rows else 0

    def close(self) -> None:
        return None

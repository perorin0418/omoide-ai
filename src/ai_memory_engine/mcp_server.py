from __future__ import annotations

import json
import os
import sys
from functools import cached_property
from io import BufferedReader
from pathlib import Path
from typing import Any

from .config import EngineConfig
from .engine import MemoryEngine


_stdio_message_mode = "framed"
_project_root_hint: Path | None = None


def _log_path() -> Path | None:
    raw = os.environ.get("AI_MEMORY_ENGINE_MCP_LOG")
    if raw:
        return Path(raw)
    if _project_root_hint is None:
        return None
    return _project_root_hint / ".ai-memory-engine" / "mcp-server.log"


def log_event(event: str, **fields: Any) -> None:
    path = _log_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": event, **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class MemoryMCPServer:
    def __init__(self, project_root: Path | MemoryEngine) -> None:
        if isinstance(project_root, MemoryEngine):
            self._engine_override = project_root
            self.project_root = project_root.paths.project_root
        else:
            self._engine_override = None
            self.project_root = project_root

    @cached_property
    def engine(self) -> MemoryEngine:
        if self._engine_override is not None:
            return self._engine_override
        return MemoryEngine(EngineConfig.for_project(self.project_root))

    def handle_message(self, message: dict[str, object]) -> dict[str, object] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params", {})
        log_event("message.received", method=method, has_id=request_id is not None)

        if method == "initialize":
            protocol_version = str(params.get("protocolVersion", "2024-11-05"))
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "ai-memory-engine", "version": "0.1.0"},
                },
            }
            log_event("message.responded", method=method)
            return response
        if method in {"notifications/initialized", "initialized", "notifications/cancelled"}:
            log_event("message.ignored", method=method)
            return None
        if method == "ping":
            response = {"jsonrpc": "2.0", "id": request_id, "result": {}}
            log_event("message.responded", method=method)
            return response
        if method == "tools/list":
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self._tools()}}
            log_event("message.responded", method=method, tool_count=len(response["result"]["tools"]))
            return response
        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = self._call_tool(str(name), dict(arguments))
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
                        "isError": False,
                    },
                }
                log_event("message.responded", method=method, tool=name, is_error=False)
                return response
            except Exception as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                }
                log_event("message.responded", method=method, tool=name, is_error=True, error=str(exc))
                return response
        if request_id is not None:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Unsupported method: {method}"},
            }
            log_event("message.responded", method=method, unsupported=True)
            return response
        return None

    def _tools(self) -> list[dict[str, object]]:
        return [
            {
                "name": "memory_prepare_turn",
                "description": "Retrieve relevant memory before the assistant responds.",
                "inputSchema": {
                    "type": "object",
                    "required": ["user_message", "session_id"],
                    "properties": {
                        "user_message": {"type": "string"},
                        "session_id": {"type": "string"},
                        "project_path": {"type": "string"},
                        "repo": {"type": "string"},
                        "branch": {"type": "string"},
                        "cwd": {"type": "string"},
                        "top_k": {"type": "integer"},
                    },
                },
            },
            {
                "name": "memory_finalize_turn",
                "description": "Persist the turn and promote reusable memory into Markdown.",
                "inputSchema": {
                    "type": "object",
                    "required": ["turn_token", "assistant_message"],
                    "properties": {
                        "turn_token": {"type": "string"},
                        "assistant_message": {"type": "string"},
                        "tool_results": {},
                        "final_status": {"type": "string"},
                    },
                },
            },
            {
                "name": "memory_upsert_note",
                "description": "Persist a structured note directly into the Markdown memory store.",
                "inputSchema": {
                    "type": "object",
                    "required": ["title", "summary"],
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "kind": {"type": "string"},
                        "category": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "details": {"type": "array", "items": {"type": "string"}},
                        "memory_id": {"type": "string"},
                        "subject": {"type": "string"},
                        "value": {"type": "string"},
                        "importance_score": {"type": "number"},
                    },
                },
            },
            {
                "name": "memory_search",
                "description": "Run hybrid search across the stored memory base.",
                "inputSchema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer"},
                        "session_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "memory_sync",
                "description": "Synchronize Markdown changes into derived stores.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "memory_rebuild",
                "description": "Rebuild all derived stores from Markdown.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def _call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "memory_prepare_turn":
            prepared = self.engine.memory_prepare_turn(
                user_message=str(arguments["user_message"]),
                session_id=str(arguments["session_id"]),
                project_path=str(arguments.get("project_path", "")),
                repo=str(arguments.get("repo", "")),
                branch=str(arguments.get("branch", "")),
                cwd=str(arguments.get("cwd", "")),
                top_k=int(arguments.get("top_k", self.engine.config.default_top_k)),
            )
            return {
                "turn_token": prepared.turn_token,
                "retrieved_memories": [
                    {
                        "memory_id": item.memory.memory_id,
                        "title": item.memory.title,
                        "summary": item.memory.summary,
                        "score": item.score,
                        "reason": item.reason,
                        "tags": item.memory.tags,
                    }
                    for item in prepared.retrieved_memories
                ],
                "project_path": prepared.project_path,
                "related_entities": prepared.related_entities,
                "open_questions": prepared.open_questions,
                "context_block": prepared.context_block,
            }
        if name == "memory_finalize_turn":
            return self.engine.memory_finalize_turn(
                turn_token=str(arguments["turn_token"]),
                assistant_message=str(arguments["assistant_message"]),
                tool_results=arguments.get("tool_results", {}),
                final_status=str(arguments.get("final_status", "completed")),
            )
        if name == "memory_upsert_note":
            return self.engine.add_knowledge(
                title=str(arguments["title"]),
                summary=str(arguments["summary"]),
                kind=str(arguments.get("kind", "fact")),
                category=str(arguments.get("category", "general")),
                tags=list(arguments.get("tags", [])),
                details=list(arguments.get("details", [])),
                memory_id=str(arguments.get("memory_id", "")) or None,
                subject=str(arguments.get("subject", "")),
                value=str(arguments.get("value", "")),
                importance_score=float(arguments.get("importance_score", 0.5)),
            )
        if name == "memory_search":
            results = self.engine.search(
                str(arguments["query"]),
                top_k=int(arguments.get("top_k", self.engine.config.default_top_k)),
                session_id=str(arguments.get("session_id", "")),
            )
            return {
                "results": [
                    {
                        "memory_id": item.memory.memory_id,
                        "title": item.memory.title,
                        "summary": item.memory.summary,
                        "score": item.score,
                        "reason": item.reason,
                    }
                    for item in results
                ]
            }
        if name == "memory_sync":
            return self.engine.synchronize()
        if name == "memory_rebuild":
            return self.engine.rebuild_index()
        raise KeyError(f"Unknown tool: {name}")


def _read_framed_message(first_line: bytes, stream: BufferedReader) -> dict[str, object] | None:
    headers: dict[str, str] = {}
    line = first_line
    while True:
        if not line:
            log_event("stdio.eof_before_message")
            return None
        log_event("stdio.header_line", line=line.decode("utf-8", "replace").rstrip("\r\n"))
        if line in {b"\r\n", b"\n"}:
            break
        key, value = line.decode("utf-8").split(":", 1)
        headers[key.strip().lower()] = value.strip()
        line = stream.readline()
    log_event("stdio.headers_complete", headers=headers)
    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        log_event("stdio.invalid_content_length", content_length=content_length)
        return None
    body = stream.read(content_length)
    log_event("stdio.body_read", content_length=content_length, body_preview=body[:200].decode("utf-8", "replace"))
    return json.loads(body.decode("utf-8"))


def read_message() -> dict[str, object] | None:
    global _stdio_message_mode
    first_line = sys.stdin.buffer.readline()
    if not first_line:
        log_event("stdio.eof_before_message")
        return None
    stripped = first_line.strip()
    if stripped.startswith(b"{"):
        _stdio_message_mode = "line"
        text = stripped.decode("utf-8")
        log_event("stdio.line_message", body_preview=text[:200])
        return json.loads(text)
    _stdio_message_mode = "framed"
    return _read_framed_message(first_line, sys.stdin.buffer)


def write_message(message: dict[str, object]) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if _stdio_message_mode == "line":
        sys.stdout.buffer.write(payload + b"\n")
        log_event("stdio.write_line_message", body_preview=payload[:200].decode("utf-8", "replace"))
    else:
        sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(payload)
        log_event("stdio.write_framed_message", content_length=len(payload))
    sys.stdout.buffer.flush()


def _is_project_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").exists()
        and (path / ".mcp.json").exists()
        and (path / "src" / "ai_memory_engine").exists()
    )


def _find_project_root_from(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if _is_project_root(candidate):
            return candidate
    return None


def resolve_project_root() -> Path:
    explicit = os.environ.get("AI_MEMORY_ENGINE_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
    if explicit:
        return Path(explicit).resolve()

    search_roots = [
        Path(os.getcwd()),
        Path(__file__),
        Path(sys.argv[0]),
        Path(sys.executable),
    ]
    for search_root in search_roots:
        project_root = _find_project_root_from(search_root)
        if project_root is not None:
            return project_root
    return Path(os.getcwd()).resolve()


def main() -> None:
    global _project_root_hint
    _project_root_hint = resolve_project_root()
    log_event("server.starting", cwd=os.getcwd(), project_root=str(_project_root_hint))
    server = MemoryMCPServer(_project_root_hint)
    try:
        while True:
            message = read_message()
            if message is None:
                log_event("server.stopping", reason="eof")
                return
            response = server.handle_message(message)
            if response is not None:
                write_message(response)
    except Exception as exc:
        log_event("server.crashed", error=str(exc))
        raise


if __name__ == "__main__":
    main()

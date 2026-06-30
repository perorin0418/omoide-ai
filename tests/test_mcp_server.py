from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_memory_engine.config import EngineConfig
from ai_memory_engine.engine import MemoryEngine
from ai_memory_engine.mcp_server import MemoryMCPServer, resolve_project_root


class MemoryMCPServerTests(unittest.TestCase):
    def test_engine_config_reads_locked_memory_ids_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            with patch.dict("os.environ", {"AI_MEMORY_ENGINE_LOCKED_MEMORY_IDS": "memory-a, memory-b\nmemory-c"}, clear=True):
                config = EngineConfig.for_project(tempdir)
            self.assertEqual(config.locked_memory_ids, ("memory-a", "memory-b", "memory-c"))

    def test_tools_list_contains_turn_hooks_and_search_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = MemoryMCPServer(MemoryEngine(EngineConfig.for_project(tempdir)))
            response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertIsNotNone(response)
            tools = response["result"]["tools"]
            names = {tool["name"] for tool in tools}
            self.assertIn("memory_prepare_turn", names)
            self.assertIn("memory_finalize_turn", names)
            self.assertIn("memory_search", names)

            prepare_tool = next(tool for tool in tools if tool["name"] == "memory_prepare_turn")
            self.assertIn("project_path", prepare_tool["inputSchema"]["properties"])

    def test_prepare_turn_tool_returns_context_block(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            engine = MemoryEngine(EngineConfig.for_project(tempdir))
            engine.add_knowledge(
                title="Implementation Runtime",
                summary="The implementation runtime is python.",
                kind="decision",
                category="architecture",
                tags=["python", "runtime"],
                memory_id="implementation-runtime",
                subject="implementation_runtime",
                value="python",
            )
            server = MemoryMCPServer(engine)
            response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_prepare_turn",
                        "arguments": {
                            "user_message": "何の言語で進める方針だったっけ？",
                            "session_id": "session-1",
                            "project_path": tempdir,
                        },
                    },
                }
            )
            self.assertIsNotNone(response)
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertIn("context_block", payload)
            self.assertIn("Implementation Runtime", payload["context_block"])
            self.assertEqual(payload["memory_mode"], "dynamic")

    def test_prepare_turn_tool_returns_locked_memory_mode_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            engine = MemoryEngine(EngineConfig.for_project(tempdir))
            engine.add_knowledge(
                title="Implementation Runtime",
                summary="The implementation runtime is python.",
                kind="decision",
                category="architecture",
                tags=["python", "runtime"],
                memory_id="implementation-runtime",
                subject="implementation_runtime",
                value="python",
            )
            engine.config.locked_memory_ids = ("implementation-runtime",)
            server = MemoryMCPServer(engine)
            response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_prepare_turn",
                        "arguments": {
                            "user_message": "この質問に固定記憶だけで答えて",
                            "session_id": "session-locked",
                            "project_path": tempdir,
                        },
                    },
                }
            )
            self.assertIsNotNone(response)
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(payload["memory_mode"], "locked")
            self.assertEqual(payload["configured_memory_ids"], ["implementation-runtime"])
            self.assertEqual(payload["retrieved_memories"][0]["memory_id"], "implementation-runtime")

    def test_prepare_and_finalize_use_runtime_cwd_for_storage(self) -> None:
        with tempfile.TemporaryDirectory() as server_root_dir, tempfile.TemporaryDirectory() as runtime_root_dir:
            server_root = Path(server_root_dir)
            runtime_root = Path(runtime_root_dir)
            server = MemoryMCPServer(server_root)

            prepared = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_prepare_turn",
                        "arguments": {
                            "user_message": "このプロジェクトは Python で実装したい",
                            "session_id": "session-1",
                            "project_path": str(runtime_root),
                            "cwd": str(runtime_root),
                        },
                    },
                }
            )
            self.assertIsNotNone(prepared)
            prepared_payload = json.loads(prepared["result"]["content"][0]["text"])
            self.assertEqual(prepared_payload["resolved_project_root"], str(runtime_root))

            finalized = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_finalize_turn",
                        "arguments": {
                            "turn_token": prepared_payload["turn_token"],
                            "assistant_message": "了解です。Python 前提で進めます。",
                        },
                    },
                }
            )
            self.assertIsNotNone(finalized)
            runtime_memory = runtime_root / "knowledge" / "decisions" / "implementation-runtime.md"
            server_memory = server_root / "knowledge" / "decisions" / "implementation-runtime.md"
            self.assertTrue(runtime_memory.exists())
            self.assertFalse(server_memory.exists())

    def test_resolve_project_root_prioritizes_runtime_search_then_runtime_cwd_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir, tempfile.TemporaryDirectory() as fallback_dir:
            runtime_root = Path(tempdir)
            nested_cwd = runtime_root / "workspace" / "child"
            nested_cwd.mkdir(parents=True)
            (runtime_root / "pyproject.toml").write_text("", encoding="utf-8")
            (runtime_root / ".mcp.json").write_text("{}", encoding="utf-8")
            (runtime_root / "src" / "ai_memory_engine").mkdir(parents=True)

            with patch.dict("os.environ", {}, clear=True):
                resolved = resolve_project_root(project_path="", cwd=str(nested_cwd))
                self.assertEqual(resolved, runtime_root)

            markerless_cwd = Path(fallback_dir)
            with patch.dict("os.environ", {}, clear=True):
                resolved = resolve_project_root(project_path="", cwd=str(markerless_cwd))
                self.assertEqual(resolved, markerless_cwd.resolve())

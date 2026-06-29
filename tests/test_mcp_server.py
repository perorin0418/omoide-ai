from __future__ import annotations

import json
import tempfile
import unittest

from ai_memory_engine.config import EngineConfig
from ai_memory_engine.engine import MemoryEngine
from ai_memory_engine.mcp_server import MemoryMCPServer


class MemoryMCPServerTests(unittest.TestCase):
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

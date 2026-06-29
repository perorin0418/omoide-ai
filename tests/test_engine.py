from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from ai_memory_engine.config import EngineConfig
from ai_memory_engine.engine import MemoryEngine
from ai_memory_engine.markdown_store import MarkdownMemoryStore


class MemoryEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tempdir.name)
        self.engine = MemoryEngine(EngineConfig.for_project(self.project_root))

    def tearDown(self) -> None:
        self.engine.close()
        self.tempdir.cleanup()

    def test_prepare_turn_includes_context_block_and_project_path(self) -> None:
        self.assertEqual(self.engine.config.vector_backend, "lancedb")
        self.assertEqual(self.engine.config.graph_backend, "kuzu")
        self.engine.add_knowledge(
            title="Implementation Runtime",
            summary="The implementation runtime is python.",
            kind="decision",
            category="architecture",
            tags=["python", "runtime"],
            memory_id="implementation-runtime",
            subject="implementation_runtime",
            value="python",
            importance_score=0.95,
        )

        prepared = self.engine.memory_prepare_turn(
            user_message="何の言語で進める方針だったっけ？",
            session_id="session-1",
            project_path=str(self.project_root),
        )
        self.assertEqual(prepared.project_path, str(self.project_root))
        self.assertIn("Relevant memory context", prepared.context_block)
        self.assertIn("Implementation Runtime", prepared.context_block)

    def test_finalize_turn_promotes_markdown_memory(self) -> None:
        prepared = self.engine.memory_prepare_turn(
            user_message="このプロジェクトは Python で実装したい",
            session_id="session-1",
            project_path=str(self.project_root),
        )
        finalized = self.engine.memory_finalize_turn(
            turn_token=prepared.turn_token,
            assistant_message="了解です。Python 前提で進めます。",
        )
        self.assertEqual(finalized["candidate_count"], 1)
        record = self.engine.store.get_record("implementation-runtime")
        self.assertIsNotNone(record)
        self.assertEqual(record.summary, "The implementation runtime is python.")
        self.assertEqual(record.value, "python")
        self.assertEqual(
            Path(record.path).relative_to(self.project_root / "knowledge"),
            Path("decisions") / "implementation-runtime.md",
        )

    def test_later_turn_can_retrieve_previous_memory(self) -> None:
        prepared = self.engine.memory_prepare_turn(
            user_message="このプロジェクトは Python で実装したい",
            session_id="session-1",
            project_path=str(self.project_root),
        )
        self.engine.memory_finalize_turn(
            turn_token=prepared.turn_token,
            assistant_message="了解です。Python 前提で進めます。",
        )

        later = self.engine.memory_prepare_turn(
            user_message="何の言語で進める方針だったっけ？ Python だっけ？",
            session_id="session-1",
            project_path=str(self.project_root),
        )
        memory_ids = [item.memory.memory_id for item in later.retrieved_memories]
        self.assertIn("implementation-runtime", memory_ids)

    def test_conflict_is_visible_without_overwriting_existing_memory(self) -> None:
        first = self.engine.memory_prepare_turn(
            user_message="このプロジェクトは Python で実装したい",
            session_id="session-1",
        )
        self.engine.memory_finalize_turn(
            turn_token=first.turn_token,
            assistant_message="了解です。Python 前提で進めます。",
        )

        second = self.engine.memory_prepare_turn(
            user_message="やっぱりこのプロジェクトは Node.js で実装したい",
            session_id="session-1",
        )
        finalized = self.engine.memory_finalize_turn(
            turn_token=second.turn_token,
            assistant_message="Node.js に切り替える案もあります。",
        )

        self.assertEqual(finalized["conflicts"][0]["action"], "conflict")
        record = self.engine.store.get_record("implementation-runtime")
        self.assertIsNotNone(record)
        self.assertEqual(record.value, "python")
        self.assertTrue(any("Conflict noted" in detail for detail in record.details))

    def test_update_delete_and_rebuild_indexes(self) -> None:
        result = self.engine.add_knowledge(
            title="Markdown Source of Truth",
            summary="Markdown is the source of truth.",
            kind="decision",
            category="architecture",
            tags=["markdown"],
            memory_id="markdown-source-of-truth",
            subject="source_of_truth",
            value="markdown",
        )
        self.engine.update_knowledge(
            "markdown-source-of-truth",
            "Markdown is the source of truth for persisted memory.",
        )
        results = self.engine.search("source of truth", session_id="session-2")
        self.assertIn("markdown-source-of-truth", [item.memory.memory_id for item in results])

        deleted = self.engine.delete_knowledge("markdown-source-of-truth")
        self.assertTrue(deleted["deleted"])
        self.engine.rebuild_index()
        results_after_delete = self.engine.search("source of truth", session_id="session-3")
        self.assertNotIn("markdown-source-of-truth", [item.memory.memory_id for item in results_after_delete])
        self.assertFalse(Path(result["path"]).exists())

    def test_incremental_sync_tracks_chunk_hashes_per_document(self) -> None:
        body = "\n\n".join(
            [
                "# Heading One",
                " ".join(["alpha"] * 420),
                "- item one\n- item two\n- item three",
                " ".join(["beta"] * 420),
            ]
        )
        path = self.project_root / "knowledge" / "reference" / "chunk-test.md"
        store = MarkdownMemoryStore(self.project_root / "knowledge")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nmemory_id: chunk-test\nkind: fact\ncategory: reference\ntags: [chunk]\nimportance_score: 0.4\nupdated_at: '2026-06-29T00:00:00+00:00'\n---\n"
            + body,
            encoding="utf-8",
        )

        self.engine.synchronize()
        manifest = json.loads(self.engine.paths.manifest_path.read_text(encoding="utf-8"))
        first_chunks = manifest[str(path)]["chunks"]
        self.assertGreaterEqual(len(first_chunks), 2)

        path.write_text(
            path.read_text(encoding="utf-8").replace("beta beta beta", "gamma gamma gamma", 1),
            encoding="utf-8",
        )
        self.engine.synchronize()
        manifest_after = json.loads(self.engine.paths.manifest_path.read_text(encoding="utf-8"))
        second_chunks = manifest_after[str(path)]["chunks"]
        self.assertNotEqual(first_chunks, second_chunks)

    def test_optional_ai_assist_can_refine_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            project_root = Path(tempdir)
            script = project_root / "assist_refiner.py"
            script.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys

                    payload = json.load(sys.stdin)
                    candidates = payload["candidates"]
                    candidates[0]["tags"].append("ai-assisted")
                    candidates[0]["details"].append("Refined by local model")
                    candidates[0]["importance_score"] = 0.99
                    print(json.dumps({"candidates": candidates}, ensure_ascii=False))
                    """
                ).strip(),
                encoding="utf-8",
            )

            config = EngineConfig.for_project(project_root)
            config.ai_assist_command = (sys.executable, str(script))
            engine = MemoryEngine(config)

            prepared = engine.memory_prepare_turn(
                user_message="このプロジェクトは Python で実装したい",
                session_id="session-ai",
                project_path=str(project_root),
            )
            engine.memory_finalize_turn(
                turn_token=prepared.turn_token,
                assistant_message="了解です。Python 前提で進めます。",
            )

            record = engine.store.get_record("implementation-runtime")
            self.assertIsNotNone(record)
            self.assertIn("ai-assisted", record.tags)
            self.assertIn("Refined by local model", record.details)
            self.assertEqual(record.importance_score, 0.99)
            engine.close()

    def test_finalize_turn_promotes_user_current_razor_from_profile_talk(self) -> None:
        prepared = self.engine.memory_prepare_turn(
            user_message="自分が使ってるのはこのカミソリです\nhttps://schick.jp/collections/hydro-series/products/smr051",
            session_id="session-razor",
            project_path=str(self.project_root),
        )
        finalized = self.engine.memory_finalize_turn(
            turn_token=prepared.turn_token,
            assistant_message="これはかなり無難に良いやつです。ハイドロ系は潤滑ジェル多めで敏感肌向けです。",
        )

        self.assertGreaterEqual(finalized["candidate_count"], 1)
        record = self.engine.store.get_record("user-current-razor")
        self.assertIsNotNone(record)
        self.assertEqual(record.value, "Schick Hydro 敏感肌用")
        self.assertIn("razor", record.subject)
        self.assertEqual(
            Path(record.path).relative_to(self.project_root / "knowledge"),
            Path("user-profile") / "products" / "user-current-razor.md",
        )

    def test_reset_memory_clears_markdown_state_and_pending_turns(self) -> None:
        self.engine.add_knowledge(
            title="Implementation Runtime",
            summary="The implementation runtime is python.",
            kind="decision",
            category="architecture",
            tags=["python", "runtime"],
            memory_id="implementation-runtime",
            subject="implementation_runtime",
            value="python",
        )
        prepared = self.engine.memory_prepare_turn(
            user_message="次に何を決めるべき？",
            session_id="session-reset",
            project_path=str(self.project_root),
        )

        reset = self.engine.reset_memory()

        self.assertTrue(reset["reset"])
        self.assertEqual(self.engine.store.list_records(), [])
        self.assertEqual(list(self.engine.paths.pending_turns_root.glob("*.json")), [])
        self.assertEqual(self.engine.search("python", session_id="session-after-reset"), [])
        self.assertFalse((self.project_root / "knowledge" / "decisions" / "implementation-runtime.md").exists())
        self.assertFalse((self.paths_pending_file(prepared.turn_token)).exists())

    def test_manual_nested_category_can_hint_custom_folder(self) -> None:
        result = self.engine.add_knowledge(
            title="Vendor Note",
            summary="This note should land in a caller-defined folder.",
            kind="fact",
            category="vendors/shick",
            memory_id="vendor-note",
        )

        self.assertTrue((self.project_root / "knowledge" / "vendors" / "shick" / "vendor-note.md").exists())
        self.assertEqual(Path(result["path"]).name, "vendor-note.md")

    def paths_pending_file(self, turn_token: str) -> Path:
        return self.engine.paths.pending_turns_root / f"{turn_token}.json"

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import EngineConfig
from .engine import MemoryEngine


def build_engine(project_root: str | None) -> MemoryEngine:
    root = Path(project_root or ".").resolve()
    return MemoryEngine(EngineConfig.for_project(root))


def main() -> None:
    parser = argparse.ArgumentParser(prog="omoide-ai")
    parser.add_argument("--project-root", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)

    subparsers.add_parser("sync")
    subparsers.add_parser("rebuild")
    reset = subparsers.add_parser("reset")
    reset.add_argument("--yes", action="store_true")

    prepare = subparsers.add_parser("prepare-turn")
    prepare.add_argument("--session-id", required=True)
    prepare.add_argument("--message", required=True)
    prepare.add_argument("--project-path", default="")
    prepare.add_argument("--repo", default="")
    prepare.add_argument("--branch", default="")
    prepare.add_argument("--cwd", default="")

    finalize = subparsers.add_parser("finalize-turn")
    finalize.add_argument("--turn-token", required=True)
    finalize.add_argument("--assistant-message", required=True)
    finalize.add_argument("--final-status", default="completed")

    add = subparsers.add_parser("add-knowledge")
    add.add_argument("--title", required=True)
    add.add_argument("--summary", required=True)
    add.add_argument("--kind", default="fact")
    add.add_argument("--category", default="general")
    add.add_argument("--tags", nargs="*", default=[])
    add.add_argument("--subject", default="")
    add.add_argument("--value", default="")
    add.add_argument("--importance-score", type=float, default=0.5)

    args = parser.parse_args()
    engine = build_engine(args.project_root)

    if args.command == "search":
        results = engine.search(args.query, top_k=args.top_k)
        print(json.dumps([_serialize_result(item) for item in results], indent=2, ensure_ascii=False))
    elif args.command == "sync":
        print(json.dumps(engine.synchronize(), indent=2, ensure_ascii=False))
    elif args.command == "rebuild":
        print(json.dumps(engine.rebuild_index(), indent=2, ensure_ascii=False))
    elif args.command == "reset":
        if not args.yes:
            parser.error("reset deletes persisted memory and state; rerun with --yes to confirm")
        print(json.dumps(engine.reset_memory(), indent=2, ensure_ascii=False))
    elif args.command == "prepare-turn":
        prepared = engine.memory_prepare_turn(
            user_message=args.message,
            session_id=args.session_id,
            project_path=args.project_path,
            repo=args.repo,
            branch=args.branch,
            cwd=args.cwd,
        )
        print(
            json.dumps(
                {
                    "turn_token": prepared.turn_token,
                    "retrieved_memories": [_serialize_result(item) for item in prepared.retrieved_memories],
                    "project_path": prepared.project_path,
                    "related_entities": prepared.related_entities,
                    "open_questions": prepared.open_questions,
                    "context_block": prepared.context_block,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.command == "finalize-turn":
        result = engine.memory_finalize_turn(
            turn_token=args.turn_token,
            assistant_message=args.assistant_message,
            final_status=args.final_status,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "add-knowledge":
        result = engine.add_knowledge(
            title=args.title,
            summary=args.summary,
            kind=args.kind,
            category=args.category,
            tags=args.tags,
            subject=args.subject,
            value=args.value,
            importance_score=args.importance_score,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _serialize_result(item) -> dict[str, object]:
    return {
        "memory_id": item.memory.memory_id,
        "title": item.memory.title,
        "summary": item.memory.summary,
        "score": item.score,
        "reason": item.reason,
        "tags": item.memory.tags,
        "path": item.memory.path,
    }


if __name__ == "__main__":
    main()

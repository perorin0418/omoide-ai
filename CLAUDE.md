# Claude Code Project Instructions

This repository uses the local `omoide-ai` MCP server for long-term memory.

## Required turn contract

For every user turn in this repository:

1. Before drafting the response, call `memory_prepare_turn`.
2. Pass:
   - `user_message`
   - `session_id`
   - `project_path`
   - `repo`
   - `branch`
   - `cwd`
3. Use the returned `retrieved_memories`, `open_questions`, and `context_block` as context for the response.
4. After the response is finalized, call `memory_finalize_turn`.
5. Pass:
   - `turn_token`
   - `assistant_message`
   - `tool_results`
   - `final_status`

## Additional memory tools

- Use `memory_upsert_note` when the user asks to explicitly save durable knowledge.
- Use `memory_search` for manual recall outside the default turn flow.
- Use `memory_sync` after direct Markdown edits under `knowledge/`.
- Use `memory_rebuild` only when derived indexes must be rebuilt from Markdown.

## Memory policy

- Markdown under `knowledge/` is the source of truth.
- Do not store durable knowledge only in DuckDB, LanceDB, or LadybugDB.
- If a turn produces a durable decision, preference, constraint, fact, task-context item, or open question, ensure it is finalized through the memory engine.

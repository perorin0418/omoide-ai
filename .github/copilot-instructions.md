# Copilot Instructions for AI Memory Engine

This repository uses the local `omoide-ai` MCP server for reusable memory across conversations.

## Required workflow

For each user turn:

1. Call `memory_prepare_turn` before writing the response.
2. Include:
   - `user_message`
   - `session_id`
   - `project_path`
   - `repo`
   - `branch`
   - `cwd`
3. Read and use the returned `retrieved_memories`, `open_questions`, and `context_block`.
4. After the final response is ready, call `memory_finalize_turn`.
5. Include:
   - `turn_token`
   - `assistant_message`
   - `tool_results`
   - `final_status`

## When to use other tools

- `memory_upsert_note`: save explicit long-term knowledge on demand
- `memory_search`: perform manual recall
- `memory_sync`: resync Markdown changes
- `memory_rebuild`: rebuild derived indexes from Markdown

## Memory rules

- Treat Markdown in `knowledge/` as the source of truth.
- Keep durable decisions and constraints reflected in Markdown-backed memory.
- Do not leave important project knowledge only in transient chat context.

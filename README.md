# AI Memory Engine

Local-first memory engine for `GitHub Copilot CLI` and `Claude Code`.

- [日本語版 README](README.ja.md)

## What it does

- stores reusable memory from conversations
- keeps Markdown as the source of truth
- builds derived indexes for retrieval
- exposes a shared local MCP server for both agents

## Architecture

```text
Claude Code / Copilot CLI
        ↓
Local MCP stdio server
        ↓
AI Memory Engine (Python)
   ├─ Conversation ingest
   ├─ Memory extraction
   ├─ Markdown memory store
   ├─ Incremental sync pipeline
   ├─ Retrieval / ranking
   └─ Event emission
        ↓
   ├─ LanceDB
   ├─ Kuzu
   └─ DuckDB
```

## Install

```bash
python -m pip install -e .
```

## Publish and install from PyPI

Once the package is published to PyPI, users can install or run it without cloning this repository.

### Install the CLI from PyPI

```bash
python -m pip install omoide-ai
```

### Run the MCP server with uvx

```bash
uvx --from omoide-ai omoide-ai-mcp
```

### MCP config for a published package

For clients that launch a local stdio MCP server, point them at `uvx` instead of a repository-local virtualenv:

```json
{
  "mcpServers": {
    "omoide-ai": {
      "type": "local",
      "command": "uvx",
      "args": ["--from", "omoide-ai", "omoide-ai-mcp"],
      "timeout": 60000
    }
  }
}
```

### Maintainer release flow

1. Create a GitHub release or run the `Publish PyPI` workflow manually.
2. Add a repository secret named `PYPI_API_TOKEN`.
3. The workflow builds the package with `uv build` and uploads it to PyPI.
4. If the same version has already been published, the workflow skips the existing files instead of failing. To publish a new release, update `version` in `pyproject.toml` first.

## Project layout

Markdown under `knowledge/` is the source of truth. Derived state is written under `.ai-memory-engine/`. Daily interaction journals are appended under `journal/`.

You do not need to pre-create fixed folders. The engine places memories into generic folders based on their role, for example:

```text
knowledge/
  decisions/
  constraints/
  reference/
  work-context/tasks/
  work-context/open-questions/
  user-profile/preferences/
  user-profile/products/
journal/
  2026-06-30.md
```

Rules are generic rather than technical:

1. `decision` memories go to `knowledge/decisions/`
2. `constraint` memories go to `knowledge/constraints/`
3. `fact` memories go to `knowledge/reference/`
4. `task-context` memories go to `knowledge/work-context/tasks/`
5. `open-question` memories go to `knowledge/work-context/open-questions/`
6. `user-profile` tags or `user_` subjects go to `knowledge/user-profile/...`

If you want to hint a custom nested folder, pass a slash-delimited `category` such as `vendors/schick`.

## CLI examples

```bash
omoide-ai sync
omoide-ai rebuild
omoide-ai search "What runtime did we choose?"
omoide-ai prepare-turn --session-id demo --message "このプロジェクトは Python で実装したい"
omoide-ai finalize-turn --turn-token <token> --assistant-message "了解。Python で進めます。"
```

Each `finalize-turn` call still promotes reusable memory into `knowledge/`, and now also appends the full exchange to that day's Markdown journal in `journal/YYYY-MM-DD.md`.

For MCP usage, the effective project root now resolves in this order:

1. `AI_MEMORY_ENGINE_PROJECT_ROOT`
2. `CLAUDE_PROJECT_DIR`
3. a project root discovered from the request's `project_path` or `cwd`
4. the request's `cwd`
5. the MCP server process context as a final fallback

## Locked memory mode

If you want the assistant to answer against a fixed set of memories, set `AI_MEMORY_ENGINE_LOCKED_MEMORY_IDS` to a comma- or newline-delimited list of `memory_id` values before calling `prepare-turn`.

```bash
AI_MEMORY_ENGINE_LOCKED_MEMORY_IDS=implementation-runtime,markdown-source-of-truth
```

In this mode:

1. `prepare-turn` skips live retrieval and always returns the configured memories in the given order
2. `context_block` starts with `Locked memory context:`
3. `finalize-turn` still stores the conversation in analytics and the journal, but skips promoting new Markdown memories so the memory base stays fixed

If any configured `memory_id` does not exist, `prepare-turn` fails fast instead of silently falling back to dynamic retrieval.

## MCP setup

### Claude Code

This repository includes `.mcp.json` for repository-local development. After publishing to PyPI, you can switch the command to the `uvx` example above.

### GitHub Copilot CLI

This repository includes `.github/mcp.json` for repository-local development. After publishing to PyPI, you can switch the command to the `uvx` example above.

Repository-scoped instructions are included in:

- `CLAUDE.md`
- `.github/copilot-instructions.md`

## Optional AI-assisted extraction

The engine includes an optional refinement step for memory extraction. It stays offline-first by default and does nothing unless you configure a local command.

Set `AI_MEMORY_ENGINE_ASSIST_COMMAND` to a local command that:

1. reads JSON from stdin
2. returns JSON on stdout
3. outputs a `candidates` array with refined memory candidates

Example shape:

```json
{
  "candidates": [
    {
      "memory_id": "implementation-runtime",
      "title": "Implementation Runtime",
      "kind": "decision",
      "summary": "The implementation runtime is python.",
      "subject": "implementation_runtime",
      "value": "python",
      "category": "project/implementation",
      "tags": ["python", "runtime"],
      "details": ["Refined by local model"],
      "confidence": 0.98,
      "importance_score": 0.99
    }
  ]
}
```

Use `AI_MEMORY_ENGINE_ASSIST_TIMEOUT_SECONDS` to control the subprocess timeout.

## Notes

- `DuckDB`, `LanceDB`, and `Kuzu` are required runtime dependencies.
- Markdown remains the source of truth even though vector and graph stores are always persisted.

## Resetting memory state

Use the following command to clear saved Markdown memories and derived local state before a fresh verification run:

```bash
omoide-ai reset --yes
```

This resets `knowledge/` memories, DuckDB analytics, the index manifest, pending turns, and derived vector/graph state.

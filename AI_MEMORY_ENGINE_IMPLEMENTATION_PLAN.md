# AI Memory Engine Implementation Plan

## Goal

Build a local-first memory engine that lets `GitHub Copilot CLI` and `Claude Code`:

1. talk with the user
2. persist reusable memory from the conversation
3. reuse that memory in later conversations

Markdown is always the source of truth. All derived stores must be rebuildable from Markdown.

## Primary Architecture

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
Derived stores
   ├─ LanceDB  : semantic retrieval
   ├─ LadybugDB: knowledge graph
   └─ DuckDB   : conversation/event analytics
```

## Why MCP

- The engine should expose a concrete tool interface to both `Claude Code` and `GitHub Copilot CLI`.
- The shared transport is a **local MCP stdio server** implemented in Python.
- MCP is only the transport layer. It does **not** automatically receive every chat turn.
- To make memory persistence deterministic, the engine must define an explicit turn lifecycle with tool calls before and after each response.

## Turn Lifecycle

### 1. Before the assistant responds

The agent calls `memory_prepare_turn`.

**Input**

- `user_message`
- `session_id`
- `project_path`
- `repo`
- `branch`
- `cwd`

**Output**

- `turn_token`
- `retrieved_memories`
- `related_entities`
- `open_questions`

**Purpose**

- search previously stored memory
- return relevant context for the current user message
- create a stable token that will be used to finalize the turn

### 2. Assistant generates its response

The agent uses the retrieved memories as context when preparing the reply.

### 3. After the response is finalized

The agent calls `memory_finalize_turn`.

**Input**

- `turn_token`
- `assistant_message`
- `tool_results`
- `final_status`

**Purpose**

- persist the conversation turn
- extract long-term memory candidates
- update Markdown if needed
- sync only changed documents into derived stores

## Does AI run inside `memory_finalize_turn`?

Yes, but only as a **memory extraction helper**, not as a second chat assistant.

The processing model is:

1. **deterministic core logic**
   - save raw turn data
   - load related memories
   - compare against existing Markdown
   - decide which files may change
2. **optional memory extraction AI**
   - classify candidate memory
   - summarize a reusable fact or decision
   - generate tags
   - help detect conflicts
3. **write and sync**
   - update Markdown
   - update LanceDB, LadybugDB, and DuckDB incrementally

For MVP, extraction should be mostly rule-based with optional AI assist for ambiguous turns.

## MCP Tool Contract

### `memory_prepare_turn`

Runs retrieval before the assistant answers.

### `memory_finalize_turn`

Finalizes a turn and persists reusable memory.

### `memory_upsert_note`

Allows the assistant to explicitly store a structured long-term note when something is clearly important.

### `memory_search`

Manual retrieval outside the automatic turn flow.

### `memory_sync`

Synchronizes changed Markdown documents into derived stores.

### `memory_rebuild`

Rebuilds all derived stores from Markdown.

## Storage Responsibilities

### Markdown

**Source of truth**

- long-term memory
- human-editable records
- Git-managed history

Directory example:

```text
knowledge/
  architecture/
  domain/
  aws/
  oracle/
```

### LanceDB

**Semantic search index**

- embeddings
- metadata
- document path
- chunk id

### LadybugDB

**Knowledge graph**

- entities
- relationships
- concepts

### DuckDB

**Operational analytics**

- raw conversation turns
- memory events
- search logs
- importance scores
- usage statistics

DuckDB is not a source of truth.

## Conversation Persistence Design

Raw turn data is stored first in DuckDB.

Suggested tables:

- `conversation_turns`
- `memory_events`
- `search_logs`

Then the engine extracts only reusable long-term knowledge and promotes it into Markdown.

## Memory Extraction Pipeline

Inside `memory_finalize_turn`:

1. save the raw conversation turn in DuckDB
2. extract candidate memories from the turn
3. classify them into:
   - `decision`
   - `preference`
   - `constraint`
   - `fact`
   - `task-context`
   - `open-question`
4. normalize values and tags
5. compare against existing memory using:
   - `memory_id`
   - semantic similarity
   - tag overlap
6. decide:
   - `add`
   - `update`
   - `conflict`
   - `ignore`
7. update Markdown
8. emit events
9. synchronize changed files only

## Initial Extraction Strategy

### Rule-based first

Examples:

- `〜したい` -> `preference`
- `〜にする` -> `decision`
- `〜しない` -> `constraint`
- `未定` / `あとで決める` -> `open-question`

### Optional AI assist

Use a small extraction model only when needed for:

- summarization
- tag generation
- conflict hints
- importance scoring

## Markdown Memory Format

Each persistent memory should have stable metadata in frontmatter.

```yaml
---
memory_id: arch-runtime-python
kind: decision
tags: [architecture, python]
sources:
  - session_id: abc123
    turn: 12
updated_at: 2026-06-29T18:00:00+09:00
---
```

Example body:

```md
# Implementation Runtime

- Current decision: Python
- Reason: Local SDK support for LanceDB, LadybugDB, and DuckDB is strong
- Evidence: planning conversation on 2026-06-29
```

## Incremental Synchronization

Only changed files should be reindexed.

### Document-level tracking

- `document_hash` per Markdown file

### Chunk-level tracking

- split by heading
- split by code block
- split by list
- split by paragraph
- target chunk size: `300-800 tokens`
- overlap: `50 tokens`
- `chunk_hash` per chunk

### Sync flow

```text
Markdown changed
  ↓
Chunk diff
  ↓
Embedding update
  ↓
LanceDB upsert/delete
  ↓
Entity extraction
  ↓
LadybugDB upsert/delete
  ↓
DuckDB event write
```

## Retrieval Flow

```text
User question
  ↓
memory_prepare_turn
  ↓
Embedding query
  ↓
LanceDB semantic search
  ↓
LadybugDB graph expansion
  ↓
Merge + ranking
  ↓
Context builder
  ↓
Assistant response
```

## Agent-Specific Integration

### Claude Code

- register the local stdio server in `.mcp.json` or user config
- enforce this contract in project instructions:
  - call `memory_prepare_turn` before answering
  - call `memory_finalize_turn` after answering

### GitHub Copilot CLI

- register the same server in `.github/mcp.json` or user config
- use repo-scoped instructions and MCP configuration to follow the same turn contract

## MVP Scope

### Must have

- Python core engine
- local MCP stdio server
- `memory_prepare_turn`
- `memory_finalize_turn`
- DuckDB raw conversation storage
- Markdown memory promotion
- incremental LanceDB sync

### Phase 2

- LadybugDB graph expansion
- better conflict resolution
- automation wrappers or hooks for more deterministic capture
- importance scoring improvements
- recall quality evaluation

## Implementation Phases

1. **Core package skeleton**
   - package structure
   - config model
   - service boundaries
   - public API surface
2. **MCP server contract**
   - stdio server
   - tool schemas
   - Claude Code config example
   - Copilot CLI config example
3. **Markdown memory model**
   - file layout
   - frontmatter schema
   - memory id rules
   - update policy
4. **Conversation persistence**
   - DuckDB schema
   - raw turn logging
   - event logging
5. **Memory extraction**
   - rule-based extractor
   - optional AI-assisted extractor
   - normalization pipeline
6. **Incremental indexing**
   - chunker
   - hashing
   - LanceDB adapter
   - sync events
7. **Graph layer**
   - entity extraction
   - LadybugDB adapter
   - graph expansion retrieval
8. **Hybrid retrieval**
   - merge and ranking
   - context builder
9. **End-to-end validation**
   - remember in one turn
   - retrieve in a later turn
   - update existing memory
   - delete and rebuild indexes

## Post-Implementation Check List

### Conversation capture

- [ ] `memory_prepare_turn` is called before response generation
- [ ] `memory_finalize_turn` is called after response generation
- [ ] raw conversation turns are persisted in DuckDB

### Memory persistence

- [ ] reusable knowledge is promoted into Markdown
- [ ] Markdown remains readable and editable by humans
- [ ] no knowledge exists only inside a database

### Incremental sync

- [ ] only changed Markdown files are reprocessed
- [ ] only changed chunks are re-embedded
- [ ] LanceDB reflects document additions, updates, and deletions
- [ ] LadybugDB reflects entity and relationship changes

### Retrieval quality

- [ ] a later conversation can retrieve a prior decision
- [ ] retrieved memory is injected before the assistant responds
- [ ] hybrid retrieval returns better context than semantic search alone

### Recovery and safety

- [ ] all derived stores can be rebuilt from Markdown
- [ ] deleting a memory file removes stale vector and graph entries
- [ ] conflict cases are visible and do not silently overwrite important memory

### Agent integration

- [ ] Claude Code works with the local MCP stdio server
- [ ] Copilot CLI works with the same MCP server
- [ ] project-level configuration is documented and reproducible

# AI Memory Engine

`GitHub Copilot CLI` と `Claude Code` 向けの、ローカルファーストな AI メモリエンジンです。

## 概要

このプロジェクトは、AI との会話から再利用価値のある知識を抽出し、**Markdown を正本**として保存します。  
保存された知識は、次回以降の会話で検索され、応答精度の向上に使われます。

主な特徴:

- Markdown を唯一の source of truth として扱う
- ローカル完結、オフライン前提
- DuckDB に会話・イベント履歴を保存
- LanceDB / Kuzu を常時利用して派生インデックスを永続化
- `Claude Code` / `GitHub Copilot CLI` から同じ MCP server を利用可能

---

## アーキテクチャ

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

---

## 動作要件

- Python 3.11 以上

---

## インストール

### 基本インストール

```bash
python -m pip install -e .
```

## ディレクトリ構成

- `knowledge/` 配下の Markdown が正本です
- AI とのやり取りの日誌は `journal/` 配下に日付ごとで追記されます
- 派生データは `.ai-memory-engine/` 配下に保存されます
- **事前にフォルダーを用意する必要はありません**

保存先フォルダーは、記憶の種類から自動で決まります。たとえば:

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

主なルール:

1. `decision` は `knowledge/decisions/`
2. `constraint` は `knowledge/constraints/`
3. `fact` は `knowledge/reference/`
4. `task-context` は `knowledge/work-context/tasks/`
5. `open-question` は `knowledge/work-context/open-questions/`
6. `user-profile` タグや `user_` 系 subject は `knowledge/user-profile/...`

必要なら `category` に `vendors/schick` のような **入れ子パス** を渡して、保存先フォルダーのヒントにもできます。

主な生成物:

- `.ai-memory-engine/analytics.duckdb`
- `.ai-memory-engine/index_manifest.json`
- `.ai-memory-engine/pending_turns/`
- `.ai-memory-engine/vector/`
- `.ai-memory-engine/graph/`

---

## 基本的な使い方

### 1. Markdown を同期する

```bash
ai-memory-engine sync
```

`knowledge/` 配下の Markdown を読み取り、必要な差分だけを再インデックスします。

### 2. 全インデックスを再構築する

```bash
ai-memory-engine rebuild
```

Markdown を正本として、派生ストアを再構築します。

### 3. 手動で知識を追加する

```bash
ai-memory-engine add-knowledge ^
  --title "Implementation Runtime" ^
  --summary "The implementation runtime is python." ^
  --kind decision ^
  --category project/implementation ^
  --tags python runtime ^
  --subject implementation_runtime ^
  --value python ^
  --importance-score 0.95
```

### 4. 知識を検索する

```bash
ai-memory-engine search "What runtime did we choose?"
```

### 5. 記憶を一括リセットする

```bash
ai-memory-engine reset --yes
```

このコマンドは、動作確認をやり直したいときのために次をまとめて初期化します。

1. `knowledge/` 配下の保存済み Markdown 記憶
2. `.ai-memory-engine/analytics.duckdb`
3. `.ai-memory-engine/index_manifest.json`
4. `.ai-memory-engine/pending_turns/`
5. ベクトル / グラフの派生ストア

安全のため、`--yes` を付けた場合だけ実行されます。

---

## 会話ターンの流れ

このプロジェクトでは、1 ターンごとに次の流れで使います。

### 1. 応答前

```bash
ai-memory-engine prepare-turn ^
  --session-id demo ^
  --project-path "D:\path\to\repo" ^
  --repo "owner/repo" ^
  --branch "main" ^
  --cwd "D:\path\to\repo" ^
  --message "このプロジェクトは Python で実装したい"
```

返却される主な情報:

- `turn_token`
- `retrieved_memories`
- `related_entities`
- `open_questions`
- `context_block`

AI はこの結果を見て応答を組み立てます。

### 2. 応答後

```bash
ai-memory-engine finalize-turn ^
  --turn-token <token> ^
  --assistant-message "了解です。Python 前提で進めます。" ^
  --final-status completed
```

この処理で:

1. 会話ターンを DuckDB に保存
2. 記憶候補を抽出
3. Markdown に反映
4. `journal/YYYY-MM-DD.md` にその日の会話日誌を追記
5. 差分だけ同期

が実行されます。

---

## Claude Code での利用

このリポジトリには `Claude Code` 向けの設定が含まれています。

- `.mcp.json`
- `CLAUDE.md`

### 前提

1. このリポジトリでパッケージをインストールする
2. Claude Code からこのプロジェクトを開く
3. `.mcp.json` を使って `ai-memory-engine` MCP server を読み込む

### 期待する動作

`CLAUDE.md` により、各ターンで以下を守る前提です。

1. 応答前に `memory_prepare_turn`
2. 応答後に `memory_finalize_turn`

---

## GitHub Copilot CLI での利用

このリポジトリには Copilot CLI 向けの設定が含まれています。

- `.github/mcp.json`
- `.github/copilot-instructions.md`

### 前提

1. このリポジトリでパッケージをインストールする
2. Copilot CLI で MCP 設定を読み込む
3. リポジトリ instruction に従って turn contract を使う

---

## Optional AI-assisted extraction

通常はルールベース抽出で動きます。  
ローカルの補助モデルを使って記憶候補を整形したい場合は、環境変数でコマンドを指定します。

### 設定

```powershell
$env:AI_MEMORY_ENGINE_ASSIST_COMMAND = "python D:\path\to\refiner.py"
$env:AI_MEMORY_ENGINE_ASSIST_TIMEOUT_SECONDS = "15"
```

### 補助コマンドの仕様

- stdin から JSON を受け取る
- stdout に JSON を返す
- `candidates` 配列を返す

返却例:

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
      "category": "architecture",
      "tags": ["python", "runtime"],
      "details": ["Refined by local model"],
      "confidence": 0.98,
      "importance_score": 0.99
    }
  ]
}
```

未設定時は no-op で、通常のルールベース抽出だけが使われます。

---

## 保存されるデータ

### Markdown

長期記憶の正本です。

### DuckDB

主に以下を保存します。

- `conversation_turns`
- `memory_events`
- `search_logs`
- `memory_usage_stats`

### LanceDB / Kuzu

検索用のベクトルストアと知識グラフとして、常に永続化されます。

---

## 典型的な運用フロー

1. Claude Code / Copilot CLI でプロジェクトを開く
2. ユーザーが会話する
3. 応答前に関連記憶を検索する
4. 応答後に会話から長期記憶候補を抽出する
5. Markdown に保存する
6. 差分だけベクトル・グラフ・分析ストアへ反映する
7. 次回以降の会話で再利用する

---

## 注意事項

- durable knowledge は Markdown に必ず反映してください
- DuckDB / LanceDB / Kuzu だけに知識を残さないでください
- `rebuild` によって Markdown から派生ストアを復元できます

---

## 関連ファイル

- `README.md` : 英語版 README
- `README.ja.md` : 日本語版 README
- `AI_MEMORY_ENGINE_IMPLEMENTATION_PLAN.md` : 実装計画
- `CLAUDE.md` : Claude Code 用 instruction
- `.github/copilot-instructions.md` : Copilot 用 instruction

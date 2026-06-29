from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class DailyJournalStore:
    def __init__(self, journal_root: Path) -> None:
        self.journal_root = journal_root
        self.journal_root.mkdir(parents=True, exist_ok=True)

    def append_turn(
        self,
        *,
        created_at: str,
        turn_token: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        tool_results: object,
        final_status: str,
        project_path: str,
        repo: str,
        branch: str,
        cwd: str,
    ) -> Path:
        timestamp = datetime.fromisoformat(created_at)
        path = self.journal_root / f"{timestamp.date().isoformat()}.md"
        if not path.exists():
            path.write_text(self._render_header(timestamp), encoding="utf-8")

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                self._render_entry(
                    timestamp=timestamp,
                    turn_token=turn_token,
                    session_id=session_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    tool_results=tool_results,
                    final_status=final_status,
                    project_path=project_path,
                    repo=repo,
                    branch=branch,
                    cwd=cwd,
                )
            )
        return path

    def _render_header(self, timestamp: datetime) -> str:
        day = timestamp.date().isoformat()
        return (
            f"# {day} Journal\n\n"
            "Auto-appended from finalized AI turns.\n"
        )

    def _render_entry(
        self,
        *,
        timestamp: datetime,
        turn_token: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        tool_results: object,
        final_status: str,
        project_path: str,
        repo: str,
        branch: str,
        cwd: str,
    ) -> str:
        metadata = [
            f"- Session: {session_id}",
            f"- Turn token: {turn_token}",
            f"- Status: {final_status}",
        ]
        if repo:
            metadata.append(f"- Repo: {repo}")
        if branch:
            metadata.append(f"- Branch: {branch}")
        if cwd:
            metadata.append(f"- CWD: {cwd}")
        if project_path:
            metadata.append(f"- Project path: {project_path}")

        sections = [
            "",
            f"## {timestamp.timetz().replace(microsecond=0).isoformat()}",
            *metadata,
            "",
            "### User",
            "```text",
            user_message,
            "```",
            "",
            "### Assistant",
            "```text",
            assistant_message,
            "```",
        ]

        if tool_results:
            sections.extend(
                [
                    "",
                    "### Tool results",
                    "```json",
                    json.dumps(tool_results, ensure_ascii=False, indent=2),
                    "```",
                ]
            )

        sections.append("")
        return "\n".join(sections)

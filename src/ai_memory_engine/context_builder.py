from __future__ import annotations

from .models import SearchResult


class ContextBuilder:
    def build(self, results: list[SearchResult], open_questions: list[str], memory_mode: str = "dynamic") -> str:
        heading = "Locked memory context:" if memory_mode == "locked" else "Relevant memory context:"
        lines = [heading]
        if not results:
            lines.append("- No prior memory matched this turn.")
        else:
            for result in results:
                lines.append(
                    f"- [{result.memory.kind.value}] {result.memory.title}: {result.memory.summary}"
                )
        if open_questions:
            lines.append("Open questions:")
            for question in open_questions:
                lines.append(f"- {question}")
        return "\n".join(lines)

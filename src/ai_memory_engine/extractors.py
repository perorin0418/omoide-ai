from __future__ import annotations

import re

from .models import MemoryCandidate, MemoryKind
from .utils import normalize_value, slugify, split_sentences


class RuleBasedMemoryExtractor:
    def extract(self, user_message: str, assistant_message: str) -> list[MemoryCandidate]:
        combined = f"{user_message}\n{assistant_message}".strip()
        candidates: list[MemoryCandidate] = []
        product_candidate = self._extract_user_product_fact(user_message, assistant_message)
        if product_candidate:
            candidates.append(product_candidate)
        for sentence in split_sentences(combined):
            lower = sentence.lower()
            for extractor in (
                self._extract_runtime,
                self._extract_source_of_truth,
                self._extract_cloud_constraint,
                self._extract_single_user_fact,
                self._extract_open_question,
                self._extract_task_context,
                self._extract_preference,
                self._extract_decision,
                self._extract_fact,
            ):
                candidate = extractor(sentence, lower)
                if candidate:
                    candidates.append(candidate)
                    break
        return self._dedupe(candidates)

    def _extract_user_product_fact(self, user_message: str, assistant_message: str) -> MemoryCandidate | None:
        combined = f"{user_message}\n{assistant_message}"
        if not self._mentions_user_ownership(user_message):
            return None

        product_name, tags = self._infer_product_name(combined)
        if not product_name:
            return None

        product_type = self._infer_product_type(combined)
        title = "User Current Product"
        details = ["Captured from a conversation about the user's current item."]
        if product_type == "razor":
            title = "User Current Razor"
            details.append("The user referred to the razor they currently use.")

        return MemoryCandidate(
            memory_id=f"user-current-{product_type}",
            title=title,
            kind=MemoryKind.FACT,
            summary=f"The user currently uses {product_name}.",
            subject=f"user_current_{product_type}",
            value=product_name,
            category="user-profile",
            tags=tags,
            details=details,
            importance_score=0.78,
        )

    def _mentions_user_ownership(self, user_message: str) -> bool:
        lowered = user_message.lower()
        return any(
            marker in user_message or marker in lowered
            for marker in (
                "私が使っている",
                "私が使ってる",
                "自分が使っている",
                "自分が使ってる",
                "使っているのは",
                "使ってるのは",
                "愛用している",
                "愛用してる",
                "i use",
                "i'm using",
                "my razor",
            )
        )

    def _infer_product_name(self, combined: str) -> tuple[str, list[str]]:
        text = combined.strip()
        tags: list[str] = []

        explicit = re.search(
            r"(?:私|自分)?(?:が)?使って(?:いる|る)(?:のは)?(?:\s*[:：]?\s*)(.+?)(?:です|だよ|だ|なんだけど|なんですが|。|！|!|\?|$)",
            text,
        )
        if explicit:
            candidate = explicit.group(1).strip()
            if candidate and not self._is_generic_product_reference(candidate) and "http" not in candidate.lower():
                return candidate, ["user-profile", "product"]

        normalized = combined.lower()
        parts: list[str] = []
        if "schick" in normalized or "schick.jp" in normalized:
            parts.append("Schick")
            tags.append("schick")
        if "hydro" in normalized or "ハイドロ" in combined:
            parts.append("Hydro")
            tags.append("hydro")
        if "敏感肌" in combined:
            parts.append("敏感肌用")
            tags.append("sensitive-skin")

        if not parts:
            return "", []

        seen: list[str] = []
        for part in parts:
            if part not in seen:
                seen.append(part)
        return " ".join(seen), ["user-profile", "product", *tags]

    def _is_generic_product_reference(self, candidate: str) -> bool:
        normalized = re.sub(r"\s+", "", candidate.lower())
        if not normalized:
            return True
        generic_markers = (
            "これ",
            "これです",
            "これだよ",
            "このカミソリ",
            "このカミソリです",
            "この髭剃り",
            "このひげ剃り",
            "このシェーバー",
            "この商品",
            "この製品",
        )
        return any(marker in normalized for marker in generic_markers)

    def _infer_product_type(self, combined: str) -> str:
        lowered = combined.lower()
        if any(marker in combined for marker in ("カミソリ", "髭剃り", "ひげ剃り", "刃")):
            return "razor"
        if any(marker in lowered for marker in ("razor", "schick", "hydro", "blade", "shaver")):
            return "razor"
        return "product"

    def _extract_runtime(self, text: str, lower: str) -> MemoryCandidate | None:
        runtime: str | None = None
        for label in ("python", "python3", "node.js", "node", "typescript"):
            if label in lower:
                runtime = normalize_value(label)
                break
        if runtime and ("実装" in text or "runtime" in lower or "言語" in text or "language" in lower):
            return MemoryCandidate(
                memory_id="implementation-runtime",
                title="Implementation Runtime",
                kind=MemoryKind.DECISION,
                summary=f"The implementation runtime is {runtime}.",
                subject="implementation_runtime",
                value=runtime,
                category="project",
                tags=["architecture", runtime, "runtime"],
                details=[f"Reason: {runtime} was chosen for the implementation runtime."],
                importance_score=0.95,
            )
        return None

    def _extract_source_of_truth(self, text: str, lower: str) -> MemoryCandidate | None:
        if "markdown" in lower and ("source of truth" in lower or "正本" in text or "真実源" in text):
            return MemoryCandidate(
                memory_id="markdown-source-of-truth",
                title="Markdown Source of Truth",
                kind=MemoryKind.DECISION,
                summary="Markdown is the source of truth for persisted memory.",
                subject="source_of_truth",
                value="markdown",
                category="project",
                tags=["architecture", "markdown", "source-of-truth"],
                details=["Derived indexes must remain rebuildable from Markdown."],
                importance_score=0.95,
            )
        return None

    def _extract_cloud_constraint(self, text: str, lower: str) -> MemoryCandidate | None:
        if "クラウド" in text and ("依存" in text or "使わない" in text or "なし" in text):
            return MemoryCandidate(
                memory_id="no-cloud-dependency",
                title="No Cloud Dependency",
                kind=MemoryKind.CONSTRAINT,
                summary="The memory engine must not depend on cloud services.",
                subject="cloud_dependency",
                value="forbidden",
                category="project",
                tags=["architecture", "offline", "cloud"],
                details=["The engine is local-first and offline-first."],
                importance_score=0.9,
            )
        return None

    def _extract_single_user_fact(self, text: str, lower: str) -> MemoryCandidate | None:
        if "単一ユーザー" in text or "single user" in lower:
            return MemoryCandidate(
                memory_id="single-user-scope",
                title="Single User Scope",
                kind=MemoryKind.FACT,
                summary="The memory engine is designed for a single user.",
                subject="user_scope",
                value="single-user",
                category="reference",
                tags=["single-user", "scope"],
                details=["The project does not target multi-user support."],
                importance_score=0.8,
            )
        return None

    def _extract_open_question(self, text: str, lower: str) -> MemoryCandidate | None:
        if any(marker in text for marker in ("未定", "あとで決める", "検討")) or "?" in text:
            summary = text.strip()
            return MemoryCandidate(
                memory_id=f"open-question-{slugify(summary)[:48]}",
                title="Open Question",
                kind=MemoryKind.OPEN_QUESTION,
                summary=summary,
                subject="open_question",
                category="work-context",
                tags=["open-question"],
                details=["This item still needs a decision."],
                importance_score=0.6,
            )
        return None

    def _extract_task_context(self, text: str, lower: str) -> MemoryCandidate | None:
        if any(marker in text for marker in ("次に", "次は", "これから")) or "next" in lower:
            summary = text.strip()
            return MemoryCandidate(
                memory_id=f"task-context-{slugify(summary)[:48]}",
                title="Task Context",
                kind=MemoryKind.TASK_CONTEXT,
                summary=summary,
                subject="task_context",
                category="work-context",
                tags=["task-context"],
                details=["Captured from the current implementation flow."],
                importance_score=0.55,
            )
        return None

    def _extract_preference(self, text: str, lower: str) -> MemoryCandidate | None:
        if any(marker in text for marker in ("したい", "好み")) or "prefer" in lower:
            summary = text.strip()
            return MemoryCandidate(
                memory_id=f"preference-{slugify(summary)[:48]}",
                title="Preference",
                kind=MemoryKind.PREFERENCE,
                summary=summary,
                subject="user_preference",
                category="user-profile",
                tags=["preference"],
                importance_score=0.65,
            )
        return None

    def _extract_decision(self, text: str, lower: str) -> MemoryCandidate | None:
        if any(marker in text for marker in ("にする", "方針", "決定")):
            summary = text.strip()
            return MemoryCandidate(
                memory_id=f"decision-{slugify(summary)[:48]}",
                title="Decision",
                kind=MemoryKind.DECISION,
                summary=summary,
                subject="decision",
                category="general",
                tags=["decision"],
                importance_score=0.7,
            )
        return None

    def _extract_fact(self, text: str, lower: str) -> MemoryCandidate | None:
        if not any(marker in lower for marker in ("local-first", "offline-first", "git friendly", "human editable")):
            return None
        if any(marker in text for marker in ("です", "である")) or " is " in f" {lower} ":
            summary = text.strip()
            return MemoryCandidate(
                memory_id=f"fact-{slugify(summary)[:48]}",
                title="Fact",
                kind=MemoryKind.FACT,
                summary=summary,
                subject="fact",
                category="reference",
                tags=["fact"],
                importance_score=0.5,
            )
        return None

    def _dedupe(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        unique: dict[str, MemoryCandidate] = {}
        for candidate in candidates:
            unique[candidate.memory_id] = candidate
        return list(unique.values())

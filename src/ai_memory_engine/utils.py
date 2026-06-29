from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "memory") -> str:
    normalized = re.sub(r"[^\w\s-]", " ", value.lower(), flags=re.UNICODE)
    slug = re.sub(r"[-\s]+", "-", normalized).strip("-")
    return slug or fallback


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+|[\u3040-\u30ff\u3400-\u9fff]+", text.lower())


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?\.])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def normalize_value(value: str) -> str:
    lowered = value.strip().lower()
    aliases = {
        "python3": "python",
        "py": "python",
        "node": "nodejs",
        "node.js": "nodejs",
        "typescript": "typescript",
        "ts": "typescript",
    }
    return aliases.get(lowered, lowered)


def jaccard_overlap(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set.intersection(right_set))
    union = len(left_set.union(right_set))
    return intersection / union if union else 0.0


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(v * v for v in left))
    right_norm = math.sqrt(sum(v * v for v in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

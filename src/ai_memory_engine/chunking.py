from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .models import DocumentChunk
from .utils import stable_hash, tokenize


def split_markdown_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    in_code_block = False

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append("\n".join(current).strip())
            current = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            current.append(line)
            in_code_block = not in_code_block
            if not in_code_block:
                flush()
            continue
        if in_code_block:
            current.append(line)
            continue
        if stripped.startswith("#"):
            flush()
            current.append(line)
            continue
        if stripped.startswith(("- ", "* ", "+ ")) or _is_numbered_list_item(stripped):
            if current and not _is_list_block(current):
                flush()
            current.append(line)
            continue
        if not stripped:
            flush()
            continue
        current.append(line)
    flush()
    return [block for block in blocks if block]


def chunk_markdown(
    path: Path,
    memory_id: str,
    text: str,
    min_tokens: int = 300,
    max_tokens: int = 800,
    overlap_tokens: int = 50,
) -> list[DocumentChunk]:
    blocks = split_markdown_blocks(text)
    chunks: list[DocumentChunk] = []
    current: list[str] = []
    current_tokens = 0
    previous_overlap = ""
    occurrences: dict[str, int] = defaultdict(int)

    def flush() -> None:
        nonlocal current, current_tokens, previous_overlap
        if not current:
            return
        chunk_text = "\n\n".join(current).strip()
        chunk_hash = stable_hash(chunk_text)
        occurrence = occurrences[chunk_hash]
        occurrences[chunk_hash] += 1
        chunks.append(
            DocumentChunk(
                chunk_id=f"{memory_id}:{chunk_hash[:16]}:{occurrence}",
                memory_id=memory_id,
                path=str(path),
                text=chunk_text,
                chunk_hash=chunk_hash,
                metadata={"path": str(path), "memory_id": memory_id},
            )
        )
        previous_overlap = _tail_overlap(chunk_text, overlap_tokens)
        current = []
        current_tokens = 0

    for block in blocks:
        for piece in _split_large_block(block, max_tokens):
            piece_tokens = max(1, len(tokenize(piece)))
            if current and current_tokens + piece_tokens > max_tokens and current_tokens >= min_tokens:
                flush()
                if previous_overlap:
                    current = [f"_Overlap context_: {previous_overlap}"]
                    current_tokens = len(tokenize(previous_overlap))
            current.append(piece)
            current_tokens += piece_tokens
            if current_tokens >= max_tokens:
                flush()
                if previous_overlap:
                    current = [f"_Overlap context_: {previous_overlap}"]
                    current_tokens = len(tokenize(previous_overlap))
    flush()
    return chunks


def _is_numbered_list_item(line: str) -> bool:
    head, _, _ = line.partition(".")
    return bool(head) and head.isdigit()


def _is_list_block(lines: list[str]) -> bool:
    material = [line.strip() for line in lines if line.strip()]
    return bool(material) and all(
        line.startswith(("- ", "* ", "+ ")) or _is_numbered_list_item(line) for line in material
    )


def _split_large_block(block: str, max_tokens: int) -> list[str]:
    if len(tokenize(block)) <= max_tokens:
        return [block]
    words = block.split()
    segments: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for word in words:
        word_tokens = max(1, len(tokenize(word)))
        if current and current_tokens + word_tokens > max_tokens:
            segments.append(" ".join(current))
            current = []
            current_tokens = 0
        current.append(word)
        current_tokens += word_tokens
    if current:
        segments.append(" ".join(current))
    return segments or [block]


def _tail_overlap(text: str, overlap_tokens: int) -> str:
    tokens = tokenize(text)
    return " ".join(tokens[-overlap_tokens:]) if tokens else ""

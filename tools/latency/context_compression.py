"""Context compression for long prompts: summarization, deduplication, token budgeting.

Stdlib-only: uses simple heuristics (frequency, position, structure) for
compression. No external ML dependencies. Designed for prompt optimization
before sending to free-tier models with context limits.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompressionConfig:
    """Configuration for context compression."""

    target_tokens: int = 4000
    min_chunk_tokens: int = 50
    preserve_headers: bool = True
    preserve_code_blocks: bool = True
    deduplicate_threshold: float = 0.85


@dataclass(frozen=True)
class CompressionResult:
    """Result of compression operation."""

    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    content: str
    removed_sections: list[str]


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/code."""
    return max(1, len(text) // 4)


def split_into_chunks(text: str, config: CompressionConfig) -> list[tuple[str, str]]:
    """Split text into (type, content) chunks: header, code, paragraph."""
    chunks: list[tuple[str, str]] = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        # Code block
        if line.lstrip().startswith("```"):
            start = i
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                i += 1
            if i < len(lines):
                i += 1
            chunks.append(("code", "".join(lines[start:i])))
        # Header
        elif line.lstrip().startswith("#"):
            start = i
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith("#"):
                i += 1
            chunks.append(("header", "".join(lines[start:i])))
        # Paragraph
        else:
            start = i
            while i < len(lines) and not (
                lines[i].lstrip().startswith("```") or lines[i].lstrip().startswith("#")
            ):
                i += 1
            chunk_text = "".join(lines[start:i]).strip()
            if chunk_text:
                chunks.append(("paragraph", chunk_text))
    return chunks


def chunk_similarity(a: str, b: str) -> float:
    """Jaccard similarity of word sets."""
    words_a = set(re.findall(r"\w+", a.lower()))
    words_b = set(re.findall(r"\w+", b.lower()))
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def deduplicate_chunks(chunks: list[tuple[str, str]], threshold: float) -> list[tuple[str, str]]:
    """Remove near-duplicate chunks of same type."""
    if len(chunks) <= 1:
        return chunks
    kept: list[tuple[str, str]] = []
    for typ, content in chunks:
        is_dup = False
        for kept_typ, kept_content in kept:
            if kept_typ == typ and chunk_similarity(content, kept_content) >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append((typ, content))
    return kept


def score_chunk(typ: str, content: str, position: int, total: int) -> float:
    """Score chunk importance: headers > code > early paragraphs > late paragraphs."""
    base = {"header": 1.0, "code": 0.9, "paragraph": 0.5}.get(typ, 0.3)
    # Position bonus: earlier chunks slightly more important
    pos_bonus = 0.1 * (1.0 - position / max(1, total))
    # Length penalty for very long paragraphs
    length_penalty = min(0.2, len(content) / 10000.0)
    return base + pos_bonus - length_penalty


def compress_context(text: str, config: CompressionConfig | None = None) -> CompressionResult:
    """Compress context to fit token budget."""
    config = config or CompressionConfig()
    original_tokens = estimate_tokens(text)

    if original_tokens <= config.target_tokens:
        return CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=original_tokens,
            compression_ratio=1.0,
            content=text,
            removed_sections=[],
        )

    chunks = split_into_chunks(text, config)
    chunks = deduplicate_chunks(chunks, config.deduplicate_threshold)

    # Score and sort by importance
    scored = [(score_chunk(t, c, i, len(chunks)), t, c) for i, (t, c) in enumerate(chunks)]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Select chunks until token budget
    selected: list[tuple[str, str]] = []
    current_tokens = 0
    removed: list[str] = []

    for score, typ, content in scored:
        chunk_tokens = estimate_tokens(content)
        if current_tokens + chunk_tokens <= config.target_tokens:
            selected.append((typ, content))
            current_tokens += chunk_tokens
        else:
            removed.append(f"{typ}:{content[:50]}...")

    # Restore original order for selected chunks
    selected_set = set(selected)
    ordered = [(t, c) for t, c in chunks if (t, c) in selected_set]

    compressed = "\n\n".join(c for _, c in ordered)
    compressed_tokens = estimate_tokens(compressed)

    return CompressionResult(
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        compression_ratio=compressed_tokens / max(1, original_tokens),
        content=compressed,
        removed_sections=removed,
    )


def compress_messages(
    messages: list[dict[str, str]],
    config: CompressionConfig | None = None,
    system_prompt: str | None = None,
) -> list[dict[str, str]]:
    """Compress a message list (OpenAI format) to token budget."""
    config = config or CompressionConfig()
    # Reserve tokens for system prompt
    reserved = estimate_tokens(system_prompt) if system_prompt else 0
    available = config.target_tokens - reserved

    if available <= 0:
        return [{"role": "system", "content": system_prompt or ""}] if system_prompt else []

    # Build text from messages (excluding system)
    text_parts = []
    for msg in messages:
        if msg.get("role") != "system":
            text_parts.append(f"[{msg['role']}] {msg.get('content', '')}")
    full_text = "\n\n".join(text_parts)

    result = compress_context(full_text, CompressionConfig(target_tokens=available, **{
        k: v for k, v in config.__dict__.items() if k != "target_tokens"
    }))

    # Reconstruct messages (simplified: single compressed user message)
    compressed_messages = []
    if system_prompt:
        compressed_messages.append({"role": "system", "content": system_prompt})
    compressed_messages.append({"role": "user", "content": result.content})
    return compressed_messages
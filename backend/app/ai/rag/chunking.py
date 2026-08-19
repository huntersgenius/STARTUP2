"""Header-aware semantic chunking.

Clinical protocols are structured documents: a dose belongs to the heading it
sits under. Chunking that splits on token count alone strips that context and
produces citations a clinician cannot verify. Every chunk therefore carries
its heading path, and headings are never split across chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Chunk sizing, in approximate tokens (see `estimate_tokens`).
#:
#: The spec asks for 400-800 token chunks, which suits long PDF protocols. A
#: hard 400-token floor, however, forces unrelated sections together — "Choice
#: of drug" merged into "When to start treatment" — and measurably hurts both
#: retrieval precision and citation quality, because the cited section no
#: longer names the advice. So MAX_TOKENS is a real ceiling, TARGET_TOKENS is
#: what long prose aims for, and MIN_TOKENS only prevents a stray one-line
#: fragment from being retrievable on its own. See docs/adr/0003.
MIN_TOKENS = 60
TARGET_TOKENS = 500
MAX_TOKENS = 800

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass
class Chunk:
    text: str
    section: str
    index: int
    token_count: int
    metadata: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Rough token count that does not need a tokenizer on an edge device.

    Uzbek and Russian are more token-dense than English under BPE, so the
    0.75 words-per-token rule of thumb is adjusted down deliberately: it is
    better to under-fill a chunk than to blow a context window in a clinic.
    """
    words = len(text.split())
    return int(words / 0.6) + 1


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the small YAML subset used by the corpus (no PyYAML dependency)."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text

    meta: dict = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, raw = line.partition(":")
        key, raw = key.strip(), raw.strip()
        if not key:
            continue
        if raw.startswith("[") and raw.endswith("]"):
            meta[key] = [v.strip() for v in raw[1:-1].split(",") if v.strip()]
        else:
            meta[key] = raw.strip("\"'")
    return meta, text[match.end() :]


def chunk_markdown(text: str) -> list[Chunk]:
    """Split markdown into header-aware chunks of roughly TARGET_TOKENS."""
    _, body = parse_frontmatter(text)

    heading_stack: list[str] = []
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_section = ""

    def flush() -> None:
        nonlocal buffer, buffer_section
        content = "\n".join(buffer).strip()
        buffer = []
        if not content:
            return
        tokens = estimate_tokens(content)
        # A very short trailing section is appended to the previous chunk
        # rather than emitted alone, where it would retrieve without context.
        if chunks and tokens < MIN_TOKENS:
            previous = chunks[-1]
            merged = f"{previous.text}\n\n{content}"
            chunks[-1] = Chunk(
                text=merged,
                section=previous.section,
                index=previous.index,
                token_count=estimate_tokens(merged),
                metadata=previous.metadata,
            )
            return
        chunks.append(
            Chunk(text=content, section=buffer_section, index=len(chunks), token_count=tokens)
        )

    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            buffer_section = " > ".join(heading_stack)
            buffer = [line]
            continue

        buffer.append(line)
        if estimate_tokens("\n".join(buffer)) >= TARGET_TOKENS:
            # Split at a paragraph boundary so a dose is not cut in half.
            joined = "\n".join(buffer)
            split_at = joined.rfind("\n\n")
            if split_at > 0 and estimate_tokens(joined[:split_at]) >= MIN_TOKENS:
                head, tail = joined[:split_at], joined[split_at:]
                buffer = [head]
                flush()
                buffer = [tail.lstrip("\n")]
            else:
                flush()

    flush()
    return chunks

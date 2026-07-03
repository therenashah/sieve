"""Lexical retrieval over `kb_documents`: term-frequency cosine similarity.

No embedding API required — the knowledge base is a handful of company docs,
so simple TF-cosine over whitespace/punctuation-tokenized text is plenty
accurate and keeps the whole stack dependent on nothing but the Anthropic
chat API.
"""

import json
import math
import re

from app.config import get_settings
from app.db import get_db

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "if", "of", "to", "in", "on", "for", "with", "as",
    "at", "by", "from", "this", "that", "it", "its", "we", "you", "i",
    "do", "does", "did", "can", "will", "would", "should", "could",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _term_freqs(text: str) -> dict[str, int]:
    freqs: dict[str, int] = {}
    for token in tokenize(text):
        freqs[token] = freqs.get(token, 0) + 1
    return freqs


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    shared = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve(query: str, top_k: int | None = None) -> str:
    """Return the top-k most relevant knowledge base chunks for `query`, concatenated."""
    settings = get_settings()
    top_k = top_k or settings.rag_top_k

    with get_db() as conn:
        rows = conn.execute("SELECT filename, content, term_freqs FROM kb_documents").fetchall()

    if not rows:
        return ""

    query_freqs = _term_freqs(query)
    scored = sorted(
        (
            (_cosine(query_freqs, json.loads(row["term_freqs"])), row["filename"], row["content"])
            for row in rows
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    top = [item for item in scored[:top_k] if item[0] > 0]
    return "\n\n---\n\n".join(f"[{filename}]\n{content}" for _, filename, content in top)

"""Chunk every doc in the knowledge base dir and index it into `kb_documents`
for lexical retrieval (term-frequency vectors, no embedding API involved).

Run via `python scripts/ingest_kb.py`, or let it run automatically on startup
if a file hasn't been indexed yet.
"""

import json
from pathlib import Path

from app.config import get_settings
from app.db import get_db
from app.rag.retriever import tokenize

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
SUPPORTED_EXTENSIONS = {".md", ".txt"}


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return [c.strip() for c in chunks if c.strip()]


def _term_freqs(text: str) -> dict[str, int]:
    freqs: dict[str, int] = {}
    for token in tokenize(text):
        freqs[token] = freqs.get(token, 0) + 1
    return freqs


def ingest_knowledge_base(force: bool = False) -> int:
    """Index every file under `knowledge_base_dir` that hasn't been indexed yet.

    Returns the number of chunks indexed. Silently no-ops if the directory
    doesn't exist yet (nothing uploaded there).
    """
    settings = get_settings()
    kb_dir = Path(settings.knowledge_base_dir)
    if not kb_dir.exists():
        return 0

    indexed = 0
    with get_db() as conn:
        if force:
            conn.execute("DELETE FROM kb_documents")
            conn.commit()

        for path in sorted(kb_dir.glob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            already_done = conn.execute(
                "SELECT COUNT(*) AS c FROM kb_documents WHERE filename = ?", (path.name,)
            ).fetchone()["c"]
            if already_done and not force:
                continue

            for index, chunk in enumerate(_chunk_text(path.read_text(encoding="utf-8"))):
                conn.execute(
                    """INSERT INTO kb_documents (filename, chunk_index, content, term_freqs)
                       VALUES (?, ?, ?, ?)""",
                    (path.name, index, chunk, json.dumps(_term_freqs(chunk))),
                )
                indexed += 1
            conn.commit()

    return indexed

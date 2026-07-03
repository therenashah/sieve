#!/usr/bin/env python3
"""CLI: index every doc in data/knowledge_base/ into the kb_documents table
(lexical term-frequency index — no external API needed).

Usage (from backend/):
    python scripts/ingest_kb.py           # skip already-indexed files
    python scripts/ingest_kb.py --force   # re-index everything
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_db  # noqa: E402
from app.rag.ingest import ingest_knowledge_base  # noqa: E402

if __name__ == "__main__":
    init_db()
    count = ingest_knowledge_base(force="--force" in sys.argv)
    print(f"Indexed {count} chunk(s) into kb_documents.")

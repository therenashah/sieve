#!/usr/bin/env python3
"""Manual test for rubric generation, run directly against the real Bedrock
endpoint (no mocking) — since no HTTP route calls generate_rubric yet, this
imports and calls the pipeline function in-process.

Usage (from the backend/ directory, with dependencies installed):

    python scripts/test_rubric_cli.py path/to/job_description.txt

Requires working AWS Bedrock access: either run this on the EC2 instance
(IAM role resolves automatically), or set AWS_ACCESS_KEY_ID/
AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN (and AWS_REGION if not ap-south-1)
in backend/.env or the environment before running.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.rubric import generate_rubric  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jd_file", help="Path to a plain-text job description file")
    args = parser.parse_args()

    jd_text = Path(args.jd_file).read_text(encoding="utf-8")
    print(f"Loaded JD ({len(jd_text)} chars). Calling generate_rubric — this hits the real model...\n")

    try:
        rubric = await generate_rubric(jd_text)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"version={rubric.version}, {len(rubric.criteria)} criteria, "
          f"weights sum to {sum(c.weight for c in rubric.criteria):.4f}\n")
    for c in sorted(rubric.criteria, key=lambda c: -c.weight):
        print(f"  [{c.id}] {c.name}  (weight={c.weight:.3f})")
        print(f"      {c.description}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

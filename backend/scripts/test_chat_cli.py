#!/usr/bin/env python3
"""End-to-end manual test for the HR screening chatbot, driven over HTTP
against a running backend (so it exercises the real API layer, not just the
engine functions directly).

Usage (from anywhere, with the backend running — e.g. `docker compose up` or
`uvicorn app.main:app --reload` from backend/):

    python backend/scripts/test_chat_cli.py                        # candidate 1: Priya Nair (gate PASSED, has a flagged gap)
    python backend/scripts/test_chat_cli.py --candidate-id 2        # Rahul Verma (gate PASSED, clean profile)
    python backend/scripts/test_chat_cli.py --candidate-id 3        # Karan Mehta (gate REJECTED — expect a 400)
    python backend/scripts/test_chat_cli.py --base-url http://localhost:8000

Requires the backend to have working AWS Bedrock access (either via an EC2
instance role, or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN
in the environment) — the chat won't produce replies otherwise. Type your
answers at the prompt; type /quit to exit early.
"""

import argparse
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--job-id", type=int, default=1)
    parser.add_argument("--candidate-id", type=int, default=1)
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=60)

    print(f"Triggering screening link for job={args.job_id} candidate={args.candidate_id} ...")
    response = client.post(f"/api/jobs/{args.job_id}/candidates/{args.candidate_id}/screening-link")
    if response.status_code != 200:
        print(f"Failed to create screening session: {response.status_code} {response.text}")
        return 1
    link = response.json()
    token = link["token"]
    print(f"Chat URL: {link['chat_url']}  (expires at {link['expires_at']})")
    print("-" * 60)

    response = client.post(f"/api/chat/{token}/start")
    _print_turn(response)

    while True:
        turn = response.json()
        if turn["session_status"] != "active":
            print("\n[session ended]")
            break

        try:
            user_input = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[exiting]")
            break

        if user_input in {"/quit", "/exit"}:
            print("[exiting]")
            break
        if not user_input:
            continue

        response = client.post(f"/api/chat/{token}/message", json={"message": user_input})
        _print_turn(response)

    return 0


def _print_turn(response: httpx.Response) -> None:
    if response.status_code != 200:
        print(f"[error] {response.status_code} {response.text}")
        return
    turn = response.json()
    for message in turn["messages"]:
        print(f"\naria> {message['content']}")


if __name__ == "__main__":
    sys.exit(main())

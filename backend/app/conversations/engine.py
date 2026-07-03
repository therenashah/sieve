"""Chat session lifecycle: creation, message handling, timeboxing.

Shared by both screening (3.5) and L1 (3.6) modes — mode-specific behavior
comes from the config passed in from screening.py / l1.py.
"""


def create_session(candidate_id: str, mode: str) -> dict:
    raise NotImplementedError


def get_session(token: str) -> dict:
    raise NotImplementedError


async def handle_message(token: str, message: str) -> dict:
    raise NotImplementedError


def is_expired(session: dict) -> bool:
    raise NotImplementedError

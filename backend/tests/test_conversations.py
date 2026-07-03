import pytest

from app.conversations import engine


def test_get_session_not_implemented():
    with pytest.raises(NotImplementedError):
        engine.get_session("dummy-token")

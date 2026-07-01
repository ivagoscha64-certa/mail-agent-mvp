from __future__ import annotations

import pytest
from googleapiclient.errors import HttpError

from mail_agent.mail.gmail_api import _execute_with_retry


class FakeRequest:
    def __init__(self, *results):
        self.calls = 0
        self._results = list(results)

    def execute(self):
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeResponse:
    def __init__(self, status: int, reason: str = "error") -> None:
        self.status = status
        self.reason = reason


def test_execute_with_retry_returns_after_transient_timeout() -> None:
    sleeps: list[float] = []
    request = FakeRequest(TimeoutError("timed out"), {"messages": [{"id": "1"}]})

    result = _execute_with_retry(request, sleep=sleeps.append)

    assert result == {"messages": [{"id": "1"}]}
    assert request.calls == 2
    assert sleeps == [0.5]


def test_execute_with_retry_raises_after_max_transient_attempts() -> None:
    sleeps: list[float] = []
    error = ConnectionResetError("connection reset")
    request = FakeRequest(error, error, error)

    with pytest.raises(ConnectionResetError) as exc_info:
        _execute_with_retry(request, sleep=sleeps.append)

    assert exc_info.value is error
    assert request.calls == 3
    assert sleeps == [0.5, 1.0]


def test_execute_with_retry_does_not_retry_non_transient_http_error() -> None:
    sleeps: list[float] = []
    error = HttpError(FakeResponse(400, "bad request"), b"bad request")
    request = FakeRequest(error, {"messages": []})

    with pytest.raises(HttpError) as exc_info:
        _execute_with_retry(request, sleep=sleeps.append)

    assert exc_info.value is error
    assert request.calls == 1
    assert sleeps == []

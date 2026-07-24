from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
import requests

from media_catalog_builder.http import RetryingHttpClient


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = dict(payload or {})
        self.headers = dict(headers or {})

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}",
                response=self,  # type: ignore[arg-type]
            )


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.responses.pop(0)


def make_client(session: FakeSession, sleeps: list[float]) -> RetryingHttpClient:
    return RetryingHttpClient(
        session=session,  # type: ignore[arg-type]
        user_agent="MediaOrganizerCatalog/Test",
        timeout_seconds=10,
        request_interval_seconds=0,
        request_retries=3,
        sleep=sleeps.append,
        monotonic=lambda: 100.0,
    )


def test_http_retries_503_then_returns_json():
    sleeps: list[float] = []
    session = FakeSession([FakeResponse(503), FakeResponse(200, {"ok": True})])

    result = make_client(session, sleeps).get_json("https://example.test", {"q": "x"})

    assert result == {"ok": True}
    assert len(session.calls) == 2
    assert sleeps == [1.0]


def test_post_json_uses_form_data_and_retries_504():
    sleeps: list[float] = []
    session = FakeSession([FakeResponse(504), FakeResponse(200, {"ok": True})])

    result = make_client(session, sleeps).post_json(
        "https://example.test",
        {"query": "SELECT * WHERE {}", "format": "json"},
    )

    assert result == {"ok": True}
    assert [call["method"] for call in session.calls] == ["POST", "POST"]
    assert session.calls[0]["data"]["format"] == "json"
    assert "params" not in session.calls[0]
    assert sleeps == [1.0]


def test_http_respects_retry_after_for_429():
    sleeps: list[float] = []
    session = FakeSession(
        [
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(200, {"ok": True}),
        ]
    )

    make_client(session, sleeps).get_json("https://example.test", {})

    assert sleeps == [7.0]


def test_http_does_not_retry_404():
    sleeps: list[float] = []
    session = FakeSession([FakeResponse(404)])

    with pytest.raises(requests.HTTPError):
        make_client(session, sleeps).get_json("https://example.test", {})

    assert len(session.calls) == 1
    assert sleeps == []


def test_http_sets_user_agent_accept_and_timeout():
    sleeps: list[float] = []
    session = FakeSession([FakeResponse(200, {"ok": True})])

    make_client(session, sleeps).get_json("https://example.test", {"q": "x"})

    assert session.headers["User-Agent"] == "MediaOrganizerCatalog/Test"
    assert session.headers["Accept"] == "application/sparql-results+json"
    assert session.calls[0]["timeout"] == 10

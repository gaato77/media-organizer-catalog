from __future__ import annotations

import time
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Protocol, cast

import requests

_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 30.0


class ResponseLike(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> object: ...

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    headers: MutableMapping[str, str]

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


class RetryingHttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float,
        request_interval_seconds: float,
        request_retries: int,
        session: SessionLike | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        if request_retries < 1:
            raise ValueError("request_retries must be positive")

        self._session = session or cast(SessionLike, requests.Session())
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/sparql-results+json",
            }
        )
        self._timeout_seconds = timeout_seconds
        self._request_interval_seconds = request_interval_seconds
        self._request_retries = request_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_started: float | None = None

    def _wait_for_request_slot(self) -> None:
        if self._last_request_started is None:
            return
        elapsed = self._monotonic() - self._last_request_started
        remaining = self._request_interval_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    @staticmethod
    def _retry_delay(response: ResponseLike | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        return min(float(2**attempt), _MAX_BACKOFF_SECONDS)

    def get_json(self, url: str, params: Mapping[str, str]) -> dict[str, Any]:
        for attempt in range(self._request_retries):
            self._wait_for_request_slot()
            self._last_request_started = self._monotonic()
            response: ResponseLike | None = None
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._timeout_seconds,
                )
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt + 1 == self._request_retries:
                        response.raise_for_status()
                    self._sleep(self._retry_delay(response, attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("HTTP response must contain a JSON object")
                return cast(dict[str, Any], payload)
            except (requests.ConnectionError, requests.Timeout):
                if attempt + 1 == self._request_retries:
                    raise
                self._sleep(self._retry_delay(response, attempt))

        raise RuntimeError("HTTP retry loop ended unexpectedly")

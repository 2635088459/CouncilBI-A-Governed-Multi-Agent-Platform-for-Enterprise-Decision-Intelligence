"""HTTP JSON transport for the frontend Backend API client.

The frontend API client works against a small JsonTransport protocol. This
module provides the real HTTP implementation for browser/server-side usage.
Tests can still plug in an in-process transport without changing app logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpResponseReader(Protocol):
    def read(self) -> bytes:
        """Read response bytes."""
        ...


class UrlOpener(Protocol):
    def __call__(self, request: Request, timeout: float) -> HttpResponseReader:
        """Open a prepared request."""
        ...


@dataclass(frozen=True, slots=True)
class HttpJsonTransport:
    base_url: str
    timeout_seconds: float = 8.0
    opener: UrlOpener | None = None

    def post_json(
        self,
        path: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        request = Request(
            url=self._url(path=path, query=query),
            data=json.dumps(body).encode("utf-8"),
            headers={
                **headers,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._open_json(request)

    def get_json(
        self,
        path: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        request = Request(
            url=self._url(path=path, query=query),
            headers={**headers, "Accept": "application/json"},
            method="GET",
        )
        return self._open_json(request)

    def _url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        if not path.startswith("/"):
            raise ValueError("HTTP transport path must start with '/'.")

        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            return f"{url}?{urlencode(query)}"
        return url

    def _open_json(self, request: Request) -> Mapping[str, Any]:
        opener = self.opener or cast(UrlOpener, urlopen)
        try:
            response = opener(request, timeout=self.timeout_seconds)
            return _decode_json_object(response.read())
        except HTTPError as exc:
            body = exc.read()
            if body:
                return _decode_json_object(body)
            raise ValueError(f"Backend API HTTP error: {exc.code}") from exc
        except URLError as exc:
            raise ValueError(f"Backend API network error: {exc.reason}") from exc


def _decode_json_object(body: bytes) -> Mapping[str, Any]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Backend API response was not valid JSON.") from exc

    if not isinstance(decoded, Mapping):
        raise ValueError("Backend API response JSON must be an object.")
    return cast(Mapping[str, Any], decoded)

"""Fixture-backed JSON transport for frontend tests.

This transport implements the same small protocol as the real HTTP transport,
but it serves typed API fixtures from memory. That lets the frontend exercise
``FrontendApiClient`` without a running backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from chatbi.frontend.api_fixtures import (
    FrontendApiFixture,
    JsonObject,
    all_frontend_api_fixtures,
)


@dataclass(frozen=True, slots=True)
class FixtureRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    query: Mapping[str, str] | None
    body: Mapping[str, Any] | None = None


class FixtureJsonTransport:
    """Serve frontend API fixtures through the JsonTransport interface."""

    def __init__(
        self,
        fixtures: tuple[FrontendApiFixture, ...] | None = None,
    ) -> None:
        self._fixtures = fixtures or all_frontend_api_fixtures()
        self._last_request: FixtureRequest | None = None

    @property
    def last_request(self) -> FixtureRequest | None:
        return self._last_request

    def post_json(
        self,
        path: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        query: Mapping[str, str] | None = None,
    ) -> JsonObject:
        self._last_request = FixtureRequest(
            method="POST",
            path=path,
            headers=headers,
            query=query,
            body=body,
        )
        return self._response_for(method="POST", path=path)

    def get_json(
        self,
        path: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> JsonObject:
        self._last_request = FixtureRequest(
            method="GET",
            path=path,
            headers=headers,
            query=query,
        )
        return self._response_for(method="GET", path=path)

    def _response_for(self, method: str, path: str) -> JsonObject:
        for fixture in self._fixtures:
            if fixture.method == method and fixture.path == path:
                return fixture.response
        raise ValueError(f"No frontend API fixture for {method} {path}")

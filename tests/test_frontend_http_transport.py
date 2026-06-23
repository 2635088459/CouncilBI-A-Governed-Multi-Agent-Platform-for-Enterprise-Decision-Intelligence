import json
from urllib.request import Request

import pytest

from chatbi.frontend.http_transport import HttpJsonTransport


class FakeResponse:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, body: object) -> None:
        self.body = body
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeResponse(self.body)


def test_post_json_sends_json_body_headers_and_query() -> None:
    opener = FakeOpener({"code": 0, "data": {"ok": True}})
    transport = HttpJsonTransport(
        base_url="http://localhost:8000/",
        timeout_seconds=3.0,
        opener=opener,
    )

    response = transport.post_json(
        path="/api/v1/chat/query",
        headers={"Authorization": "Bearer token", "X-Trace-Id": "trc_001"},
        query={"user_id": "u_001"},
        body={"question": "Show revenue trend."},
    )

    request = opener.requests[0]
    assert response["code"] == 0
    assert request.full_url == "http://localhost:8000/api/v1/chat/query?user_id=u_001"
    assert request.get_method() == "POST"
    assert request.data == b'{"question": "Show revenue trend."}'
    assert dict(request.header_items())["Authorization"] == "Bearer token"
    assert dict(request.header_items())["Content-type"] == "application/json"
    assert opener.timeouts == [3.0]


def test_get_json_sends_query_and_accept_header() -> None:
    opener = FakeOpener({"code": 0, "data": {"items": []}})
    transport = HttpJsonTransport(
        base_url="http://localhost:8000",
        opener=opener,
    )

    response = transport.get_json(
        path="/api/v1/chat/history",
        headers={"Authorization": "Bearer token"},
        query={"user_id": "u_001", "page_size": "20"},
    )

    request = opener.requests[0]
    assert response["data"] == {"items": []}
    assert request.full_url == "http://localhost:8000/api/v1/chat/history?user_id=u_001&page_size=20"
    assert request.get_method() == "GET"
    assert dict(request.header_items())["Accept"] == "application/json"


def test_transport_rejects_relative_path_without_leading_slash() -> None:
    transport = HttpJsonTransport(base_url="http://localhost:8000")

    with pytest.raises(ValueError, match="path must start"):
        transport.get_json(path="api/v1/health", headers={})


def test_transport_rejects_non_object_json_response() -> None:
    opener = FakeOpener(["not", "an", "object"])
    transport = HttpJsonTransport(
        base_url="http://localhost:8000",
        opener=opener,
    )

    with pytest.raises(ValueError, match="must be an object"):
        transport.get_json(path="/api/v1/health", headers={})

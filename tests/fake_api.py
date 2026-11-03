"""A stand-in for the World Feed Monitor REST API, as an httpx mock transport.

Responses follow the published schema: {meta, data} for searches, the documented
error bodies and headers for 401, 403, 422, 429 and 503. Article values are
placeholders, not real headlines.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

KEY, SECRET = "test-key", "test-secret"
AUTH = "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()


def article(n: int, **overrides: Any) -> dict[str, Any]:
    return {
        "uuid": f"uuid-{n}",
        "title": f"Example headline {n}",
        "url": f"https://publisher.example/articles/{n}?ref=rss&lang=ja",
        "content": f"Example summary {n}.",
        "author": None,
        "image": None,
        "published_at": "2026-11-03 09:12:00",
        "published_timezone": "Asia/Tokyo",
        "published_at_utc": "2026-11-03T00:12:00Z",
        "source": {
            "uuid": "s-1",
            "key": "example-daily-jp",
            "name": "Example Daily",
            "url": "https://publisher.example",
        },
        "country": {"uuid": "c-1", "iso_2": "JP", "iso_3": "JPN", "name": "Japan"},
        "language": {"uuid": "l-1", "name": "Japanese", "local_name": "日本語", "code": "ja", "locale": "ja_jp"},
        "categories": [],
        "macro_categories": [{"uuid": "m-1", "key": "technology", "name": "Technology"}],
        **overrides,
    }


@dataclass
class FakeApi:
    total: int = 60  # articles matching, 25 per page
    responses: list[httpx.Response] = field(default_factory=list)  # served first, in order
    requests: list[httpx.Request] = field(default_factory=list)
    network_down: bool = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.network_down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.headers.get("Authorization") != AUTH:
            return httpx.Response(401, json={"message": "Invalid credentials"})
        if self.responses:
            return self.responses.pop(0)

        if request.url.path == "/v1/feeds/search":
            page = int(request.url.params.get("page", 1))
            pages = max(1, -(-self.total // 25))
            count = max(0, min(25, self.total - (page - 1) * 25))
            data = [article((page - 1) * 25 + i + 1) for i in range(count)]
            meta = {
                "timeout": "5s",
                "total_pages": pages,
                "items_per_page": 25,
                "total_items": self.total,
                "current_page": page,
                "has_previous": page > 1,
                "has_next": page < pages,
                "applied_filters": {
                    k: v.split(",") if k in ("country", "language") else v
                    for k, v in request.url.params.items()
                    if k != "page"
                },
            }
            return httpx.Response(200, json={"meta": meta, "data": data})

        if request.url.path == "/v1/metadata/countries":
            return httpx.Response(
                200, json={"meta": {}, "data": [{"uuid": "c-1", "name": "Japan", "iso_2": "JP", "iso_3": "JPN"}]}
            )

        return httpx.Response(404, json={"message": "Not found"})


def rate_limited(window: str = "minute", retry_after: int = 24, limit: int = 30) -> httpx.Response:
    return httpx.Response(
        429,
        json={
            "message": f"You have used your plan allowance of {limit} requests per {window}.",
            "window": window,
            "limit": limit,
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"},
    )

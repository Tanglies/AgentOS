"""Bounded web cache tests (no real network access)."""

from __future__ import annotations

import httpx

from agentos.core.cache import TTLCache
from agentos.core.config import ToolsSettings
from agentos.runtime.web_tools import FetchUrlTool

PUBLIC_URL = "https://93.184.216.34/page"


def test_ttl_cache_expires_and_evicts_lru() -> None:
    now = [0.0]
    cache = TTLCache[str, str](
        ttl_seconds=10,
        max_entries=2,
        clock=lambda: now[0],
    )
    cache.set("a", "A")
    cache.set("b", "B")
    assert cache.get("a") == "A"
    cache.set("c", "C")

    assert cache.get("b") is None
    now[0] = 11
    assert cache.get("a") is None
    assert len(cache) == 1


async def test_fetch_url_uses_ttl_cache() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="hello")

    tool = FetchUrlTool(
        ToolsSettings(web_cache_enabled=True, web_cache_ttl_seconds=60),
        transport=httpx.MockTransport(handler),
    )
    first = await tool.run(PUBLIC_URL)
    second = await tool.run(PUBLIC_URL)

    assert first == second
    assert calls == 1


async def test_fetch_url_does_not_cache_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    tool = FetchUrlTool(
        ToolsSettings(web_cache_enabled=True),
        transport=httpx.MockTransport(handler),
    )
    assert "HTTP 500" in await tool.run(PUBLIC_URL)
    assert "HTTP 500" in await tool.run(PUBLIC_URL)
    assert calls == 2


async def test_fetch_url_does_not_cache_sensitive_query() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="secret")

    tool = FetchUrlTool(
        ToolsSettings(web_cache_enabled=True),
        transport=httpx.MockTransport(handler),
    )
    url = f"{PUBLIC_URL}?token=capability"
    await tool.run(url)
    await tool.run(url)
    assert calls == 2


async def test_fetch_url_does_not_cache_no_store_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "cache-control": "no-store"},
            text="private",
        )

    tool = FetchUrlTool(
        ToolsSettings(web_cache_enabled=True),
        transport=httpx.MockTransport(handler),
    )
    await tool.run(PUBLIC_URL)
    await tool.run(PUBLIC_URL)
    assert calls == 2

"""联网工具测试：SSRF 防护、HTML 转换、抓取与搜索。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from agentos.core.config import ToolsSettings
from agentos.runtime import FetchUrlTool, WebSearchTool, create_web_tools
from agentos.runtime.web_tools import _html_to_text, _is_public_host, _validate_url

# 一个真实存在的公网 IPv4，用字面量可避免测试依赖 DNS
PUBLIC_HOST_URL = "https://93.184.216.34/page"


def _settings(**overrides: Any) -> ToolsSettings:
    return ToolsSettings(**overrides)


def _fetch_tool(handler: Any, **overrides: Any) -> FetchUrlTool:
    return FetchUrlTool(_settings(**overrides), transport=httpx.MockTransport(handler))


def _search_tool(handler: Any, **overrides: Any) -> WebSearchTool:
    overrides.setdefault("web_search_api_key", SecretStr("tvly-test"))
    return WebSearchTool(_settings(**overrides), transport=httpx.MockTransport(handler))


# --- SSRF 防护 ------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # 云环境元数据地址
        "0.0.0.0",
        "::1",
    ],
)
async def test_public_host_rejects_internal_addresses(host: str) -> None:
    assert await _is_public_host(host) is False


async def test_public_host_accepts_public_address() -> None:
    assert await _is_public_host("93.184.216.34") is True


async def test_public_host_rejects_unresolvable_name() -> None:
    assert await _is_public_host("this-domain-should-not-resolve.invalid") is False


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.0.1/router",
        "http://10.1.2.3/",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http:///no-host",
    ],
)
async def test_validate_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        await _validate_url(url)


async def test_validate_url_allows_public_target() -> None:
    # 不抛异常即通过
    await _validate_url(PUBLIC_HOST_URL)


# --- HTML 转纯文本 --------------------------------------------------------


def test_html_to_text_extracts_text_and_skips_scripts() -> None:
    html = (
        "<html><head><style>body{color:red}</style></head><body>"
        "<h1>标题</h1><p>正文内容</p><script>alert(1)</script>"
        "</body></html>"
    )

    text = _html_to_text(html)

    assert "标题" in text
    assert "正文内容" in text
    assert "alert(1)" not in text
    assert "color:red" not in text


def test_html_to_text_collapses_whitespace() -> None:
    assert _html_to_text("<p>a    b</p>") == "a b"


# --- fetch_url ------------------------------------------------------------


async def test_fetch_url_converts_html_to_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body><p>Hello AgentOS</p></body></html>",
        )

    output = await _fetch_tool(handler).run(PUBLIC_HOST_URL)

    assert "Hello AgentOS" in output
    assert "<p>" not in output
    assert PUBLIC_HOST_URL in output


async def test_fetch_url_keeps_plain_text_untouched() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, text="raw text body"
        )

    assert "raw text body" in await _fetch_tool(handler).run(PUBLIC_HOST_URL)


async def test_fetch_url_blocks_metadata_endpoint_without_requesting() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, text="should never be returned")

    output = await _fetch_tool(handler).run("http://169.254.169.254/latest/meta-data/")

    assert "拒绝访问非公网地址" in output
    assert called is False


async def test_fetch_url_blocks_loopback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="nope")

    assert "拒绝访问非公网地址" in await _fetch_tool(handler).run("http://127.0.0.1:8000/")


async def test_fetch_url_rejects_unsupported_scheme() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="nope")

    assert "仅支持 http/https" in await _fetch_tool(handler).run("file:///etc/passwd")


async def test_fetch_url_reports_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="missing")

    assert "HTTP 404" in await _fetch_tool(handler).run(PUBLIC_HOST_URL)


async def test_fetch_url_follows_redirect_to_public_target() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/page":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="arrived")

    output = await _fetch_tool(handler).run(PUBLIC_HOST_URL)

    assert "arrived" in output
    assert "/final" in output


async def test_fetch_url_revalidates_redirect_target() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    output = await _fetch_tool(handler).run(PUBLIC_HOST_URL)

    assert "拒绝访问非公网地址" in output


async def test_fetch_url_truncates_large_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, text="x" * 5000
        )

    output = await _fetch_tool(handler, max_web_bytes=100, max_output_chars=1000).run(
        PUBLIC_HOST_URL
    )

    assert "已截断" in output


async def test_fetch_url_handles_empty_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="")

    assert "没有可提取的文本内容" in await _fetch_tool(handler).run(PUBLIC_HOST_URL)


# --- web_search -----------------------------------------------------------


def _tavily_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "title": "AgentOS 文档",
                "url": "https://example.com/docs",
                "content": "AgentOS 是一个企业级 Agent 平台。",
            },
            {
                "title": "第二个结果",
                "url": "https://example.com/2",
                "content": "补充说明",
            },
        ]
    }


async def test_web_search_sends_key_and_formats_results() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_tavily_payload())

    output = await _search_tool(handler).run("AgentOS 是什么")

    assert captured["authorization"] == "Bearer tvly-test"
    assert captured["body"]["query"] == "AgentOS 是什么"
    assert captured["body"]["max_results"] == 5
    assert "AgentOS 文档" in output
    assert "https://example.com/docs" in output
    assert "第二个结果" in output


async def test_web_search_honours_max_results_setting() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    await _search_tool(handler, web_search_max_results=3).run("x")

    assert captured["body"]["max_results"] == 3


async def test_web_search_reports_no_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    assert "未找到" in await _search_tool(handler).run("不存在的关键词")


async def test_web_search_reports_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    assert "HTTP 401" in await _search_tool(handler).run("x")


async def test_web_search_reports_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    assert "不是合法 JSON" in await _search_tool(handler).run("x")


async def test_web_search_handles_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    assert "请求超时" in await _search_tool(handler, web_timeout_seconds=1).run("x")


async def test_web_search_handles_missing_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{}]})

    output = await _search_tool(handler).run("x")

    assert "(无标题)" in output


# --- 工厂与密钥保护 --------------------------------------------------------


def test_create_web_tools_includes_search_only_with_key() -> None:
    assert [tool.name for tool in create_web_tools(ToolsSettings())] == ["fetch_url"]

    with_key = ToolsSettings(web_search_api_key=SecretStr("tvly-test"))
    assert [tool.name for tool in create_web_tools(with_key)] == ["fetch_url", "web_search"]


def test_web_search_spec_does_not_leak_api_key() -> None:
    settings = ToolsSettings(web_search_api_key=SecretStr("tvly-super-secret"))
    payload = json.dumps(WebSearchTool(settings).spec().to_provider_payload())

    assert "tvly-super-secret" not in payload


def test_fetch_url_spec_declares_required_url() -> None:
    spec = FetchUrlTool(ToolsSettings()).spec()

    assert spec.name == "fetch_url"
    assert spec.parameters["required"] == ["url"]
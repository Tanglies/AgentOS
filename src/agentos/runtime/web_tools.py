"""联网工具：网页抓取与联网搜索。

两个工具：

- :class:`FetchUrlTool` —— 抓取公网 http/https 页面并转换为纯文本
- :class:`WebSearchTool` —— 通过搜索 API 检索信息（需配置 API Key）

安全边界（``fetch_url`` 最容易被滥用，做了 SSRF 防护）：

- 只允许 ``http`` / ``https`` 协议
- 目标是**公网地址**才放行：回环、内网、链路本地、保留地址全部拒绝，
  包括云环境的元数据地址（``169.254.169.254``）
- 重定向逐跳重新校验，避免「先给出公网地址再 302 到内网」绕过
- 响应体有字节上限，超时也有上限

.. warning::

   DNS 解析与真正发起连接之间存在 TOCTOU 窗口，理论上可被 DNS rebinding 利用。
   对安全要求更高的场景应改用出口代理或网络层隔离。
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from agentos.core.config import ToolsSettings
from agentos.runtime.tools import Tool, truncate_text

USER_AGENT = "AgentOS/0.1 (+https://github.com/Tanglies/AgentOS)"
MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class _HtmlTextExtractor(HTMLParser):
    """把 HTML 转成纯文本：跳过脚本样式，块级标签处换行。"""

    _BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "br",
            "li",
            "tr",
            "hr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "section",
            "article",
            "header",
            "footer",
            "blockquote",
            "pre",
        }
    )
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        """返回归一化后的纯文本。"""
        raw = "".join(self._chunks)
        lines = [
            re.sub(r"[ \t\u00a0\u3000]+", " ", line).strip()
            for line in raw.splitlines()
        ]
        return "\n".join(line for line in lines if line)


def _html_to_text(payload: str) -> str:
    """把 HTML 转换为纯文本，解析失败时原样返回。"""
    parser = _HtmlTextExtractor()
    parser.feed(payload)
    parser.close()
    return parser.text()


async def _is_public_host(host: str) -> bool:
    """判断主机名是否只解析到公网地址。"""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        # is_global 对回环、内网、链路本地、保留、组播地址均为 False
        if not address.is_global:
            return False
    return True


async def _validate_url(url: str) -> None:
    """校验协议与目标地址，不通过时抛 :class:`ValueError`。"""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"仅支持 http/https，收到：{parsed.scheme or '(空)'}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL 缺少主机名")
    if not await _is_public_host(host):
        raise ValueError(f"拒绝访问非公网地址：{host}")


class FetchUrlTool(Tool):
    """抓取网页并转换为纯文本。"""

    name = "fetch_url"
    description = (
        "抓取指定的公网网页并返回纯文本内容。"
        "只支持 http/https，内网与元数据地址会被拒绝。"
        "适合读取文档、文章、API 文档等公开页面。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "完整 URL，例如 https://example.com/docs",
            }
        },
        "required": ["url"],
    }

    def __init__(
        self, settings: ToolsSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def _download(self, url: str) -> tuple[str, str, bytes, bool]:
        """下载内容，返回 (最终 URL, content-type, 字节, 是否截断)。"""
        limit = self._settings.max_web_bytes
        current = url
        headers = {"user-agent": USER_AGENT}

        async with httpx.AsyncClient(
            timeout=self._settings.web_timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await _validate_url(current)
                async with client.stream("GET", current, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("重定向缺少 Location 头")
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise ValueError(f"HTTP {response.status_code}")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= limit:
                            break
                    content_type = response.headers.get("content-type", "")
                    return current, content_type, b"".join(chunks), total >= limit

        raise ValueError(f"重定向次数超过 {MAX_REDIRECTS} 次")

    async def run(self, url: str) -> str:
        try:
            final_url, content_type, raw, truncated = await self._download(url)
        except ValueError as exc:
            return f"抓取失败：{exc}"
        except httpx.TimeoutException:
            return f"抓取失败：请求超时（>{self._settings.web_timeout_seconds:g}s）"
        except httpx.HTTPError as exc:
            return f"抓取失败：{type(exc).__name__}: {exc}"

        text = raw.decode("utf-8", errors="replace")
        if "html" in content_type.lower() or text.lstrip().startswith("<"):
            text = _html_to_text(text)

        header = f"来源：{final_url}"
        if truncated:
            header += f"（内容超过 {self._settings.max_web_bytes} 字节，已截断）"
        body = text.strip() or "(页面没有可提取的文本内容)"
        return truncate_text(f"{header}\n\n{body}", self._settings.max_output_chars)


class WebSearchTool(Tool):
    """通过搜索 API 检索信息（Tavily 兼容）。"""

    name = "web_search"
    description = (
        "联网搜索，返回与查询相关的网页标题、链接与摘要。"
        "适合需要最新信息、事实核查或查找资料链接的场景。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"}
        },
        "required": ["query"],
    }

    def __init__(
        self, settings: ToolsSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def run(self, query: str) -> str:
        api_key = self._settings.web_search_api_key
        if api_key is None:  # pragma: no cover - 未配置时不会注册该工具
            return "联网搜索未配置 API Key。"

        payload = {
            "query": query,
            "max_results": self._settings.web_search_max_results,
            "search_depth": "basic",
        }
        headers = {
            "authorization": f"Bearer {api_key.get_secret_value()}",
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.web_timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    self._settings.web_search_api_url, json=payload, headers=headers
                )
        except httpx.TimeoutException:
            return f"搜索失败：请求超时（>{self._settings.web_timeout_seconds:g}s）"
        except httpx.HTTPError as exc:
            return f"搜索失败：{type(exc).__name__}: {exc}"

        if response.status_code >= 400:
            return f"搜索失败：HTTP {response.status_code}（请检查 API Key 与额度）"

        try:
            data = response.json()
        except ValueError:
            return "搜索失败：返回内容不是合法 JSON"

        results = data.get("results") or []
        if not results:
            return f"未找到与「{query}」相关的结果"

        lines = [f"搜索「{query}」的结果（{len(results)} 条）：", ""]
        for index, item in enumerate(results, 1):
            title = str(item.get("title") or "(无标题)").strip()
            link = str(item.get("url") or "").strip()
            snippet = " ".join(str(item.get("content") or "").split())[:400]
            lines.append(f"{index}. {title}")
            if link:
                lines.append(f"   {link}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

        return truncate_text("\n".join(lines).strip(), self._settings.max_output_chars)


def create_web_tools(settings: ToolsSettings) -> list[Tool]:
    """按配置创建联网工具。

    ``fetch_url`` 始终创建；``web_search`` 仅在配置了 API Key 时创建，
    避免把不可用的能力暴露给模型。
    """
    tools: list[Tool] = [FetchUrlTool(settings)]
    if settings.web_search_api_key is not None:
        tools.append(WebSearchTool(settings))
    return tools
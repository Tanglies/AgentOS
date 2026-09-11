"""命令行入口。

用法::

    agentos serve [--host HOST] [--port PORT] [--reload]
    agentos version
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from agentos import __version__
from agentos.core.config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentos", description="AgentOS 命令行工具")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host", default=None, help="监听地址，默认取 AGENTOS_API__HOST")
    serve.add_argument("--port", type=int, default=None, help="监听端口，默认取 AGENTOS_API__PORT")
    serve.add_argument("--reload", action="store_true", help="开启热重载（仅开发环境使用）")

    subparsers.add_parser("version", help="打印版本号")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        settings = get_settings()
        uvicorn.run(
            "agentos.api.app:app",
            host=args.host or settings.api.host,
            port=args.port or settings.api.port,
            reload=bool(args.reload),
            log_level=settings.logging.level.lower(),
        )
        return 0

    if args.command == "version":
        print(__version__)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
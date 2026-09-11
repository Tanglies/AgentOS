r"""真实模型冒烟测试。

通过 AgentOS 的 LLM 抽象层调用配置中的真实模型服务，验证「配置 → 客户端 → Runtime → 结果」
整条链路，并打印耗时与 token 消耗。脚本不会打印任何密钥内容。

用法::

    .\.venv\Scripts\python.exe examples\qwen_smoke.py
    .\.venv\Scripts\python.exe examples\qwen_smoke.py --model qwen3.8-flash
    .\.venv\Scripts\python.exe examples\qwen_smoke.py --models qwen3.8-max,qwen3.7-plus
    .\.venv\Scripts\python.exe examples\qwen_smoke.py --prompt "用一句话解释什么是 Agent"

配置来自环境变量或 .env：AGENTOS_LLM__PROVIDER / MODEL / BASE_URL / API_KEY。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from urllib.parse import urlparse

from agentos.core.config import Settings, get_settings
from agentos.core.exceptions import AgentOSError
from agentos.core.logging import configure_logging
from agentos.llm.factory import create_llm_client
from agentos.runtime.agent import Agent
from agentos.runtime.runtime import AgentRuntime, RunResult

DEFAULT_PROMPTS = [
    "用一句话介绍你自己，并说明你能做什么。",
    "用 Python 写一个函数判断字符串是否为回文，并给出一个测试用例。",
    "设计一个 Agent 平台的 Tool Calling 模块，列出三个关键设计点。",
]


def mask_secret(value: str | None) -> str:
    """密钥打码，只保留可辨识前缀。"""
    if not value:
        return "(未配置)"
    return f"{value[:7]}***({len(value)} 字符)"


def describe(settings: Settings) -> None:
    llm = settings.llm
    host = urlparse(llm.base_url).netloc or llm.base_url
    api_key = llm.api_key.get_secret_value() if llm.api_key else None
    print("配置概览")
    print(f"  provider : {llm.provider}")
    print(f"  model    : {llm.model}")
    print(f"  endpoint : {host}")
    print(f"  api_key  : {mask_secret(api_key)}")
    print(f"  timeout  : {llm.timeout_seconds}s    retries: {llm.max_retries}")


async def run_prompt(runtime: AgentRuntime, agent: Agent, prompt: str) -> tuple[RunResult, float]:
    started = time.perf_counter()
    result = await runtime.run(agent, prompt)
    return result, (time.perf_counter() - started) * 1000


async def run_for_model(model: str, prompts: list[str], settings: Settings) -> bool:
    llm_settings = settings.llm.model_copy(update={"model": model})
    client = create_llm_client(llm_settings)
    runtime = AgentRuntime(client, settings=settings.runtime)
    agent = Agent(name="smoke", model=model, system_prompt=settings.runtime.system_prompt)

    print(f"===== 模型 {model} =====")
    succeeded = True
    total_tokens = 0

    try:
        for index, prompt in enumerate(prompts, start=1):
            print(f"[{index}/{len(prompts)}] {prompt}")
            try:
                result, elapsed = await run_prompt(runtime, agent, prompt)
            except AgentOSError as exc:
                succeeded = False
                print(f"    ✗ 失败: {exc.code} - {exc.message}")
                if exc.details:
                    safe = {k: v for k, v in exc.details.items() if k != "body"}
                    print(f"      details: {safe}")
                    if "body" in exc.details:
                        print(f"      provider: {str(exc.details['body'])[:200]}")
                print()
                continue

            tokens = result.usage.total_tokens if result.usage else 0
            total_tokens += tokens
            text = " ".join(result.output.split())
            print(f"    ✓ {elapsed:,.0f} ms | tokens={tokens} | iterations={result.iterations}")
            print(f"      输出: {text[:160]}{'...' if len(text) > 160 else ''}")
            print()
    finally:
        await runtime.aclose()

    status = "通过" if succeeded else "存在失败"
    print(f"----- {model}: {status}，合计 {total_tokens} tokens -----\n")
    return succeeded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentOS 真实模型冒烟测试")
    parser.add_argument("--model", default=None, help="覆盖 .env 中的模型名")
    parser.add_argument("--models", default=None, help="逗号分隔的多个模型，逐个测试")
    parser.add_argument("--prompt", action="append", default=None, help="自定义提示词，可重复")
    parser.add_argument("--quiet", action="store_true", help="降低框架日志级别")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.model and args.models:
        print("--model 与 --models 不能同时使用", file=sys.stderr)
        return 2

    settings = get_settings()
    log_settings = settings.logging
    if args.quiet:
        log_settings = log_settings.model_copy(update={"level": "WARNING"})
    configure_logging(log_settings, force=True)

    models = (
        [item.strip() for item in args.models.split(",") if item.strip()]
        if args.models
        else [args.model or settings.llm.model]
    )
    prompts = args.prompt or DEFAULT_PROMPTS

    print("AgentOS 真实模型冒烟测试")
    print("=" * 64)
    describe(settings)
    print(f"  提示词 {len(prompts)} 条   模型 {len(models)} 个")
    print("=" * 64)
    print()

    results = [asyncio.run(run_for_model(model, prompts, settings)) for model in models]

    print("=" * 64)
    summary = "、".join(
        f"{model}: {'通过' if ok else '失败'}" for model, ok in zip(models, results, strict=True)
    )
    print(f"总结: {summary}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""Optional model cost estimation tests."""

from __future__ import annotations

from agentos.core.config import ModelPricing, RuntimeSettings
from agentos.llm.base import TokenUsage
from agentos.llm.echo import EchoLLMClient
from agentos.observability.cost import estimate_cost
from agentos.runtime.runtime import AgentRuntime


def test_estimate_cost_uses_configured_price() -> None:
    usage = TokenUsage(prompt_tokens=1_000, completion_tokens=500, total_tokens=1_500)
    pricing = {
        "model-a": ModelPricing(
            prompt_tokens_per_million=2.0,
            completion_tokens_per_million=4.0,
        )
    }

    assert estimate_cost(usage, model="model-a", pricing=pricing) == 0.004


def test_estimate_cost_is_null_without_price() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    assert estimate_cost(usage, model="unknown", pricing={}) is None


async def test_runtime_records_estimated_cost() -> None:
    runtime = AgentRuntime(
        EchoLLMClient(model="echo-1"),
        settings=RuntimeSettings(default_agent="assistant"),
        pricing={
            "echo-1": ModelPricing(
                prompt_tokens_per_million=1.0,
                completion_tokens_per_million=1.0,
            )
        },
    )

    result = await runtime.run("assistant", "hello")

    assert result.estimated_cost is not None
    assert result.estimated_cost > 0

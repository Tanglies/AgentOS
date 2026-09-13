"""Optional model cost estimation from configured token prices."""

from __future__ import annotations

from collections.abc import Mapping

from agentos.core.config import ModelPricing
from agentos.llm.base import TokenUsage


def estimate_cost(
    usage: TokenUsage | None,
    *,
    model: str,
    pricing: Mapping[str, ModelPricing],
) -> float | None:
    """Estimate cost, or return ``None`` when the model has no configured price.

    Prices are intentionally configuration-only. AgentOS does not hard-code any
    provider or model price because availability and currency differ by region.
    """
    if usage is None:
        return None
    price = pricing.get(model)
    if price is None:
        return None
    cost = (
        usage.prompt_tokens * price.prompt_tokens_per_million
        + usage.completion_tokens * price.completion_tokens_per_million
    ) / 1_000_000
    return round(cost, 8)


__all__ = ["estimate_cost"]

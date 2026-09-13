"""Long-term memory prompt budget tests."""

from __future__ import annotations

from agentos.core.config import MemorySettings
from agentos.runtime.long_term_memory import LongTermMemory, estimate_tokens


def test_memory_context_respects_char_and_token_budgets(tmp_path) -> None:
    settings = MemorySettings(
        long_term_db_path=str(tmp_path / "memory.db"),
        long_term_recall_limit=5,
        long_term_max_context_chars=120,
        long_term_max_context_tokens=30,
    )
    memory = LongTermMemory(settings)
    memory.remember("alpha " + "x" * 500)

    context = memory.build_context("alpha")

    assert context.recall_count == 1
    assert context.char_count <= 120
    assert context.token_count <= 30
    assert context.text is not None
    assert context.text.endswith("…")


def test_memory_context_is_empty_without_matches(tmp_path) -> None:
    memory = LongTermMemory(MemorySettings(long_term_db_path=str(tmp_path / "memory.db")))
    memory.remember("a different topic")

    assert memory.build_context("alpha").text is None


def test_token_estimate_handles_cjk_conservatively() -> None:
    assert estimate_tokens("上海天气") >= 4

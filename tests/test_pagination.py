"""Keyset pagination tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.core.exceptions import ValidationError
from agentos.core.pagination import PaginationCursor, decode_cursor, encode_cursor


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        llm={"provider": "echo"},
        logging={"level": "ERROR"},
        registry={"persist": True, "db_path": str(tmp_path / "agents.db")},
        runs={"enabled": True, "db_path": str(tmp_path / "runs.db")},
        audit={"db_path": str(tmp_path / "audit.db")},
        api_keys={"db_path": str(tmp_path / "api-keys.db")},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
    )


def test_cursor_round_trip_normalizes_timezone() -> None:
    source = PaginationCursor(
        created_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone(timedelta(hours=8))),
        item_id="run_123",
        order="asc",
    )

    decoded = decode_cursor(encode_cursor(source))

    assert decoded.item_id == "run_123"
    assert decoded.order == "asc"
    assert decoded.created_at == datetime(2026, 9, 21, 4, 0, tzinfo=UTC)


@pytest.mark.parametrize("token", ["", "%%%", "e30"])
def test_invalid_cursor_is_rejected(token: str) -> None:
    with pytest.raises(ValidationError):
        decode_cursor(token)


def test_run_cursor_pagination_is_stable_under_inserts(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for value in ("first", "second", "third"):
            assert client.post("/api/v1/runs", json={"input": value}).status_code == 200

        first_page = client.get("/api/v1/runs", params={"limit": 2}).json()
        assert [item["input"] for item in first_page["items"]] == ["third", "second"]
        assert first_page["next_cursor"]

        assert client.post("/api/v1/runs", json={"input": "new"}).status_code == 200

        second_page = client.get(
            "/api/v1/runs",
            params={"limit": 2, "cursor": first_page["next_cursor"]},
        )
        assert second_page.status_code == 200
        body = second_page.json()
        assert [item["input"] for item in body["items"]] == ["first"]
        assert body["next_cursor"] is None


def test_cursor_cannot_be_combined_with_offset_style_pagination(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/runs", params={"cursor": "bad", "page": 2})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_malformed_cursor_returns_validation_error(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/runs", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_cursor_order_must_match_request(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        client.post("/api/v1/runs", json={"input": "one"})
        client.post("/api/v1/runs", json={"input": "two"})
        cursor = client.get("/api/v1/runs", params={"limit": 1, "order": "asc"}).json()[
            "next_cursor"
        ]
        response = client.get(
            "/api/v1/runs",
            params={"limit": 1, "order": "desc", "cursor": cursor},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

"""Keyset pagination tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.core.exceptions import ValidationError
from agentos.core.pagination import (
    KeysetCursor,
    PaginationCursor,
    decode_cursor,
    decode_keyset_cursor,
    encode_cursor,
    encode_keyset_cursor,
)


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


def test_keyset_cursor_round_trip() -> None:
    source = KeysetCursor(key="researcher", item_id="researcher", order="asc")

    assert decode_keyset_cursor(encode_keyset_cursor(source)) == source


def test_keyset_and_time_cursors_are_not_interchangeable() -> None:
    time_token = encode_cursor(
        PaginationCursor(created_at=datetime(2026, 9, 21, tzinfo=UTC), item_id="run_1")
    )
    keyset_token = encode_keyset_cursor(KeysetCursor(key="alpha", item_id="alpha"))

    with pytest.raises(ValidationError):
        decode_keyset_cursor(time_token)
    with pytest.raises(ValidationError):
        decode_cursor(keyset_token)


@pytest.mark.parametrize("token", ["", "%%%", "e30"])
def test_invalid_keyset_cursor_is_rejected(token: str) -> None:
    with pytest.raises(ValidationError):
        decode_keyset_cursor(token)


def test_agent_cursor_pagination_walks_the_name_order(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for name in ("zeta", "alpha", "middle", "bravo"):
            assert client.post("/api/v1/agents", json={"name": name}).status_code == 201

        first = client.get("/api/v1/agents", params={"page_size": 2}).json()
        assert [item["name"] for item in first["items"]] == ["alpha", "assistant"]
        assert first["total"] == 5
        assert first["next_cursor"]

        second = client.get(
            "/api/v1/agents",
            params={"page_size": 2, "cursor": first["next_cursor"]},
        ).json()
        assert [item["name"] for item in second["items"]] == ["bravo", "middle"]
        assert second["total"] == 5
        assert second["next_cursor"]

        third = client.get(
            "/api/v1/agents",
            params={"page_size": 2, "cursor": second["next_cursor"]},
        ).json()

    assert [item["name"] for item in third["items"]] == ["zeta"]
    assert third["next_cursor"] is None


def test_agent_cursor_is_stable_when_a_previous_row_is_deleted(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for name in ("alpha", "bravo", "charlie", "delta"):
            client.post("/api/v1/agents", json={"name": name})
        first = client.get("/api/v1/agents", params={"page_size": 2}).json()
        assert [item["name"] for item in first["items"]] == ["alpha", "assistant"]

        assert client.delete("/api/v1/agents/alpha").status_code == 204

        second = client.get(
            "/api/v1/agents",
            params={"page_size": 2, "cursor": first["next_cursor"]},
        ).json()

    assert [item["name"] for item in second["items"]] == ["bravo", "charlie"]


def test_agent_cursor_cannot_be_combined_with_page(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for name in ("alpha", "bravo"):
            client.post("/api/v1/agents", json={"name": name})
        cursor = client.get("/api/v1/agents", params={"page_size": 1}).json()[
            "next_cursor"
        ]
        assert cursor
        response = client.get("/api/v1/agents", params={"page": 2, "cursor": cursor})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_agent_list_rejects_a_time_based_cursor(tmp_path) -> None:
    token = encode_cursor(
        PaginationCursor(created_at=datetime(2026, 9, 21, tzinfo=UTC), item_id="run_1")
    )

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/agents", params={"cursor": token})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_agent_cursor_must_match_the_list_order(tmp_path) -> None:
    token = encode_keyset_cursor(
        KeysetCursor(key="alpha", item_id="alpha", order="desc")
    )

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/agents", params={"cursor": token})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

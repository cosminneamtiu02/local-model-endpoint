"""Unit tests for the HealthResponse liveness schema."""

import pytest
from pydantic import ValidationError

from app.schemas import HealthResponse


def test_health_response_default_status_is_ok() -> None:
    """HealthResponse defaults to ``status="ok"`` — the v1 liveness contract."""
    resp = HealthResponse()
    assert resp.status == "ok"


def test_health_response_dump_returns_minimal_shape() -> None:
    """The wire shape is exactly ``{"status": "ok"}``."""
    resp = HealthResponse()
    assert resp.model_dump() == {"status": "ok"}


def test_health_response_rejects_unknown_field() -> None:
    """``extra='forbid'`` keeps the wire surface minimal (LIP liveness contract)."""
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "ok", "uptime_seconds": 42})


def test_health_response_rejects_non_ok_status() -> None:
    """status is the literal ``"ok"`` — no other value is permitted."""
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "degraded"})


def test_health_response_is_frozen_at_runtime() -> None:
    """``frozen=True`` — the wire shape is immutable post-construction."""
    resp = HealthResponse()
    with pytest.raises(ValidationError):
        # frozen=True invariant test — assignment must raise at runtime,
        # not get typed-out by pyright.
        resp.status = "ok"  # pyright: ignore[reportAttributeAccessIssue]

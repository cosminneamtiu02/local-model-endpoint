"""Unit tests for the RFC 7807 ProblemDetails schema."""

import json
from typing import TypedDict

import pytest
from pydantic import ValidationError

from app.schemas import ProblemDetails


class _BaseKwargs(TypedDict):
    """Canonical kwargs shape for ProblemDetails construction in tests.

    Typed so pyright strict can narrow ``**_base_kwargs()`` spreads at
    every call site without falling back to ``dict[str, object]``
    (Unknown under the AnyHttpUrl typing).
    """

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str


def _base_kwargs() -> _BaseKwargs:
    return _BaseKwargs(
        type="urn:lip:error:queue-full",
        title="Inference Queue Full",
        status=503,
        detail="Inference queue at capacity (5 waiters, max 4).",
        instance="/api/v1/inference",
        code="QUEUE_FULL",
        # UUID-shaped to match the schema's defense-in-depth pattern; the
        # handler always populates this field from the middleware's
        # generated UUID, so test fixtures should mirror the real wire shape.
        request_id="12345678-1234-1234-1234-123456789012",
    )


def test_problem_details_accepts_canonical_rfc7807_fields() -> None:
    """All five RFC 7807 fields plus code + request_id construct cleanly."""
    pd = ProblemDetails(**_base_kwargs())
    assert pd.type == "urn:lip:error:queue-full"
    assert pd.title == "Inference Queue Full"
    assert pd.status == 503
    assert pd.detail.startswith("Inference queue")
    assert pd.instance == "/api/v1/inference"
    assert pd.code == "QUEUE_FULL"
    assert pd.request_id == "12345678-1234-1234-1234-123456789012"


def test_problem_details_allows_arbitrary_extension_fields() -> None:
    """extra='allow' accepts typed-params extensions and validation_errors[]."""
    # ``model_validate`` keeps the extras-spread path strictly typed: kwargs
    # spread (``**_base_kwargs(), max_waiters=...``) cannot be statically
    # typed because pyright can't express "TypedDict + arbitrary extra keys".
    pd = ProblemDetails.model_validate(
        {**_base_kwargs(), "max_waiters": 4, "current_waiters": 5},
    )
    dumped = pd.model_dump()
    assert dumped["max_waiters"] == 4
    assert dumped["current_waiters"] == 5


def test_problem_details_accepts_validation_errors_extension_list() -> None:
    """validation_errors[] is permitted via extra='allow' as a list of dicts."""
    pd = ProblemDetails.model_validate(
        {
            **_base_kwargs(),
            "validation_errors": [
                {"field": "messages.0.role", "reason": "Input should be 'user'"},
                {"field": "messages.1.content", "reason": "field required"},
            ],
        },
    )
    dumped = pd.model_dump()
    assert isinstance(dumped["validation_errors"], list)
    assert dumped["validation_errors"][0]["field"] == "messages.0.role"
    assert dumped["validation_errors"][1]["reason"] == "field required"


def test_problem_details_rejects_missing_status() -> None:
    """status is required (RFC 7807 §3.1)."""
    kwargs: dict[str, object] = dict(_base_kwargs())
    del kwargs["status"]
    with pytest.raises(ValidationError, match="status"):
        ProblemDetails.model_validate(kwargs)


def test_problem_details_rejects_status_out_of_range() -> None:
    """status must be 400-599 — non-error responses are not problems."""
    kwargs: dict[str, object] = dict(_base_kwargs())
    kwargs["status"] = 200
    with pytest.raises(ValidationError, match="status"):
        ProblemDetails.model_validate(kwargs)


def test_problem_details_dump_includes_extension_fields_at_root() -> None:
    """extra fields appear at root level of model_dump(), not nested."""
    pd = ProblemDetails.model_validate(
        {**_base_kwargs(), "validation_errors": [{"field": "x", "reason": "y"}]},
    )
    dumped = pd.model_dump()
    assert "validation_errors" in dumped
    assert dumped["validation_errors"] == [{"field": "x", "reason": "y"}]
    # No nested 'extra' key
    assert "extra" not in dumped
    assert "__pydantic_extra__" not in dumped


def test_problem_details_model_dump_json_produces_valid_json() -> None:
    """model_dump_json() — the path used by the handler — round-trips through json.loads."""
    pd = ProblemDetails.model_validate(
        {
            **_base_kwargs(),
            "max_waiters": 4,
            "current_waiters": 5,
            "validation_errors": [{"field": "x", "reason": "y"}],
        },
    )
    raw = pd.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["status"] == 503
    assert parsed["max_waiters"] == 4
    assert parsed["validation_errors"] == [{"field": "x", "reason": "y"}]


@pytest.mark.parametrize(
    "bad_code",
    [
        "",  # rejected by min_length=1
        "queue-full",  # kebab-case
        "QueueFull",  # PascalCase
        "QUEUE__FULL",  # double underscore
        "_QUEUE_FULL",  # leading underscore
        "QUEUE_FULL_",  # trailing underscore
        "42_FOO",  # leading digit
    ],
)
def test_problem_details_rejects_malformed_code(bad_code: str) -> None:
    """``code`` MUST match the SCREAMING_SNAKE regex from
    ``apps/backend/app/schemas/problem_details.py:112``.

    The drift-guard test ``test_screaming_snake_pattern_drift_guard.py``
    pins the regex string itself across codegen + schema; this test
    exercises the regex against the failing-input alphabet so a future
    refactor that swaps the ``pattern=`` for a callable validator (or
    drops the pattern entirely) would land red even if the literal-string
    drift-guard stayed green.
    """
    kwargs: dict[str, object] = dict(_base_kwargs())
    kwargs["code"] = bad_code
    with pytest.raises(ValidationError, match="code"):
        ProblemDetails.model_validate(kwargs)


@pytest.mark.parametrize(
    "bad_type",
    [
        "oops",  # bare string, not a URN nor about:blank
        "http://example.com/error",  # http URL — disallowed in v1
        "urn:lip:error:Mixed_Case",  # uppercase / underscores in tail
        "urn:other:error:queue-full",  # wrong namespace
    ],
)
def test_problem_details_rejects_malformed_type(bad_type: str) -> None:
    """``type`` MUST match ``about:blank`` or ``urn:lip:error:<kebab>``.

    Pinned via regex on the schema; this test asserts the rejection
    alphabet so a future refactor of the regex (e.g. relaxing to allow
    http URLs) lands as a deliberate diff with these cases editing in
    lockstep.
    """
    kwargs: dict[str, object] = dict(_base_kwargs())
    kwargs["type"] = bad_type
    with pytest.raises(ValidationError, match="type"):
        ProblemDetails.model_validate(kwargs)

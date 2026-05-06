"""Drift-guard for the inference-feature unit-test ``valid_request_id`` fixture.

The literal ``VALID_REQUEST_ID`` lives at module scope in
``tests/unit/features/inference/conftest.py``; this test asserts the
literal still matches the wire-contract UUID regex pinned in
``app.schemas.wire_constants.UUID_REGEX``. A future regex tightening
that no longer matches the fixture fires here, NOT as 16 silent green
tests with a stale fixture.

Lives in a dedicated ``test_*.py`` module — not embedded in conftest —
so the standard ``find tests -name 'test_*.py'`` audit finds it
without surprise.
"""

from __future__ import annotations

from app.schemas.wire_constants import UUID_REGEX

from .conftest import VALID_REQUEST_ID


def test_valid_request_id_fixture_matches_wire_contract_regex() -> None:
    """Pin the ``valid_request_id`` literal against the wire-contract UUID regex."""
    assert UUID_REGEX.match(VALID_REQUEST_ID), (
        f"valid_request_id fixture ({VALID_REQUEST_ID!r}) no longer matches "
        "the wire-contract UUID regex; tighten or update the fixture in "
        "lockstep with the regex."
    )

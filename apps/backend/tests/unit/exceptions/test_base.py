"""Unit tests for DomainError base class invariants."""

import pytest

from app.exceptions import DomainError


def test_domain_error_subclass_without_classvars_raises_type_error() -> None:
    """A DomainError subclass missing 'code' or 'http_status' raises TypeError at class creation."""
    with pytest.raises(TypeError, match="must declare ClassVar"):

        class _MissingError(DomainError):
            pass


def test_domain_error_direct_instantiation_raises_type_error() -> None:
    """DomainError itself is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError, match="abstract"):
        DomainError()

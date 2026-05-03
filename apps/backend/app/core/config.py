"""Application configuration via pydantic-settings."""

import ipaddress
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_private_host(host: str) -> bool:
    """Return True if ``host`` is loopback / RFC1918 / link-local / ULA / mDNS."""
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    # Pydantic's ``AnyHttpUrl.host`` normalizes brackets out of IPv6 forms
    # (i.e. ``http://[::1]/`` -> ``"::1"``), so the SSRF clamp normally
    # sees bare hosts. The bracket-strip below is defense-in-depth for
    # ``bind_host``, which is a free-form string and could legitimately
    # carry brackets (e.g. ``LIP_BIND_HOST=[::]``).
    classifiable = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ip = ipaddress.ip_address(classifiable)
    except ValueError:
        # Control-flow conversion: a non-IP string (e.g. a custom DNS name) is
        # not loopback/private — return the safe default. Not a "silent swallow"
        # per CLAUDE.md; the parse failure encodes a known business case.
        return False
    # 0.0.0.0 / :: are unspecified — nonsensical as outbound targets and
    # the same all-interfaces values the bind-side clamp reject-lists, so
    # they must NOT be considered "private" upstream targets.
    if ip.is_unspecified:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # env_prefix="LIP_" disambiguates every env var from Ollama daemon's
    # own OLLAMA_HOST. validate_default=True ensures bad defaults fail at
    # import time.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LIP_",
        extra="forbid",
        frozen=True,
        case_sensitive=False,
        env_ignore_empty=True,
        validate_default=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    # Lowercase is canonical; configure_logging uppercases via .upper()
    # before passing to stdlib logging.setLevel.
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"

    # Ollama backend host. Configurable so tests can point at a fixture and
    # future deployments can target a different Ollama instance. The
    # ``LIP_`` env-var prefix (set on model_config) disambiguates the
    # consumer-visible env var ``LIP_OLLAMA_HOST`` from Ollama daemon's
    # own ``OLLAMA_HOST``. AnyHttpUrl validates scheme + host; httpx
    # accepts the str() form. The model-level validator further clamps
    # the host to localhost / RFC1918 / link-local / ULA / mDNS unless
    # allow_external_ollama is set.
    ollama_host: AnyHttpUrl = AnyHttpUrl("http://localhost:11434")

    # Escape hatch for pointing Ollama at a non-private host (cloud
    # endpoint, gateway, etc.). Default is False so a typo in the env
    # var cannot silently turn LIP into a forwarding proxy.
    allow_external_ollama: bool = False

    # Escape hatch for binding to a public interface (0.0.0.0 / ::).
    # Default is False; the model validator rejects all-interfaces
    # values unless this is explicitly True.
    allow_public_bind: bool = False

    # Interface to bind uvicorn to. Default is loopback only; binding to a
    # non-private host requires opt-in via allow_public_bind because LIP
    # has no authentication layer. ``max_length=253`` is the RFC 1035
    # hostname cap so garbage strings fail at the type boundary before
    # reaching ``_check_safety_invariants``'s classifier.
    bind_host: str = Field(
        default="127.0.0.1",
        description="Interface to bind uvicorn to (loopback / private LAN).",
        # min_length=1 dropped: an empty bind_host is already rejected by
        # ``_check_safety_invariants`` (``is_private_host("")`` returns
        # False) with the more actionable error "bind_host='' is not
        # loopback / private LAN..." than Pydantic's generic "String
        # should have at least 1 character". One way to do each thing —
        # the safety-invariant validator owns the "is this a usable
        # bind target" call.
        max_length=253,
    )
    # ``ge=1024`` forbids privileged ports — running LIP as root is out
    # of project scope. Raise the lower bound only if a future macOS
    # launchd handoff is added that drops privileges after binding 80/443.
    bind_port: int = Field(default=8000, ge=1024, le=65535)

    @model_validator(mode="after")
    def _check_safety_invariants(self) -> Self:
        # Bind-host clamp: anything we can't recognize as private requires
        # ``allow_public_bind``. This catches the all-interfaces values
        # (0.0.0.0, ::) AND a public address typo (8.8.8.8, garbage strings,
        # etc.) — the original membership check on a 2-element set let
        # everything outside the loopback/RFC1918 families slip past the
        # validator unless it was literally one of two strings.
        if not is_private_host(self.bind_host) and not self.allow_public_bind:
            msg = (
                f"bind_host={self.bind_host!r} is not loopback / private LAN / link-local; "
                "set LIP_ALLOW_PUBLIC_BIND=true explicitly to acknowledge "
                "LIP has no auth before LAN-exposing it"
            )
            raise ValueError(msg)
        # SSRF clamp: don't let a typo turn LIP into a forwarding proxy.
        host = self.ollama_host.host or ""
        if not is_private_host(host) and not self.allow_external_ollama:
            msg = (
                f"ollama_host host={host!r} is not localhost / private LAN / link-local; "
                "set LIP_ALLOW_EXTERNAL_OLLAMA=true explicitly to acknowledge that LIP will "
                "forward consumer prompts to a non-private host"
            )
            raise ValueError(msg)
        return self

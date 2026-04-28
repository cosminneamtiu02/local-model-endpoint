"""Application configuration via pydantic-settings."""

import ipaddress
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_private_host(host: str) -> bool:
    """Return True if ``host`` is loopback / RFC1918 / link-local / ULA / mDNS."""
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    # AnyHttpUrl.host returns IPv6 hosts in bracketed form (``[::1]``); the
    # stdlib ipaddress module rejects brackets, so strip before classifying.
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
    # has no authentication layer.
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1024, le=65535)

    @model_validator(mode="after")
    def _check_safety_invariants(self) -> Self:
        # Bind-host clamp: anything we can't recognize as private requires
        # ``allow_public_bind``. This catches the all-interfaces values
        # (0.0.0.0, ::) AND a public address typo (8.8.8.8, garbage strings,
        # etc.) — the original membership check on a 2-element set let
        # everything outside the loopback/RFC1918 families slip past the
        # validator unless it was literally one of two strings.
        if not _is_private_host(self.bind_host) and not self.allow_public_bind:
            msg = (
                f"bind_host={self.bind_host!r} is not loopback / private LAN / link-local; "
                "set LIP_ALLOW_PUBLIC_BIND=true explicitly to acknowledge "
                "LIP has no auth before LAN-exposing it"
            )
            raise ValueError(msg)
        # SSRF clamp: don't let a typo turn LIP into a forwarding proxy.
        host = self.ollama_host.host or ""
        if not _is_private_host(host) and not self.allow_external_ollama:
            msg = (
                f"ollama_host host={host!r} is not localhost / private LAN / link-local; "
                "set LIP_ALLOW_EXTERNAL_OLLAMA=true explicitly to acknowledge that LIP will "
                "forward consumer prompts to a non-private host"
            )
            raise ValueError(msg)
        return self

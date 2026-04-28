"""Application configuration via pydantic-settings."""

import ipaddress
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hostnames LIP considers safe targets for the Ollama base URL without
# explicit operator opt-in. The clamp accepts: ``localhost``, any address
# that ``ipaddress`` classifies as loopback / private / link-local (covers
# RFC1918 IPv4, IPv6 loopback ``::1``, IPv6 link-local ``fe80::/10``, and
# IPv6 ULA ``fc00::/7``), and ``*.local`` mDNS names. Anything else
# requires ``allow_external_ollama=True`` so a typo cannot silently turn
# LIP into an external-host forwarding proxy.
_PUBLIC_BIND_ADDRS: frozenset[str] = frozenset({"0.0.0.0", "::"})  # noqa: S104 - reject-list


def _is_private_host(host: str) -> bool:
    """Return True if ``host`` is loopback / RFC1918 / link-local / ULA / mDNS."""
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    LIP-specific fields are added during feature-dev as LIP-E004 and
    LIP-E005 are thickened. Planned-but-deferred fields:
        - queue depth                     (LIP-E004-F001)
        - per-request timeout seconds     (LIP-E004-F003)
        - idle-shutdown interval seconds  (LIP-E005-F002)
    """

    # ``env_prefix="LIP_"`` namespaces every env-var read so a single shell
    # can run both the Ollama daemon (which reads ``OLLAMA_HOST``) and LIP
    # without crossed wires. Every field's env var is therefore
    # ``LIP_<UPPER_FIELD_NAME>`` (e.g. ``LIP_APP_ENV``, ``LIP_OLLAMA_HOST``).
    # ``case_sensitive=False`` matches pydantic-settings' default; pinning
    # explicit defends against future minor-release default flips.
    # ``env_ignore_empty=True`` lets an exported-but-empty ``LIP_X=`` fall
    # back to the field default (the common shell-unset pattern).
    # ``validate_default=True`` runs validators against literal defaults so
    # a constraint-violating default fails at import time, not first-use.
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

    # Interface to bind uvicorn to. Default is loopback only; binding to
    # 0.0.0.0 / :: requires opt-in via allow_public_bind because LIP has
    # no authentication layer.
    bind_host: str = Field(default="127.0.0.1")
    bind_port: int = Field(default=8000, ge=1024, le=65535)

    @model_validator(mode="after")
    def _check_safety_invariants(self) -> Self:
        # Bind-host clamp: reject all-interfaces values, and reject any
        # non-IP / non-loopback string unless the operator opted into
        # public binding. ``ipaddress.ip_address`` rejects non-IP strings
        # with ValueError; we treat anything we can't recognize as
        # private as "needs allow_public_bind".
        if self.bind_host in _PUBLIC_BIND_ADDRS and not self.allow_public_bind:
            msg = (
                f"bind_host={self.bind_host!r} binds to all interfaces; "
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

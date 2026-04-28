"""Application configuration via pydantic-settings."""

import re
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hostnames / IPs that LIP considers safe targets for the Ollama base URL
# without explicit operator opt-in. Loopback + private RFC1918 + link-local
# cover every realistic LAN deployment of an Ollama daemon. Anything else
# requires `allow_external_ollama=True` so a typo cannot silently turn
# LIP into an external-host forwarding proxy.
_PRIVATE_HOST_PATTERN = re.compile(
    r"""^(
        localhost
        | 127\.\d{1,3}\.\d{1,3}\.\d{1,3}
        | ::1
        | 10\.\d{1,3}\.\d{1,3}\.\d{1,3}
        | 192\.168\.\d{1,3}\.\d{1,3}
        | 172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}
        | 169\.254\.\d{1,3}\.\d{1,3}
        | [a-z0-9-]+\.local
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


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
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LIP_",
        extra="forbid",
        frozen=True,
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
    # the host to localhost / RFC1918 / link-local unless
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
        # Bind-host clamp.
        public_addrs = {"0.0.0.0", "::"}  # noqa: S104 - reject-list, not bind target
        if self.bind_host in public_addrs and not self.allow_public_bind:
            msg = (
                f"bind_host={self.bind_host!r} binds to all interfaces; "
                "set LIP_ALLOW_PUBLIC_BIND=true explicitly to acknowledge "
                "LIP has no auth before LAN-exposing it"
            )
            raise ValueError(msg)
        # SSRF clamp: don't let a typo turn LIP into a forwarding proxy.
        host = self.ollama_host.host or ""
        if not _PRIVATE_HOST_PATTERN.match(host) and not self.allow_external_ollama:
            msg = (
                f"ollama_host host={host!r} is not localhost / private LAN / link-local; "
                "set LIP_ALLOW_EXTERNAL_OLLAMA=true explicitly to acknowledge that LIP will "
                "forward consumer prompts to a non-private host"
            )
            raise ValueError(msg)
        return self

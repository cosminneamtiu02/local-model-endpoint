"""Application configuration via pydantic-settings."""

from typing import Literal

from pydantic import AnyHttpUrl, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    LIP-specific fields are added during feature-dev as LIP-E004 and
    LIP-E005 are thickened. Planned-but-deferred fields:
        - queue depth                     (LIP-E004-F001)
        - per-request timeout seconds     (LIP-E004-F003)
        - idle-shutdown interval seconds  (LIP-E005-F002)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    # Lowercase is canonical; configure_logging uppercases via .upper()
    # before passing to stdlib logging.setLevel.
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"

    # Ollama backend host. Configurable so tests can point at a fixture
    # and future deployments can target a different Ollama instance. The
    # `lip_` prefix disambiguates this from Ollama daemon's own
    # OLLAMA_HOST env var so a single shell can run both without crossed
    # wires. AnyHttpUrl validates scheme + host; httpx accepts the
    # str() form.
    lip_ollama_host: AnyHttpUrl = AnyHttpUrl("http://localhost:11434")

    # Escape hatch for binding to a public interface (0.0.0.0 / ::).
    # Declared *before* bind_host so the bind_host validator can read it
    # via ValidationInfo.data. Default is False; the bind_host validator
    # rejects all-interfaces values unless this is explicitly True.
    allow_public_bind: bool = False

    # Interface to bind uvicorn to. Default is loopback only; binding to
    # 0.0.0.0 / :: requires opt-in via allow_public_bind because LIP has
    # no authentication layer.
    bind_host: str = Field(default="127.0.0.1")
    bind_port: int = Field(default=8000, ge=1024, le=65535)

    @field_validator("bind_host")
    @classmethod
    def _reject_public_bind_unless_allowed(cls, value: str, info: ValidationInfo) -> str:
        public_addrs = {"0.0.0.0", "::"}  # noqa: S104 - reject-list, not bind target
        if value in public_addrs and not info.data.get("allow_public_bind", False):
            msg = (
                f"bind_host={value!r} binds to all interfaces; set ALLOW_PUBLIC_BIND=true "
                "explicitly to acknowledge LIP has no auth before LAN-exposing it"
            )
            raise ValueError(msg)
        return value

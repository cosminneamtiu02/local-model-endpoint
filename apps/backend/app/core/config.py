"""Application configuration via pydantic-settings."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    LIP-specific fields (queue depth, per-request timeout, idle-shutdown
    interval) are added during feature-dev as LIP-E004 and LIP-E005 are
    thickened.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_env: str = "development"
    # Lowercase is canonical; configure_logging uppercases via .upper()
    # before passing to stdlib logging.setLevel.
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"

    # Ollama backend host. Configurable so tests can point at a fixture
    # and future deployments can target a different Ollama instance.
    ollama_host: str = "http://localhost:11434"

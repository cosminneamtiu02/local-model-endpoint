"""Application configuration via pydantic-settings."""

import ipaddress
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
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
    # Strip an IPv6 zone-ID suffix (RFC 4007 ``%scope`` selector) before
    # parsing so a link-local address like ``fe80::1%en0`` classifies as
    # link-local rather than triggering ipaddress's ValueError. The zone-ID
    # is interface-local routing metadata, not part of the address itself,
    # so dropping it is the correct classification semantics.
    classifiable = classifiable.split("%", 1)[0]
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
    # IPv4-mapped IPv6 (``::ffff:127.0.0.1`` / ``::ffff:8.8.8.8``) does not
    # set ``.is_loopback`` / ``.is_private`` / ``.is_link_local`` on the
    # IPv6 view — re-classify against the embedded IPv4 form so an operator
    # who explicitly writes the v4-mapped-v6 loopback isn't pushed toward
    # ``LIP_ALLOW_EXTERNAL_OLLAMA=true`` by a false-positive clamp.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Loads from ``apps/backend/.env`` (resolved against this file's location
    via ``Path(__file__).parents[2]``) so the resolution is invariant to the
    process cwd. Production invocation via ``task dev`` cd's into
    ``apps/backend/`` (Taskfile.yml ``BACKEND_DIR`` var) and a tester or
    operator running ``python -m app`` from the repo root both find the
    same file.

    ``extra="forbid"`` is enforced on init kwargs ONLY — pydantic-settings
    silently ignores unknown ``LIP_*``-prefixed env vars (verified by
    ``test_settings_extra_forbid_silently_ignores_unknown_env_var``).
    A typo in ``.env`` (e.g. ``LIP_OLLMA_HOST``) is therefore not caught
    at import time. The audit-only ``os.environ`` enumeration in
    ``app.api.deps.audit_lip_env_typos`` (per ADR-014) surfaces such typos
    as a single ``unknown_lip_env_vars_ignored`` structlog warning when
    invoked once from ``create_app`` at startup, so the silent-ignore
    behavior is observable to operators.
    """

    # env_prefix="LIP_" disambiguates every env var from Ollama daemon's
    # own OLLAMA_HOST. validate_default=True ensures bad defaults fail at
    # import time. ``env_file`` is anchored to this file's location so it
    # survives a non-default cwd (``Path(__file__).parents[2]`` resolves
    # to ``apps/backend/`` from ``apps/backend/app/core/config.py``).
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parents[2] / ".env"),
        env_file_encoding="utf-8",
        env_prefix="LIP_",
        extra="forbid",
        frozen=True,
        case_sensitive=False,
        env_ignore_empty=True,
        validate_default=True,
    )

    # ``production`` is the only value that triggers behavior today (gates
    # ``/docs`` exposure in main.py). The alphabet is closed against
    # ADR-011's "no scaffolding before the feature lands" rule: re-add a
    # ``"test"`` literal narrowly when a test-mode behavior actually lands
    # (e.g. mock-Ollama injection, forced JSON logging) so operators have
    # one switch with one effect, not a switch with no effect.
    app_env: Literal["development", "production"] = Field(
        default="development",
        description=(
            "Application environment. Only ``production`` triggers behavior "
            "(gates ``/docs`` / ``/redoc`` / ``/openapi.json`` exposure)."
        ),
    )
    # Lowercase is canonical; configure_logging uppercases via .upper()
    # before passing to stdlib logging.setLevel. Uppercase env values are
    # accepted via the ``_normalize_log_level`` field validator.
    log_level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="info",
        description=(
            "Minimum log level. Uppercase env values (INFO, WARNING) are "
            "accepted and lowercased before validation."
        ),
    )

    # Ollama backend host. Configurable so tests can point at a fixture and
    # future deployments can target a different Ollama instance. The
    # ``LIP_`` env-var prefix (set on model_config) disambiguates the
    # consumer-visible env var ``LIP_OLLAMA_HOST`` from Ollama daemon's
    # own ``OLLAMA_HOST``. AnyHttpUrl validates scheme + host; httpx
    # accepts the str() form. The model-level validator further clamps
    # the host to localhost / RFC1918 / link-local / ULA / mDNS unless
    # allow_external_ollama is set.
    #
    # ``default_factory`` (not ``default``) so URL parsing runs at model-init
    # time rather than at module-import time. AnyHttpUrl is immutable so the
    # shared-instance footgun does not apply, but a typo in the literal
    # would otherwise crash interpreter import before structlog has any
    # handler attached. ``validate_default=True`` re-validates per construction.
    ollama_host: AnyHttpUrl = Field(
        default_factory=lambda: AnyHttpUrl("http://localhost:11434"),
        description=(
            "Ollama backend URL. Validated against the loopback / RFC1918 / "
            "link-local / ULA / mDNS clamp unless ``allow_external_ollama`` "
            "is set; httpx accepts the ``str()`` form."
        ),
    )

    # Escape hatch for pointing Ollama at a non-private host (cloud
    # endpoint, gateway, etc.). Default is False so a typo in the env
    # var cannot silently turn LIP into a forwarding proxy.
    allow_external_ollama: bool = Field(
        default=False,
        description="Bypass the loopback/RFC1918 SSRF clamp on ollama_host.",
    )

    # Escape hatch for binding to a public interface (0.0.0.0 / ::).
    # Default is False; the model validator rejects all-interfaces
    # values unless this is explicitly True.
    allow_public_bind: bool = Field(
        default=False,
        description="Bypass the loopback/private-LAN clamp on bind_host.",
    )

    # Interface to bind uvicorn to. Default is loopback only; binding to a
    # non-private host requires opt-in via allow_public_bind because LIP
    # has no authentication layer. ``max_length=253`` is the RFC 1035
    # hostname cap so garbage strings fail at the type boundary before
    # reaching ``_check_safety_invariants``'s classifier.
    bind_host: str = Field(
        default="127.0.0.1",
        description="Interface to bind uvicorn to (loopback / private LAN).",
        # ``env_ignore_empty=True`` in model_config means an empty
        # ``LIP_BIND_HOST=`` env var is treated as missing and falls back
        # to the default; ``min_length=1`` here catches the direct-init
        # ``Settings(bind_host="")`` path that pydantic-settings does not
        # filter, surfacing it as a typed ValidationError at the boundary
        # instead of degrading to ``_check_safety_invariants``'s emptiness
        # check. ``max_length=253`` is the RFC 1035 hostname cap.
        min_length=1,
        max_length=253,
    )
    # ``ge=1024`` forbids privileged ports — running LIP as root is out
    # of project scope. Raise the lower bound only if a future macOS
    # launchd handoff is added that drops privileges after binding 80/443.
    # Loose ``int`` (not ``StrictInt``): env vars always arrive as strings,
    # so ``StrictInt`` would reject every valid ``LIP_BIND_PORT=8000`` env
    # var; the ``ge``/``le`` bounds catch the value-shape concern.
    bind_port: int = Field(
        default=8000,
        ge=1024,
        le=65535,
        description=(
            "Port to bind uvicorn to (1024-65535; privileged ports are out "
            "of project scope per the ``ge=1024`` constraint)."
        ),
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Lowercase incoming log-level strings to match the canonical alphabet.

        Both ``LIP_LOG_LEVEL=INFO`` and ``LIP_LOG_LEVEL=info`` are accepted
        — the ``Literal[...]`` constraint on ``log_level`` is case-sensitive,
        so without this normalizer an uppercase value (the natural form for
        operators copy-pasting from stdlib ``logging`` docs) would fail
        validation with a confusing "input should be 'debug', 'info', ..."
        error. Returning the value unchanged for non-string inputs lets
        Pydantic's downstream type-coercion produce the canonical error.
        """
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_safety_invariants(self) -> Self:
        # Bind-host clamp: anything we can't recognize as private requires
        # ``allow_public_bind``. This catches the all-interfaces values
        # (0.0.0.0, ::) AND a public address typo (8.8.8.8, garbage
        # strings, etc.) — clamping anything we cannot classify as private
        # is the correct default for a service with no auth.
        # ``!r`` (not ``!s``) is intentional and load-bearing: ``repr()``
        # escapes control chars (\\x1b, \\n, etc.) so a malicious env var
        # like ``LIP_BIND_HOST=$'\\x1b[31mfoo\\x1b[0m'`` cannot ANSI-inject
        # into stdout-rendered ValidationError messages.
        if not is_private_host(self.bind_host) and not self.allow_public_bind:
            msg = (
                f"bind_host={self.bind_host!r} is not loopback / private LAN / link-local; "
                "set LIP_ALLOW_PUBLIC_BIND=true explicitly to acknowledge "
                "LIP has no auth before LAN-exposing it"
            )
            raise ValueError(msg)
        # SSRF clamp: don't let a typo turn LIP into a forwarding proxy.
        # ``ollama_host=`` mirrors the ``bind_host=`` field name in the
        # bind-clamp above so a single grep finds both safety-clamp errors.
        host = self.ollama_host.host or ""
        if not is_private_host(host) and not self.allow_external_ollama:
            msg = (
                f"ollama_host={host!r} is not localhost / private LAN / link-local; "
                "set LIP_ALLOW_EXTERNAL_OLLAMA=true explicitly to acknowledge that LIP will "
                "forward consumer prompts to a non-private host"
            )
            raise ValueError(msg)
        # Reject URL-embedded userinfo on ollama_host. Without this, a
        # misconfigured host that includes credentials in the URL would let
        # httpx's HTTPStatusError ``str(exc)`` formatter surface them into
        # the ``ollama_call_failed`` log line via the URL embedded in the
        # exception message. AnyHttpUrl accepts userinfo by default; the
        # rest of LIP has no auth model that uses it.
        if self.ollama_host.username or self.ollama_host.password:
            msg = (
                "ollama_host must not embed URL userinfo; LIP has no auth model "
                "that uses it and the credentials would surface in httpx exception "
                "strings on failure paths."
            )
            raise ValueError(msg)
        return self

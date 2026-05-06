"""Code generator from errors.yaml.

Primary (and only) output: Python exception classes (one file per error class
plus optional params class), wired through ``generate_python``. The Taskfile
and CI invoke this entry point, and the generated Python tree under
``app/exceptions/_generated/`` is the canonical artifact.

Generated files are committed but never edited by hand.
"""

import json
import keyword
import re
import string
from collections.abc import Mapping
from operator import itemgetter
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

import yaml

# Type aliases for the loaded YAML shape. ``yaml.safe_load`` returns ``Any``,
# so the generator-internal contract is "validated YAML is a ``_ErrorsFile``"
# — load_and_validate is the gatekeeper that establishes the invariant via
# explicit isinstance checks and a final cast. Helpers below accept the
# narrowed types so pyright strict can verify the call graph.
_ParamsMap = dict[str, str]
_ErrorSpec = dict[str, Any]
_ErrorsFile = dict[str, Any]

# Module-level constants are ``Final`` to mirror the discipline in
# ``apps/backend/app/api/request_id_middleware.py``, ``exception_handler_registry.py``,
# and ``ollama_translation.py``: the rebind-immutable annotation lets pyright
# catch accidental reassignment and keeps the codegen package idiomatically
# consistent with the backend it generates into.
VALID_PARAM_TYPES: Final[frozenset[str]] = frozenset({"string", "integer", "number", "boolean"})
PARAM_TYPE_TO_PYTHON: Final[Mapping[str, str]] = MappingProxyType(
    {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
    }
)

# RFC 7807 standard fields plus LIP project extensions plus the validation_errors
# extension array name. errors.yaml MUST NOT declare a param with any of these
# names — the response handler in apps/backend/app/api/exception_handler_registry.py
# spreads typed params at root level alongside these explicit kwargs, and a
# collision raises TypeError at request time, masking the real error as a 500.
#
# MAINTENANCE: when a new ProblemExtras key is added in
# apps/backend/app/schemas/problem_extras.py (e.g. a future
# ``retry_after`` extension on rate-limited responses), it MUST be added
# to this set in lockstep. The codegen package cannot import from
# apps.backend (cross-workspace dep), so the two sources of truth must
# be hand-synced — this comment is the only enforcement until a future
# build-time validator catches the drift.
RESERVED_PARAM_NAMES: Final[frozenset[str]] = frozenset(
    {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "code",
        "request_id",
        "validation_errors",
    }
)

# Ruff's configured line-length. Used to wrap long generated lines into the
# parenthesized continuation form ruff format produces, so the codegen is
# idempotent under ``ruff format`` and ``task check:errors``' drift guard
# remains stable across regenerations.
RUFF_LINE_LENGTH: Final[int] = 100

# HTTP status range — codes outside [400, 599] are not error responses per
# RFC 9110 §15.5/§15.6 and have no place in errors.yaml. ``HTTP_5XX_FLOOR``
# is the boundary the codegen uses to gate the PII-safe-allowlist check
# at codegen time; the wider 400-599 range is the YAML-validation gate.
HTTP_ERROR_STATUS_MIN: Final[int] = 400
HTTP_ERROR_STATUS_MAX: Final[int] = 599
HTTP_5XX_FLOOR: Final[int] = 500

# Control character boundaries — symmetric with the ``_C0_CONTROL_UPPER`` /
# ``_DEL_CHAR`` constants in ``apps/backend/app/api/request_id_middleware.py``
# (the runtime ASCII-clean discipline pattern). Codes < 0x20 are the C0
# control range (\\x00-\\x1f, ASCII control chars); 0x7f is DEL. Used by the
# detail_template control-char rejector so a YAML author with a misbehaving
# editor cannot inject raw control bytes that would ride into wire-body
# ``ProblemDetails.detail`` and dev-mode ConsoleRenderer log lines.
_C0_CONTROL_UPPER: Final[int] = 0x20
# DEL (0x7F) is the lone codepoint above the C0 range that ``ascii_safe``
# (the runtime peer in ``app/core/logging.py``) also flags. Hoisting it to
# a named constant keeps the codegen control-char rejector and the runtime
# discipline expressed via the SAME pair of named bounds — a future
# audit-bump that adds the C1 range (``0x80``-``0x9F``) is then a single
# constant addition rather than a search-and-replace across two modules.
_DEL_CHAR: Final[int] = 0x7F

# Sentinel that every codegen-emitted file's first source line MUST start
# with. The orphan-cleanup pass uses this to discriminate codegen output
# from a hypothetical hand-written sibling — the structural prefix-match
# is stricter than a substring scan and prevents an accidental wrong-
# output_dir invocation from wiping unrelated Python files.
_GENERATED_SENTINEL_PREFIX: Final[str] = '"""Generated'

# Compiled regex patterns hoisted to module scope (mirrors
# ``apps/backend/app/schemas/wire_constants.py``'s precompile-at-module-
# scope discipline). Codegen is cold-path so the perf delta is academic;
# the consistency keeps a single grep pattern useful for "where do regexes
# live in this codebase".
_ERROR_KEY_INDENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(\s+)(\w+)\s*:\s*(?:#.*)?$",
)
_PASCAL_CASE_BOUNDARY_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<!^)([A-Z])")
_SCREAMING_SNAKE_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Z][A-Z0-9]*(_[A-Z][A-Z0-9]*)*$",
)


def _code_to_class_name(code: str) -> str:
    """Convert SCREAMING_SNAKE to PascalCase error class name.

    Appends 'Error' unless the name already ends with 'Error'.
    e.g. WIDGET_NOT_FOUND -> WidgetNotFoundError
         INTERNAL_ERROR -> InternalError (not InternalErrorError)
    """
    base = "".join(word.capitalize() for word in code.lower().split("_"))
    if base.endswith("Error"):
        return base
    return base + "Error"


def _class_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case.

    e.g. ``WidgetNotFoundError`` -> ``widget_not_found_error``.

    The regex inserts an underscore before EVERY uppercase letter EXCEPT
    the first. When the input is a ``_code_to_class_name`` output, each
    uppercase letter marks a SCREAMING_SNAKE segment boundary (single-
    letter or first-letter-of-multi-letter): ``HTTP_TIMEOUT`` round-trips
    via class ``HttpTimeoutError`` to file stem ``http_timeout_error``,
    and a degenerate code ``A_B_C`` round-trips via ``ABCError`` to
    ``a_b_c_error`` (each segment is one upper letter, regex-correctly
    underscored). Restricted to inputs derived from ``_code_to_class_name``;
    do NOT use on arbitrary PascalCase strings (``IOError`` would become
    ``i_o_error`` because the regex has no way to know "IO" is a single
    initialism rather than two segments).
    """
    return _PASCAL_CASE_BOUNDARY_PATTERN.sub(r"_\1", name).lower()


def _detect_duplicate_keys(raw_text: str) -> None:
    """Detect duplicate top-level error code keys in the YAML text.

    PyYAML silently collapses duplicate mapping keys; we detect them here so
    accidental duplicates fail loud at codegen time rather than silently
    dropping one of the two entries. The regex permits trailing whitespace
    and ``# ...`` comments so common YAML formatting variants don't bypass
    the check.
    """
    lines = raw_text.splitlines()
    in_errors = False
    seen_codes: set[str] = set()
    # Match any single-level indented `KEY:` line (any indent depth, any
    # whitespace style). We also remember the indent depth of the first
    # error key so a deeper-indented sibling block is skipped, but a
    # 4-space-indented `errors:` body is still detected.
    error_indent: int | None = None

    for line in lines:
        stripped = line.rstrip()
        if stripped == "errors:":
            in_errors = True
            error_indent = None
            continue
        if in_errors:
            m = _ERROR_KEY_INDENT_PATTERN.match(stripped)
            if m:
                indent = len(m.group(1))
                if error_indent is None:
                    error_indent = indent
                if indent == error_indent:
                    code = m.group(2)
                    if code in seen_codes:
                        msg = f"Duplicate error code: {code}"
                        raise ValueError(msg)
                    seen_codes.add(code)
            elif stripped and not stripped.startswith(" ") and not stripped.startswith("#"):
                in_errors = False
                error_indent = None


def _derive_type_uri(code: str) -> str:
    """Derive the RFC 7807 type URN from a SCREAMING_SNAKE error code.

    Why: type_uri is a *stable identifier* per RFC 7807 §3.1, derived
    deterministically so consumers can pattern-match on it without coupling to
    a hosted docs URL (which we explicitly out-of-scope per F004).
    """
    return f"urn:lip:error:{code.lower().replace('_', '-')}"


def _wrap_import_if_too_long(import_line: str, *, line_length: int = RUFF_LINE_LENGTH) -> str:
    """Wrap a ``from X import Y`` line in parens when single-line form exceeds line_length.

    Matches what ruff format would produce, so the generator output is
    idempotent under ``ruff format``. Without this, long imports are emitted
    on one line, ruff format wraps them, and the next codegen invocation
    re-emits the unwrapped form — breaking ``task check:errors``' drift guard.
    """
    if len(import_line) <= line_length:
        return import_line
    # "from MODULE import NAME" → "from MODULE import (\n    NAME,\n)"
    prefix, _, name = import_line.rpartition(" import ")
    return f"{prefix} import (\n    {name},\n)"


def _python_string_literal(value: str) -> str:
    """Render an arbitrary string as a valid Python double-quoted string literal.

    Why: errors.yaml may contain newlines, tabs, control characters, or unicode
    in title/detail_template values. Hand-rolled escape (replace ``\\`` then
    ``"``) misses the others and would produce invalid Python source. ``json.dumps``
    produces a valid JSON string literal which is also a valid Python string
    literal for any input — including non-ASCII characters (preserved verbatim).
    """
    return json.dumps(value, ensure_ascii=False)


def _validate_detail_template(code: str, template: str, params: _ParamsMap) -> None:
    """Validate detail_template placeholders are safe ``{name}`` references.

    Disallows positional placeholders ({0}), attribute access ({x.attr}),
    and indexing ({x[0]}). These would either fail at runtime with
    confusing IndexError/AttributeError, or — in the attribute-access case —
    expose ``str.format``'s "format string vulnerability" surface (consumers
    of attacker-controlled templates can reach ``__class__.__init__.__globals__``).

    Also asserts that every ``{name}`` placeholder corresponds to a declared
    param key — catching template/params mismatches at build time rather than
    waiting for the first request that hits ``detail()``.

    Rejects raw control characters (\\x00-\\x08, \\x0b, \\x0c, \\x0e-\\x1f,
    \\x7f). The handler chain ASCII-cleans Pydantic-error ``field`` /
    ``reason`` strings via ``ascii_safe`` before rendering them into the
    wire body, but ``ProblemDetails.detail`` is rendered straight from
    ``str.format(template, **params)`` — a control-char-laden template
    would ride into every problem+json that uses the error AND into
    dev-mode ``ConsoleRenderer`` log lines via ``error_message`` /
    ``detail`` fields. Tab and newline are permitted (``\\t`` / ``\\n``)
    so multi-line templates remain legal.
    """
    allowed_control_chars = frozenset({"\t", "\n"})
    # Single set-comprehension over ``_C0_CONTROL_UPPER`` AND ``_DEL_CHAR``
    # — symmetric with the walrus-memoised peer in
    # ``apps/backend/app/api/request_id_middleware.py`` (``(o := ord(c)) <
    # _C0_CONTROL_UPPER or o == _DEL_CHAR``). The previous ``set`` union
    # form computed the DEL branch via a literal ``"\x7f"`` and split the
    # codepoint check across two expressions, which broke the asserted
    # symmetry with the middleware's named-bound spelling.
    bad = sorted(
        ch
        for ch in template
        if ((o := ord(ch)) < _C0_CONTROL_UPPER or o == _DEL_CHAR)
        and ch not in allowed_control_chars
    )
    if bad:
        msg = (
            f"Error {code} detail_template contains control characters "
            f"{[hex(ord(c)) for c in bad]!r}; only \\t and \\n are permitted."
        )
        raise ValueError(msg)
    formatter = string.Formatter()
    referenced: set[str] = set()
    try:
        parsed = list(formatter.parse(template))
    except ValueError as exc:
        msg = f"Error {code} has malformed detail_template: {exc}"
        raise ValueError(msg) from exc
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if not field_name or field_name.isdigit():
            msg = (
                f"Error {code} detail_template uses positional placeholder "
                f"{{{field_name}}}; only named placeholders ({{name}}) are permitted."
            )
            raise ValueError(msg)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name):
            msg = (
                f"Error {code} detail_template field {{{field_name}}} contains "
                f"attribute access or indexing; only plain {{name}} placeholders are allowed."
            )
            raise ValueError(msg)
        if format_spec or conversion:
            msg = (
                f"Error {code} detail_template uses format spec / conversion "
                f"on {{{field_name}}}; only plain {{name}} placeholders are allowed."
            )
            raise ValueError(msg)
        referenced.add(field_name)

    declared = set(params)
    missing = referenced - declared
    if missing:
        msg = (
            f"Error {code} detail_template references {sorted(missing)} but "
            f"params declares {sorted(declared)}."
        )
        raise ValueError(msg)
    unused = declared - referenced
    if unused:
        # Symmetric guard: a declared-but-unused param is a typo (e.g. params
        # `retry_after` while the template references `{retry_after_seconds}`).
        # Failing loud here keeps params and template in lockstep.
        msg = (
            f"Error {code} declares params {sorted(unused)} but "
            f"detail_template never references them."
        )
        raise ValueError(msg)


def _validate_params(code: str, params: _ParamsMap) -> None:
    """Validate param types, reserved-name collisions, and identifier safety.

    Three independent checks per param:
    1. Type is one of VALID_PARAM_TYPES.
    2. Name does not collide with a reserved RFC 7807 / LIP envelope key
       (response handler crashes on kwargs collision otherwise).
    3. Name is a valid Python identifier and not a reserved keyword (the
       codegen emits ``def __init__(self, *, <name>: <type>)``, so a bad
       name produces invalid Python at class-definition time).
    """
    for param_name, param_type in params.items():
        if param_type not in VALID_PARAM_TYPES:
            msg = (
                f"Invalid param type '{param_type}' for {code}.{param_name}. "
                f"Must be one of: {', '.join(sorted(VALID_PARAM_TYPES))}"
            )
            raise ValueError(msg)
        if param_name in RESERVED_PARAM_NAMES:
            msg = (
                f"Param name '{param_name}' on {code} collides with a reserved "
                f"RFC 7807 / LIP envelope key (one of "
                f"{', '.join(sorted(RESERVED_PARAM_NAMES))}); "
                f"the response handler would crash on the kwargs collision."
            )
            raise ValueError(msg)
        if not param_name.isidentifier() or keyword.iskeyword(param_name):
            msg = (
                f"Invalid param name '{param_name}' for {code}: must be a valid "
                "Python identifier and not a reserved keyword"
            )
            raise ValueError(msg)


SUPPORTED_SCHEMA_VERSION: Final[int] = 1


_DESCRIPTION_MAX_CHARS: Final[int] = 512


def _validate_description_safe_for_docstring(code: str, description: str) -> None:
    """Reject characters that would corrupt the generated docstring.

    Description ships into a single-line triple-quoted docstring in the
    generated module. Pre-rejecting unsafe substrings at YAML-load time
    keeps the codegen template simple — instead of escape-handling at
    every render site (where a missed escape ships malformed Python
    files into source control).

    Length cap is also enforced here: a multi-paragraph description
    bloats the generated file with no reader payoff (descriptions are
    a one-line summary; the canonical detail goes in detail_template).
    """
    if len(description) > _DESCRIPTION_MAX_CHARS:
        msg = (
            f"Error {code} description exceeds {_DESCRIPTION_MAX_CHARS}-char cap "
            f"({len(description)} chars). Trim to a one-line summary; the per-instance "
            "human-readable detail belongs in detail_template, not the description."
        )
        raise ValueError(msg)
    forbidden_substrings = ('"""', "\n", "\\")
    for forbidden in forbidden_substrings:
        if forbidden in description:
            msg = (
                f"Error {code} description contains forbidden substring "
                f"{forbidden!r}; descriptions ship into the generated docstring "
                "and must be a single-line string with no embedded triple-quotes "
                "or backslashes."
            )
            raise ValueError(msg)


# PII-safe (code, param_name) pairs that may legitimately appear on 5xx
# errors. These are enum-valued strings (drawn from a closed alphabet by
# the raise site, not user-supplied free-form), so spreading them at root
# level on the wire body cannot leak operator-private data.
#
# Scoped per-code rather than as a flat name set so a name like
# ``reason`` cannot accidentally launder into a *different* 5xx error's
# string param surface. Each entry is (error_code, param_name) — a future
# error declaring ``reason`` must be re-allowlisted explicitly here, with
# an in-source comment justifying the closed-alphabet claim for that
# specific error's raise sites.
_PII_SAFE_5XX_STRING_PARAMS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        # closed enum: only "ollama" today; LIP-internal label
        ("ADAPTER_CONNECTION_FAILURE", "backend"),
        # closed enum: "timeout" / "connection_refused" / etc.
        ("ADAPTER_CONNECTION_FAILURE", "reason"),
    }
)


def _validate_no_5xx_string_params(code: str, http_status: int, params: _ParamsMap) -> None:
    """Guard against PII leakage in 5xx response bodies.

    The catch-all ``_handle_unhandled_exception`` path takes care to
    avoid leaking user-supplied strings into the response body (it
    truncates exc_message for logging only and uses the static
    InternalError detail on the wire). A typed 5xx error with a
    free-form string parameter would silently bypass that discipline —
    its detail_template spreads the param at root level on the response
    body, leaking whatever the caller passed (file paths, urls, prompt
    fragments).

    Allowlists ``_PII_SAFE_5XX_STRING_PARAMS`` as (code, param_name)
    pairs for closed-enum strings that are demonstrably PII-safe on a
    *specific* error code. New 5xx string params MUST extend that
    allowlist with explicit justification.
    """
    if http_status < HTTP_5XX_FLOOR:
        return
    forbidden = [
        name
        for name, ptype in params.items()
        if ptype == "string" and (code, name) not in _PII_SAFE_5XX_STRING_PARAMS
    ]
    if forbidden:
        allowlisted = sorted(_PII_SAFE_5XX_STRING_PARAMS)
        msg = (
            f"Error {code} is a {http_status} (5xx) with non-allowlisted string "
            f"param(s) {sorted(forbidden)!r}; 5xx response bodies must not include "
            "user-supplied free-form strings (PII discipline — see "
            "exception_handler_registry.py _handle_unhandled_exception). Use integer "
            f"params, restructure as a 4xx, or add the (code, param_name) pair "
            f"to _PII_SAFE_5XX_STRING_PARAMS (currently {allowlisted}) with "
            "justification that it carries closed-enum values only."
        )
        raise ValueError(msg)


def load_and_validate(errors_path: Path) -> _ErrorsFile:
    """Load errors.yaml and validate its contents."""
    raw_text = errors_path.read_text(encoding="utf-8")
    _detect_duplicate_keys(raw_text)

    raw_data = yaml.safe_load(raw_text)
    # The top-level ``version`` field is part of the error-contracts schema and
    # must match SUPPORTED_SCHEMA_VERSION. A future bump means the generator
    # interprets the YAML differently — we want a loud failure on rev mismatch
    # rather than silent partial-regeneration of stale code. Validate the YAML
    # is a dict (not a list / scalar / null) before we trust the cast below.
    if not isinstance(raw_data, dict):
        msg = f"errors.yaml top-level must be a mapping, got {type(raw_data).__name__}."
        raise TypeError(msg)
    data = cast("_ErrorsFile", raw_data)
    declared_version = data.get("version")
    if declared_version != SUPPORTED_SCHEMA_VERSION:
        msg = (
            f"errors.yaml declares version {declared_version!r}; "
            f"this generator only supports version {SUPPORTED_SCHEMA_VERSION}. "
            "Bump SUPPORTED_SCHEMA_VERSION in lockstep with any schema change."
        )
        raise ValueError(msg)
    errors = data.get("errors", {})

    seen_class_names: set[str] = set()
    for code, spec in errors.items():
        # Validate code format: SCREAMING_SNAKE_CASE strict. The regex
        # disallows leading/trailing underscores AND consecutive
        # underscores ("FOO__BAR" is rejected). Each segment must start
        # with an uppercase letter and may contain digits afterwards
        # ("X_42" is rejected because the second segment starts with a
        # digit). The wire-side mirror lives in
        # ``app/schemas/problem_details.py`` (the ``code`` Field
        # pattern); update both together — a drift-guard test in
        # ``apps/backend/tests/unit/exceptions/test_screaming_snake_pattern_drift_guard.py``
        # mechanically verifies they match.
        if not _SCREAMING_SNAKE_CODE_PATTERN.match(code):
            msg = (
                f"Error code must be SCREAMING_SNAKE_CASE with no leading/"
                f"trailing/double underscores: {code}"
            )
            raise ValueError(msg)

        # Validate http_status
        status = spec.get("http_status")
        if not isinstance(status, int) or not (
            HTTP_ERROR_STATUS_MIN <= status <= HTTP_ERROR_STATUS_MAX
        ):
            msg = f"Invalid HTTP status {status} for {code}. Must be 400-599."
            raise ValueError(msg)

        # Validate param types, reserved names, and identifier safety
        params = spec.get("params", {})
        _validate_params(code, params)

        # Validate required fields: title, detail_template, and description
        # (description ships as the generated class docstring; an under-specified
        # entry produced a generic fallback that drifted from the source-of-truth
        # YAML, so we enforce it).
        for required in ("title", "detail_template", "description"):
            value = spec.get(required)
            if not isinstance(value, str) or not value.strip():
                msg = (
                    f"Error {code} missing required field '{required}' "
                    f"(must be a non-empty string)."
                )
                raise ValueError(msg)

        # Description is emitted into a single-line triple-quoted docstring;
        # the dedicated helper rejects unsafe substrings + over-cap length
        # to keep the codegen template simple. Extracted to keep
        # load_and_validate's complexity under ruff's C901 ceiling.
        _validate_description_safe_for_docstring(code, spec["description"])

        # PII guard for 5xx errors — see helper docstring.
        _validate_no_5xx_string_params(code, spec["http_status"], params)

        # Validate detail_template placeholders are safe and match params.
        _validate_detail_template(code, spec["detail_template"], params)

        # Detect class-name collisions: NOT_FOUND and NOT_FOUND_ERROR both
        # produce NotFoundError, which would silently overwrite the file.
        class_name = _code_to_class_name(code)
        if class_name in seen_class_names:
            msg = (
                f"Code {code} produces class {class_name} which collides with "
                f"a previously declared error code."
            )
            raise ValueError(msg)
        seen_class_names.add(class_name)

    return data


def _normalized_docstring_description(description: str) -> str:
    """Trim trailing whitespace and append a period if the description lacks terminal punctuation.

    Without normalization, descriptions like ``Requested resource does not exist``
    render as un-punctuated docstring fragments (PEP 257: single-line docstrings
    SHOULD end with a period). Normalizing at render time keeps errors.yaml
    free of the discipline ("the spec source describes the error; punctuation
    is a presentation concern handled by the codegen").
    """
    trimmed = description.rstrip()
    if trimmed and trimmed[-1] not in ".!?":
        return trimmed + "."
    return trimmed


def _render_params_module(
    *, code: str, params_class_name: str, params: _ParamsMap, description: str | None
) -> str:
    """Render the source for a generated *_params.py module.

    The errors.yaml ``description`` is included in the params class docstring
    when present so generated code carries the human-readable context.
    """
    if description is not None:
        description = _normalized_docstring_description(description)
    fields = "\n".join(
        f"    {name}: {PARAM_TYPE_TO_PYTHON[ptype]}" for name, ptype in params.items()
    )
    # ``description`` is validated upstream against ``"""``, backslash, and
    # newline so the simple triple-quoted form below stays intact. Any
    # unsafe char would have raised at YAML-load time.
    #
    # Line-length discipline: the single-line ``"""Parameters for X: <desc>"""``
    # form is preferred when it fits in ``RUFF_LINE_LENGTH - 4`` (4 = the
    # 4-space indent at column 0 -> column 4). For long descriptions, fall
    # back to the canonical PEP 257 multi-line form so ruff's docstring
    # rules cannot reject the generated file once the project ever opts into
    # ``D`` enforcement on ``_generated/``.
    if description:
        single_line = f'"""Parameters for {code} error: {description}"""'
        if len(single_line) <= RUFF_LINE_LENGTH - 4:
            docstring = single_line
        else:
            docstring = f'"""Parameters for {code} error.\n\n    {description}\n    """'
    else:
        docstring = f'"""Parameters for {code} error."""'
    # ``frozen=True`` matches the project-wide value-object discipline:
    # every hand-written wire schema and value-object is frozen so a typed
    # error's params cannot be silently mutated between ``raise`` and the
    # ``_handle_domain_error`` boundary that renders ``detail_template``.
    return (
        '"""Generated from errors.yaml. Do not edit."""\n\n'
        "from pydantic import BaseModel, ConfigDict\n\n\n"
        f"class {params_class_name}(BaseModel):\n"
        f"    {docstring}\n\n"
        '    model_config = ConfigDict(extra="forbid", frozen=True)\n\n'
        f"{fields}\n"
    )


def _render_detail_template_decl(detail_template: str) -> str:
    """Render the ``detail_template: ClassVar[str] = "..."`` line, wrapped if long."""
    literal = _python_string_literal(detail_template)
    single_line = f"    detail_template: ClassVar[str] = {literal}"
    if len(single_line) <= RUFF_LINE_LENGTH:
        return single_line
    return f"    detail_template: ClassVar[str] = (\n        {literal}\n    )"


def _render_super_block(params_class_name: str, params: _ParamsMap) -> str:
    """Render the ``super().__init__(params=...)`` block, wrapped if long."""
    pieces = [f"{name}={name}" for name in params]
    super_line = f"        super().__init__(params={params_class_name}({', '.join(pieces)}))"
    if len(super_line) <= RUFF_LINE_LENGTH:
        return super_line + "\n"
    return (
        "        super().__init__(\n"
        f"            params={params_class_name}(\n"
        f"                {',\n                '.join(pieces)},\n"
        "            ),\n"
        "        )\n"
    )


def _render_error_module(  # noqa: PLR0913 — codegen template assembly is intentionally explicit
    *,
    code: str,
    error_class_name: str,
    http_status: int,
    type_uri: str,
    title: str,
    detail_template: str,
    params: _ParamsMap,
    params_class_name: str | None,
    params_file_stem: str | None,
    description: str | None,
) -> str:
    """Render the source for a generated *_error.py module."""
    if description is not None:
        description = _normalized_docstring_description(description)
    title_literal = _python_string_literal(title)
    detail_template_decl = _render_detail_template_decl(detail_template)
    classvars = (
        f'    code: ClassVar[str] = "{code}"\n'
        f"    http_status: ClassVar[int] = {http_status}\n"
        f'    type_uri: ClassVar[str] = "{type_uri}"\n'
        f"    title: ClassVar[str] = {title_literal}\n"
        f"{detail_template_decl}\n"
    )

    if params:
        # Invariant: when params truthy, both names are populated by the caller.
        # Use cast (not assert) so this survives `python -O`.
        params_class_name = cast("str", params_class_name)
        params_file_stem = cast("str", params_file_stem)
        super_block = _render_super_block(params_class_name, params)
        params_import = _wrap_import_if_too_long(
            f"from app.exceptions._generated.{params_file_stem} import {params_class_name}"
        )
        kw_args = ", ".join(
            f"{name}: {PARAM_TYPE_TO_PYTHON[ptype]}" for name, ptype in params.items()
        )
        # ``@override`` (PEP 698, Python 3.12+) on the generated ``__init__``
        # and ``detail`` makes a future rename of the base method a static
        # error rather than a silent shadow — the generator and the runtime
        # invariant stay in lockstep.
        # detail() body uses ``cast`` to the CONCRETE ``*Params`` class
        # (not the abstract ``BaseModel``) so the type-checker sees the
        # real per-error parameter shape — a future schema typo
        # (e.g. ``max_waiters`` -> ``maxWaiters`` in YAML) is then a
        # static error at the format-string call site instead of a
        # silent string-format failure at runtime. ``cast`` (not
        # ``assert``) so the narrowing also holds under ``python -O``.
        detail_method = (
            "    @override\n"
            "    def detail(self) -> str:\n"
            '        """Render the human-readable detail for this error."""\n'
            f'        params = cast("{params_class_name}", self.params)\n'
            "        return self.detail_template.format(**params.model_dump())\n"
        )
        # ``description`` is validated upstream to be free of ``"""``,
        # backslashes, and newlines (see _validate_description_safe_for_docstring)
        # so the simple triple-quote works without escape gymnastics.
        # The params class is imported at module scope (used at runtime by
        # ``__init__`` AND used by the typed ``cast`` in ``detail()``); the
        # earlier TYPE_CHECKING-only ``from pydantic import BaseModel`` is
        # gone now that ``cast`` targets the concrete params class instead.
        parameterized_docstring = description or f"Error: {code}."
        return (
            '"""Generated from errors.yaml. Do not edit."""\n\n'
            "from typing import ClassVar, cast, override\n\n"
            f"{params_import}\n"
            "from app.exceptions.base import DomainError\n\n\n"
            f"class {error_class_name}(DomainError):\n"
            f'    """{parameterized_docstring}"""\n\n'
            + classvars
            + "\n"
            + "    @override\n"
            + f"    def __init__(self, *, {kw_args}) -> None:\n"
            + super_block
            + "\n"
            + detail_method
        )

    # Parameterless: detail() returns the rendered detail_template (no params
    # to substitute, so the template IS the rendered detail). load_and_validate
    # asserts the template is non-empty, so the previous ``or self.title``
    # fallback was dead code that contradicted the validation invariant.
    detail_method = (
        "    @override\n"
        "    def detail(self) -> str:\n"
        '        """Render the human-readable detail for this error."""\n'
        "        return self.detail_template\n"
    )
    parameterless_docstring = description or f"Error: {code}."
    return (
        '"""Generated from errors.yaml. Do not edit."""\n\n'
        "from typing import ClassVar, override\n\n"
        "from app.exceptions.base import DomainError\n\n\n"
        f"class {error_class_name}(DomainError):\n"
        f'    """{parameterless_docstring}"""\n\n'
        + classvars
        + "\n"
        + "    @override\n"
        + "    def __init__(self) -> None:\n"
        + "        super().__init__(params=None)\n\n"
        + detail_method
    )


def generate_python(errors_path: Path, output_dir: Path) -> list[Path]:
    """Generate Python exception classes from errors.yaml.

    Cleans up orphan ``*_error.py`` / ``*_params.py`` files from previous
    generations whose source codes have since been removed from errors.yaml.
    The committed ``__init__.py`` and ``_registry.py`` are always rewritten,
    so they pick up only the current set of codes.
    """
    data = load_and_validate(errors_path)
    errors = data["errors"]
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files: list[Path] = []

    # `init_entries` stores (name, formatted_import_line) pairs so the __init__.py
    # __all__ derivation reads name directly and is robust to long imports that
    # wrap into the parenthesized form.
    init_entries: list[tuple[str, str]] = []
    registry_entries: list[tuple[str, str]] = []

    for code, spec in errors.items():
        error_class_name = _code_to_class_name(code)
        base_name = error_class_name.removesuffix("Error")
        error_file_stem = _class_to_snake(error_class_name)
        params = spec.get("params", {})

        params_class_name: str | None = None
        params_file_stem: str | None = None
        if params:
            params_class_name = f"{base_name}Params"
            params_file_stem = _class_to_snake(params_class_name)
            params_file = output_dir / f"{params_file_stem}.py"
            params_file.write_text(
                _render_params_module(
                    code=code,
                    params_class_name=params_class_name,
                    params=params,
                    description=spec.get("description"),
                ),
                encoding="utf-8",
            )
            generated_files.append(params_file)
            init_entries.append(
                (
                    params_class_name,
                    _wrap_import_if_too_long(
                        f"from app.exceptions._generated.{params_file_stem} "
                        f"import {params_class_name}"
                    ),
                )
            )

        error_file = output_dir / f"{error_file_stem}.py"
        error_file.write_text(
            _render_error_module(
                code=code,
                error_class_name=error_class_name,
                http_status=spec["http_status"],
                type_uri=_derive_type_uri(code),
                title=spec["title"],
                detail_template=spec["detail_template"],
                params=params,
                params_class_name=params_class_name,
                params_file_stem=params_file_stem,
                description=spec.get("description"),
            ),
            encoding="utf-8",
        )
        generated_files.append(error_file)
        init_entries.append(
            (
                error_class_name,
                _wrap_import_if_too_long(
                    f"from app.exceptions._generated.{error_file_stem} import {error_class_name}"
                ),
            )
        )
        registry_entries.append((code, error_class_name))

    # Generate __init__.py (sorted by name for deterministic output).
    # ``ERROR_CLASSES`` is re-exported through this aggregator so consumers
    # can ``from app.exceptions._generated import ERROR_CLASSES`` (matching
    # how every error class is reached via this surface). Without this
    # re-export, the parent ``app/exceptions/__init__.py`` would have to
    # bypass the package surface and reach into ``_registry`` directly,
    # leaving the registry as an asymmetric outlier among the otherwise-
    # uniform per-file flow through the aggregator.
    sorted_entries = sorted(init_entries, key=itemgetter(0))
    # ``_registry`` sorts before any concrete error module under ASCII order
    # (``_`` is 0x5F, ``a`` is 0x61), so emit its import FIRST and let ruff
    # treat the block as a single sorted import group. This drops the
    # historic ``I001`` per-file ignore that was needed back when the
    # registry import was tacked onto the end of an alpha-sorted block.
    init_file = output_dir / "__init__.py"
    init_content = (
        '"""Generated error classes. Do not edit."""\n\n'
        "from app.exceptions._generated._registry import ERROR_CLASSES\n"
        + "\n".join(imp for _, imp in sorted_entries)
        + "\n\n__all__ = [\n"
        '    "ERROR_CLASSES",\n'
        + "\n".join(f'    "{name}",' for name, _ in sorted_entries)
        + "\n]\n"
    )
    init_file.write_text(init_content, encoding="utf-8")
    generated_files.append(init_file)

    # Generate _registry.py (sorted, error classes only).
    #
    # ``DomainError`` is the value type of ``ERROR_CLASSES``
    # (``dict[str, type[DomainError]]``) and the concrete error classes
    # imported below subclass it; importing it at module scope alongside
    # the concrete error classes keeps the registry's type annotation
    # honest at runtime (rather than gating the base-class symbol behind
    # ``TYPE_CHECKING`` while the dict literal references concrete
    # subclasses that already pull the base class in transitively).
    registry_file = output_dir / "_registry.py"
    error_imports = sorted((name, imp) for name, imp in init_entries if name.endswith("Error"))
    sorted_registry_entries = sorted(registry_entries, key=itemgetter(0))
    # Emit ``app.exceptions._generated.*`` imports BEFORE ``app.exceptions.base``
    # so the block is in ASCII-sorted order (``_`` 0x5F < ``b`` 0x62). This
    # drops the historic ``I001`` per-file ignore that was needed when the
    # base import was emitted first.
    registry_content = (
        '"""Generated error registry. Do not edit.\n\n'
        "Maps SCREAMING_SNAKE error codes to their concrete DomainError\n"
        "subclasses. The mapping is the planned consumer-facing reverse-\n"
        "lookup surface for cases where an error code arrives as a string\n"
        "(e.g. a future relay/proxy endpoint that accepts an upstream\n"
        "consumer's typed error code and re-raises a matching DomainError\n"
        "into our handler chain). Production app/ code that raises typed\n"
        "errors from explicit class names does NOT consume this registry —\n"
        "the test backstop in tests/unit/exceptions/test_registry.py is\n"
        "the current sole consumer, pinning the dict shape so the codegen\n"
        "stays canonical until the runtime consumer lands.\n"
        '"""\n\n'
        + "\n".join(imp for _, imp in error_imports)
        + "\nfrom app.exceptions.base import DomainError\n\n"
        "ERROR_CLASSES: dict[str, type[DomainError]] = {\n"
        + "\n".join(f'    "{code}": {name},' for code, name in sorted_registry_entries)
        + "\n}\n"
    )
    registry_file.write_text(registry_content, encoding="utf-8")
    generated_files.append(registry_file)

    # Clean up orphan files: any *.py in output_dir that we didn't just write
    # AND that carries our generator sentinel marker. The sentinel guard
    # prevents an accidental wrong-output_dir invocation from wiping
    # unrelated Python files. Every emitter above starts the file with the
    # exact line ``"""Generated from errors.yaml. Do not edit."""`` (or
    # ``"""Generated error classes. Do not edit."""`` for the package
    # __init__ / ``"""Generated error registry. Do not edit.`` for the
    # registry). Match on a structural line-1 prefix (module-level
    # ``_GENERATED_SENTINEL_PREFIX``) rather than a substring-anywhere-in-
    # head so a hypothetical hand-written file whose docstring merely
    # mentions "Generated" is not eligible for unlink.
    keep = {f.name for f in generated_files}
    for stale in output_dir.glob("*.py"):
        if stale.name in keep:
            continue
        try:
            head = stale.read_text(encoding="utf-8").splitlines()[:1]
        except (OSError, UnicodeDecodeError):
            continue
        if head and head[0].startswith(_GENERATED_SENTINEL_PREFIX):
            stale.unlink()

    return generated_files


def _cli_main() -> None:
    """Run the Python codegen against the canonical errors.yaml location.

    `task errors:generate` invokes this entrypoint so the canonical
    code path lives in this module rather than a fragile inline
    `python -c` one-liner in the Taskfile.
    """
    # ``parents[1]`` is ``packages/error-contracts/`` (workspace root).
    # ``parents[3]`` is the repo root. Indexed access mirrors the test-
    # suite idiom (``Path(__file__).parents[5]`` in
    # ``test_errors_yaml_drift_guard.py``) and avoids the misleading
    # ``repo_root.parent.parent`` name-vs-depth mismatch the previous form
    # encoded.
    here = Path(__file__).resolve()
    workspace_root = here.parents[1]
    repo_root = here.parents[3]
    errors_yaml = workspace_root / "errors.yaml"
    output_dir = repo_root / "apps" / "backend" / "app" / "exceptions" / "_generated"
    generated = generate_python(errors_yaml, output_dir)
    # ``noqa: T201`` rationale: this is the codegen CLI's user-facing
    # summary line emitted when the script is invoked directly via
    # ``task errors:generate``. Wiring structlog through the codegen
    # path would over-engineer a one-shot CLI utility (and the rest of
    # the script intentionally avoids importing project-runtime
    # modules so the codegen survives a future pyright-strict bump
    # without dragging in app.core dependencies).
    print(f"Generated {len(generated)} Python error files in {output_dir}")  # noqa: T201


if __name__ == "__main__":
    _cli_main()

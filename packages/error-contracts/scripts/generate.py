"""Code generator from errors.yaml.

Primary output: Python exception classes (one file per error class plus optional
params class), wired through ``generate_python``. The Taskfile and CI invoke
only this entry point, so the generated Python tree under
``app/exceptions/_generated/`` is the canonical artifact.

Secondary outputs: ``generate_typescript`` and ``generate_required_keys`` remain
in this module but are not currently orchestrated. They are retained for future
re-introduction if a frontend or translation-validation tool ships.

Generated files are committed but never edited by hand.
"""

import json
import re
import string
from pathlib import Path

import yaml

VALID_PARAM_TYPES = {"string", "integer", "number", "boolean"}
PARAM_TYPE_TO_PYTHON = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}
PARAM_TYPE_TO_TS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
}

# RFC 7807 standard fields plus LIP project extensions plus the validation_errors
# extension array name. errors.yaml MUST NOT declare a param with any of these
# names — the response handler spreads typed params at root level alongside
# these explicit kwargs (apps/backend/app/api/errors.py::_build_body), and a
# collision raises TypeError at request time, masking the real error as a 500.
RESERVED_PARAM_NAMES = frozenset(
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
RUFF_LINE_LENGTH = 100


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
    """Convert PascalCase to snake_case. e.g. WidgetNotFoundError -> widget_not_found_error."""
    s = re.sub(r"([A-Z])", r"_\1", name).lower().lstrip("_")
    return s


def _detect_duplicate_keys(raw_text: str) -> None:
    """Detect duplicate top-level error code keys in the YAML text.

    PyYAML silently collapses duplicate mapping keys; we detect them here so
    accidental duplicates fail loud at codegen time rather than silently
    dropping one of the two entries. The regex permits trailing whitespace
    and ``# ...`` comments so common YAML formatting variants don't bypass
    the check.
    """
    lines = raw_text.split("\n")
    in_errors = False
    seen_codes: set[str] = set()
    indent_pattern = re.compile(r"^  (\w+)\s*:\s*(?:#.*)?$")

    for line in lines:
        stripped = line.rstrip()
        if stripped == "errors:":
            in_errors = True
            continue
        if in_errors:
            m = indent_pattern.match(stripped)
            if m:
                code = m.group(1)
                if code in seen_codes:
                    msg = f"Duplicate error code: {code}"
                    raise ValueError(msg)
                seen_codes.add(code)
            elif (
                stripped
                and not stripped.startswith(" ")
                and not stripped.startswith("#")
            ):
                in_errors = False


def _derive_type_uri(code: str) -> str:
    """Derive the RFC 7807 type URN from a SCREAMING_SNAKE error code.

    Why: type_uri is a *stable identifier* per RFC 7807 §3.1, derived
    deterministically so consumers can pattern-match on it without coupling to
    a hosted docs URL (which we explicitly out-of-scope per F004).
    """
    return f"urn:lip:error:{code.lower().replace('_', '-')}"


def _wrap_import_if_too_long(
    import_line: str, *, line_length: int = RUFF_LINE_LENGTH
) -> str:
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


def _validate_detail_template(code: str, template: str, params: dict) -> None:
    """Validate detail_template placeholders are safe ``{name}`` references.

    Disallows positional placeholders ({0}), attribute access ({x.attr}),
    and indexing ({x[0]}). These would either fail at runtime with
    confusing IndexError/AttributeError, or — in the attribute-access case —
    expose ``str.format``'s "format string vulnerability" surface (consumers
    of attacker-controlled templates can reach ``__class__.__init__.__globals__``).

    Also asserts that every ``{name}`` placeholder corresponds to a declared
    param key — catching template/params mismatches at build time rather than
    waiting for the first request that hits ``detail()``.
    """
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
        if field_name == "" or field_name.isdigit():
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

    declared = set(params.keys())
    missing = referenced - declared
    if missing:
        msg = (
            f"Error {code} detail_template references {sorted(missing)} but "
            f"params declares {sorted(declared)}."
        )
        raise ValueError(msg)


def load_and_validate(errors_path: Path) -> dict:
    """Load errors.yaml and validate its contents."""
    raw_text = errors_path.read_text()
    _detect_duplicate_keys(raw_text)

    data = yaml.safe_load(raw_text)
    errors = data.get("errors", {})

    seen_class_names: set[str] = set()
    for code, spec in errors.items():
        # Validate code format
        if not re.match(r"^[A-Z][A-Z0-9_]*$", code):
            msg = f"Error code must be SCREAMING_SNAKE_CASE: {code}"
            raise ValueError(msg)

        # Validate http_status
        status = spec.get("http_status")
        if not isinstance(status, int) or status < 400 or status > 599:
            msg = f"Invalid HTTP status {status} for {code}. Must be 400-599."
            raise ValueError(msg)

        # Validate param types and reserved names
        params = spec.get("params", {})
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

        # Validate RFC 7807 fields (LIP-E004-F004): both required, both strings.
        for required in ("title", "detail_template"):
            value = spec.get(required)
            if not isinstance(value, str) or not value.strip():
                msg = (
                    f"Error {code} missing required field '{required}' "
                    f"(must be a non-empty string)."
                )
                raise ValueError(msg)

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


def _render_params_module(*, code: str, params_class_name: str, params: dict) -> str:
    """Render the source for a generated *_params.py module."""
    fields = "\n".join(
        f"    {name}: {PARAM_TYPE_TO_PYTHON[ptype]}" for name, ptype in params.items()
    )
    return (
        '"""Generated from errors.yaml. Do not edit."""\n\n'
        "from pydantic import BaseModel, ConfigDict\n\n\n"
        f"class {params_class_name}(BaseModel):\n"
        f'    """Parameters for {code} error."""\n\n'
        '    model_config = ConfigDict(extra="forbid")\n\n'
        f"{fields}\n"
    )


def _render_detail_template_decl(detail_template: str) -> str:
    """Render the ``detail_template: ClassVar[str] = "..."`` line, wrapped if long."""
    literal = _python_string_literal(detail_template)
    single_line = f"    detail_template: ClassVar[str] = {literal}"
    if len(single_line) <= RUFF_LINE_LENGTH:
        return single_line
    return f"    detail_template: ClassVar[str] = (\n        {literal}\n    )"


def _render_super_block(params_class_name: str, params: dict) -> str:
    """Render the ``super().__init__(params=...)`` block, wrapped if long."""
    params_construct = ", ".join(f"{name}={name}" for name in params)
    super_line = (
        f"        super().__init__(params={params_class_name}({params_construct}))"
    )
    if len(super_line) <= RUFF_LINE_LENGTH:
        return super_line + "\n"
    params_lines = ",\n                ".join(f"{name}={name}" for name in params)
    return (
        "        super().__init__(\n"
        f"            params={params_class_name}(\n"
        f"                {params_lines},\n"
        "            ),\n"
        "        )\n"
    )


def _render_error_module(
    *,
    code: str,
    error_class_name: str,
    http_status: int,
    type_uri: str,
    title: str,
    detail_template: str,
    params: dict,
    params_class_name: str | None,
    params_file_stem: str | None,
) -> str:
    """Render the source for a generated *_error.py module."""
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
        assert params_class_name is not None  # invariant when params truthy
        assert params_file_stem is not None
        super_block = _render_super_block(params_class_name, params)
        params_import = _wrap_import_if_too_long(
            f"from app.exceptions._generated.{params_file_stem} import {params_class_name}"
        )
        kw_args = ", ".join(
            f"{name}: {PARAM_TYPE_TO_PYTHON[ptype]}" for name, ptype in params.items()
        )
        # detail() body uses `cast` (not `assert`) so the type narrowing also
        # holds under `python -O`, where `assert` is stripped. The codegen
        # invariant guarantees self.params is non-None for parameterized
        # errors; cast documents that invariant for type-checkers without
        # adding a runtime no-op.
        detail_method = (
            "    def detail(self) -> str:\n"
            '        """Render the human-readable detail for this error."""\n'
            '        params = cast("BaseModel", self.params)\n'
            "        return self.detail_template.format(**params.model_dump())\n"
        )
        return (
            '"""Generated from errors.yaml. Do not edit."""\n\n'
            "from typing import TYPE_CHECKING, ClassVar, cast\n\n"
            f"{params_import}\n"
            "from app.exceptions.base import DomainError\n\n"
            "if TYPE_CHECKING:\n"
            "    from pydantic import BaseModel\n\n\n"
            f"class {error_class_name}(DomainError):\n"
            f'    """Error: {code}."""\n\n'
            + classvars
            + "\n"
            + f"    def __init__(self, *, {kw_args}) -> None:\n"
            + super_block
            + "\n"
            + detail_method
        )

    # Parameterless: detail() returns the rendered detail_template (no params
    # to substitute, so the template IS the rendered detail). Falls back to
    # title only if detail_template is empty — which load_and_validate now
    # forbids. This honors errors.yaml's intent: the YAML's detail_template is
    # the authoritative consumer-visible string for parameterless errors too,
    # not a silently-ignored field.
    detail_method = (
        "    def detail(self) -> str:\n"
        '        """Render the human-readable detail for this error."""\n'
        "        return self.detail_template or self.title\n"
    )
    return (
        '"""Generated from errors.yaml. Do not edit."""\n\n'
        "from typing import ClassVar\n\n"
        "from app.exceptions.base import DomainError\n\n\n"
        f"class {error_class_name}(DomainError):\n"
        f'    """Error: {code}."""\n\n'
        + classvars
        + "\n"
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
                )
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
            )
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
    sorted_entries = sorted(init_entries, key=lambda pair: pair[0])
    init_file = output_dir / "__init__.py"
    init_content = (
        '"""Generated error classes. Do not edit."""\n\n'
        + "\n".join(imp for _, imp in sorted_entries)
        + "\n\n__all__ = [\n"
        + "\n".join(f'    "{name}",' for name, _ in sorted_entries)
        + "\n]\n"
    )
    init_file.write_text(init_content)
    generated_files.append(init_file)

    # Generate _registry.py (sorted, error classes only).
    registry_file = output_dir / "_registry.py"
    error_imports = sorted(
        (name, imp) for name, imp in init_entries if name.endswith("Error")
    )
    sorted_registry_entries = sorted(registry_entries, key=lambda pair: pair[0])
    registry_content = (
        '"""Generated error registry. Do not edit."""\n\n'
        "from __future__ import annotations\n\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from app.exceptions.base import DomainError\n\n"
        + "\n".join(imp for _, imp in error_imports)
        + "\n\n"
        "ERROR_CLASSES: dict[str, type[DomainError]] = {\n"
        + "\n".join(f'    "{code}": {name},' for code, name in sorted_registry_entries)
        + "\n}\n"
    )
    registry_file.write_text(registry_content)
    generated_files.append(registry_file)

    # Clean up orphan files: any *.py in output_dir that we didn't just write.
    # Preserves __init__.py / _registry.py (they ARE in generated_files now).
    keep = {f.name for f in generated_files}
    for stale in output_dir.glob("*.py"):
        if stale.name not in keep:
            stale.unlink()

    return generated_files


def generate_typescript(errors_path: Path, output_path: Path) -> Path:
    """Generate TypeScript types from errors.yaml."""
    data = load_and_validate(errors_path)
    errors = data["errors"]

    codes_array = ", ".join(f'"{code}"' for code in errors)

    params_entries: list[str] = []
    status_entries: list[str] = []
    for code, spec in errors.items():
        params = spec.get("params", {})
        if params:
            fields = "; ".join(
                f"{name}: {PARAM_TYPE_TO_TS[ptype]}" for name, ptype in params.items()
            )
            params_entries.append(f"  {code}: {{ {fields} }};")
        else:
            params_entries.append(f"  {code}: Record<string, never>;")
        status_entries.append(f"  {code}: {spec['http_status']},")

    content = (
        "// THIS FILE IS GENERATED FROM errors.yaml\n"
        "// DO NOT EDIT BY HAND. Run `task errors:generate` to regenerate.\n\n"
        f"export type ErrorCode =\n  | {'\n  | '.join(f'"{code}"' for code in errors)};\n\n"
        "export interface ErrorParamsByCode {\n" + "\n".join(params_entries) + "\n}\n\n"
        "export interface ApiErrorPayload<C extends ErrorCode = ErrorCode> {\n"
        "  code: C;\n"
        "  params: ErrorParamsByCode[C];\n"
        "  details: Array<{ field: string; reason: string }> | null;\n"
        "  request_id: string;\n"
        "}\n\n"
        f"export const ERROR_CODES: readonly ErrorCode[] = [{codes_array}] as const;\n\n"
        "export const HTTP_STATUS_BY_CODE: Record<ErrorCode, number> = {\n"
        + "\n".join(status_entries)
        + "\n};\n"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    return output_path


def generate_required_keys(errors_path: Path, output_path: Path) -> Path:
    """Generate required-keys.json for translation validation."""
    data = load_and_validate(errors_path)
    errors = data["errors"]

    keys = list(errors.keys())
    params_by_key = {
        code: list(spec.get("params", {}).keys()) for code, spec in errors.items()
    }

    result = {
        "version": 1,
        "namespace": "errors",
        "keys": keys,
        "params_by_key": params_by_key,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return output_path

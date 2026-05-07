"""Tests for the error contracts code generator."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Direct-test import for the control-char defense — PyYAML rejects most
# C0 controls at parse time, so going through load_and_validate would not
# exercise the in-codegen layer. Private-symbol access is justified.
from scripts.generate import _validate_detail_template

if TYPE_CHECKING:
    from collections.abc import Callable


def _load_class_to_snake() -> Callable[[str], str]:
    """Import generate.py by file path so the private ``_class_to_snake``
    helper can be exercised directly without rewiring the package as
    importable. Returns the bound function rather than the module so the
    type of the call site is precise."""
    generate_py = Path(__file__).resolve().parents[1] / "scripts" / "generate.py"
    spec = importlib.util.spec_from_file_location("_generate_for_test", generate_py)
    assert spec is not None, generate_py
    assert spec.loader is not None, generate_py
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_generate_for_test", module)
    spec.loader.exec_module(module)
    return getattr(module, "_class_to_snake")  # noqa: B009 — getattr to silence type-checker on dynamic-load


@pytest.mark.parametrize(
    ("pascal", "expected_snake"),
    [
        ("QueueFullError", "queue_full_error"),
        ("RateLimitedParams", "rate_limited_params"),
        ("WidgetNotFoundError", "widget_not_found_error"),
        ("InternalError", "internal_error"),
        ("ModelCapabilityNotSupportedError", "model_capability_not_supported_error"),
    ],
)
def test_class_to_snake_pins_pascal_case_translation(pascal: str, expected_snake: str) -> None:
    """``_class_to_snake`` is the codegen's PascalCase -> snake_case helper.

    Every generated file stem flows through this helper, so its contract is
    load-bearing across the whole error-system codegen. Pinning the
    translation here surfaces a future regex tweak (e.g. handling acronym
    runs like ``OAuth2Error``) as a focused unit-test failure, not as a
    confusing late-stage drift in ``check:errors``.
    """
    class_to_snake = _load_class_to_snake()
    assert class_to_snake(pascal) == expected_snake


SAMPLE_YAML = """
version: 1
errors:
  NOT_FOUND:
    http_status: 404
    description: Resource not found
    title: Not Found
    detail_template: The requested resource does not exist.
    params: {}
  EXAMPLE_NOT_FOUND:
    http_status: 404
    description: Widget not found
    title: Widget Not Found
    detail_template: "Widget {widget_id} does not exist."
    params:
      widget_id: string
  EXAMPLE_NAME_TOO_LONG:
    http_status: 422
    description: Name too long
    title: Name Too Long
    detail_template: "Field {name} length {actual_length} exceeds the maximum of {max_length}."
    params:
      name: string
      max_length: integer
      actual_length: integer
  INTERNAL_ERROR:
    http_status: 500
    description: Sample internal error for codegen test
    title: Internal Server Error
    detail_template: An unexpected error occurred. The request_id can be used for log correlation.
    params: {}
"""

DUPLICATE_YAML = """
version: 1
errors:
  NOT_FOUND:
    http_status: 404
    description: First
    params: {}
  NOT_FOUND:
    http_status: 404
    description: Duplicate
    params: {}
"""

INVALID_STATUS_YAML = """
version: 1
errors:
  BAD_ERROR:
    http_status: 200
    description: Not an error status
    params: {}
"""

INVALID_PARAM_TYPE_YAML = """
version: 1
errors:
  BAD_PARAMS:
    http_status: 400
    description: Bad param type
    params:
      items: list
"""


@pytest.fixture
def sample_errors_path(tmp_path: Path) -> Path:
    """Write sample errors.yaml and return its path."""
    path = tmp_path / "errors.yaml"
    path.write_text(SAMPLE_YAML)
    return path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Create and return a temporary output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return out


def test_codegen_produces_valid_python(sample_errors_path: Path, output_dir: Path) -> None:
    """Codegen should produce one .py file per error class."""
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    # Should produce: not_found_error.py, example_not_found_error.py,
    # example_not_found_params.py, example_name_too_long_error.py,
    # example_name_too_long_params.py, internal_error.py, __init__.py, _registry.py
    assert (output_dir / "not_found_error.py").exists()
    assert (output_dir / "example_not_found_error.py").exists()
    assert (output_dir / "example_not_found_params.py").exists()
    assert (output_dir / "example_name_too_long_error.py").exists()
    assert (output_dir / "example_name_too_long_params.py").exists()
    assert (output_dir / "internal_error.py").exists()
    assert (output_dir / "__init__.py").exists()
    assert (output_dir / "_registry.py").exists()

    # Verify content of a parameterized error using full-line equality checks
    # so the assertions cannot be satisfied by docstring/comment text alone.
    content = (output_dir / "example_not_found_error.py").read_text()
    assert "class ExampleNotFoundError(DomainError):" in content
    assert 'code: ClassVar[str] = "EXAMPLE_NOT_FOUND"' in content
    assert "http_status: ClassVar[int] = 404" in content
    assert "def __init__(self, *, widget_id: str) -> None:" in content

    # Verify the special-case branch in _code_to_class_name: codes ending in
    # _ERROR must NOT get a doubled "ErrorError" suffix.
    internal_content = (output_dir / "internal_error.py").read_text()
    assert "class InternalError(DomainError):" in internal_content
    assert "InternalErrorError" not in internal_content
    assert 'code: ClassVar[str] = "INTERNAL_ERROR"' in internal_content
    assert "http_status: ClassVar[int] = 500" in internal_content

    # __init__.py: confirm the import line and __all__ entry for at least one
    # generated error class are present in the exact format the generator emits.
    init_content = (output_dir / "__init__.py").read_text()
    assert (
        "from app.exceptions._generated.example_not_found_error import ExampleNotFoundError"
        in init_content
    )
    assert '    "ExampleNotFoundError",' in init_content

    # _registry.py: confirm an ERROR_CLASSES entry is emitted for at least one code.
    registry_content = (output_dir / "_registry.py").read_text()
    assert '    "EXAMPLE_NOT_FOUND": ExampleNotFoundError,' in registry_content

    # Params file: confirm the BaseModel class declaration and the str/int field
    # mappings (string -> str, integer -> int) are present.
    params_content = (output_dir / "example_name_too_long_params.py").read_text()
    assert "class ExampleNameTooLongParams(BaseModel):" in params_content
    assert "    name: str" in params_content
    assert "    max_length: int" in params_content

    # Compile-check every generated .py file. This catches syntax bugs in the
    # multi-line super().__init__ branch that string-substring checks miss.
    for py_file in output_dir.glob("*.py"):
        src = py_file.read_text()
        try:
            ast.parse(src)
        except SyntaxError as e:
            pytest.fail(f"Generated file {py_file.name} has syntax error: {e}")


def test_codegen_rejects_duplicate_codes(tmp_path: Path) -> None:
    """Codegen should reject YAML with duplicate error codes."""
    # YAML spec merges duplicate keys silently, so we detect via custom loader
    path = tmp_path / "errors.yaml"
    path.write_text(DUPLICATE_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"Duplicate error code: NOT_FOUND"):
        load_and_validate(path)


def test_codegen_rejects_invalid_http_status(tmp_path: Path) -> None:
    """Codegen should reject error codes with non-error HTTP status."""
    path = tmp_path / "errors.yaml"
    path.write_text(INVALID_STATUS_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(
        ValueError, match=r"Invalid HTTP status 200 for BAD_ERROR\. Must be 400-599\."
    ):
        load_and_validate(path)


def test_codegen_rejects_invalid_param_type(tmp_path: Path) -> None:
    """Codegen should reject params with unsupported types."""
    path = tmp_path / "errors.yaml"
    path.write_text(INVALID_PARAM_TYPE_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"Invalid param type 'list' for BAD_PARAMS\.items\."):
        load_and_validate(path)


# ─────────────────────────────────────────────────────────────────────────────
# RFC 7807 fields: title, detail_template, type_uri, detail()
# Added by LIP-E004-F004.
# ─────────────────────────────────────────────────────────────────────────────


def test_codegen_emits_title_and_type_uri_classvars(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Each generated error class declares title and type_uri as ClassVars."""
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    # Parameterized error
    content = (output_dir / "example_not_found_error.py").read_text()
    assert 'title: ClassVar[str] = "Widget Not Found"' in content
    assert 'type_uri: ClassVar[str] = "urn:lip:error:example-not-found"' in content

    # Parameterless generic error — keeps the InternalError special case
    internal_content = (output_dir / "internal_error.py").read_text()
    assert 'title: ClassVar[str] = "Internal Server Error"' in internal_content
    assert 'type_uri: ClassVar[str] = "urn:lip:error:internal-error"' in internal_content


def test_codegen_emits_detail_method_with_template_substitution(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Codegen emits detail() that formats detail_template with params for parameterized errors."""
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    content = (output_dir / "example_not_found_error.py").read_text()
    assert 'detail_template: ClassVar[str] = "Widget {widget_id} does not exist."' in content
    assert "def detail(self) -> str:" in content
    # Parameterized branch type-narrows via cast (survives `python -O`) then
    # formats. The cast targets the CONCRETE *Params class so a future
    # schema typo is a static error at the format-string call site, not a
    # silent string-format failure at runtime.
    assert 'cast("ExampleNotFoundParams", self.params)' in content
    assert "params.model_dump()" in content


def test_codegen_emits_detail_method_returning_detail_template_for_parameterless(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Parameterless errors' detail() returns detail_template directly.

    The previous template generated ``self.detail_template or self.title`` as
    a defensive fallback; load_and_validate already enforces a non-empty
    detail_template so the fallback was dead code that contradicted the
    invariant. The generator now emits the bare ``return self.detail_template``.
    """
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    content = (output_dir / "internal_error.py").read_text()
    assert "def detail(self) -> str:" in content
    assert "return self.detail_template\n" in content
    assert "return self.detail_template or self.title" not in content


def test_codegen_derives_kebab_type_uri_from_screaming_snake_code(
    tmp_path: Path, output_dir: Path
) -> None:
    """type_uri = urn:lip:error:<code.lower().replace('_', '-')> — verify across codes."""
    yaml_text = """
version: 1
errors:
  QUEUE_FULL:
    http_status: 503
    description: Queue full
    title: Queue Full
    detail_template: "queue is full"
    params: {}
  ADAPTER_CONNECTION_FAILURE:
    http_status: 502
    description: Adapter failure
    title: Adapter Failure
    detail_template: "adapter failed"
    params: {}
  MODEL_CAPABILITY_NOT_SUPPORTED:
    http_status: 422
    description: Capability missing
    title: Capability Missing
    detail_template: "missing capability"
    params: {}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import generate_python

    generate_python(path, output_dir)

    qf = (output_dir / "queue_full_error.py").read_text()
    assert 'type_uri: ClassVar[str] = "urn:lip:error:queue-full"' in qf

    acf = (output_dir / "adapter_connection_failure_error.py").read_text()
    assert 'type_uri: ClassVar[str] = "urn:lip:error:adapter-connection-failure"' in acf

    mcns = (output_dir / "model_capability_not_supported_error.py").read_text()
    assert 'type_uri: ClassVar[str] = "urn:lip:error:model-capability-not-supported"' in mcns


def test_codegen_rejects_missing_title(tmp_path: Path) -> None:
    """Codegen requires title on every error (RFC 7807 standard field)."""
    yaml_text = """
version: 1
errors:
  NO_TITLE:
    http_status: 400
    description: Missing title field
    detail_template: "x"
    params: {}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"NO_TITLE.*missing required field 'title'"):
        load_and_validate(path)


def test_codegen_rejects_missing_detail_template(tmp_path: Path) -> None:
    """Codegen requires detail_template on every error."""
    yaml_text = """
version: 1
errors:
  NO_TEMPLATE:
    http_status: 400
    description: Missing template
    title: No Template
    params: {}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"NO_TEMPLATE.*missing required field 'detail_template'"):
        load_and_validate(path)


def test_codegen_rejects_missing_description(tmp_path: Path) -> None:
    """Codegen requires description on every error.

    Symmetric with the missing-title and missing-detail_template tests
    above. Without this test a regression that drops ``description``
    from the required-fields tuple would silently make descriptions
    optional, and the codegen would emit fallback ``Error: CODE.``-style
    docstrings that drift from any source of truth.
    """
    yaml_text = """
version: 1
errors:
  NO_DESC:
    http_status: 400
    title: No Description
    detail_template: "x"
    params: {}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"NO_DESC.*missing required field 'description'"):
        load_and_validate(path)


def test_codegen_rejects_description_over_cap(tmp_path: Path) -> None:
    """Codegen enforces the 512-char cap on description.

    Pinning the cap from the backend side reciprocally enforces the
    codegen contract — a future relaxation in the codegen would also
    have to relax this test, surfacing the behavior change in a
    review-able diff rather than as silent multi-paragraph descriptions
    flowing into generated docstrings.
    """
    long_description = "x" * 513
    yaml_text = f"""
version: 1
errors:
  TOO_LONG_DESC:
    http_status: 400
    description: "{long_description}"
    title: Too Long
    detail_template: "x"
    params: {{}}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"TOO_LONG_DESC.*description exceeds 512-char cap"):
        load_and_validate(path)


def test_codegen_emits_template_format_call_for_parameterized_errors(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Parameterized error's detail() body uses str.format(**params.model_dump()) via a cast."""
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    content = (output_dir / "example_not_found_error.py").read_text()
    # Body type-narrows via cast (survives `python -O`) then renders the
    # template. The cast targets the CONCRETE *Params class.
    assert 'params = cast("ExampleNotFoundParams", self.params)' in content
    assert "self.detail_template.format(**params.model_dump())" in content


def test_codegen_emits_detail_template_for_parameterless_errors(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Parameterless error's detail() returns detail_template directly.

    load_and_validate now requires a non-empty ``detail_template`` for every
    error (parameterless or not), so the previous ``or self.title`` fallback
    was dead code and is no longer emitted by the codegen.
    """
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    content = (output_dir / "internal_error.py").read_text()
    assert "return self.detail_template\n" in content
    # No template-substitution path (no params to substitute).
    assert "params.model_dump()" not in content


def test_codegen_emits_extra_forbid_and_frozen_on_params_classes(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Generated *_params.py classes declare extra='forbid' and frozen=True.

    extra='forbid' fails loudly on consumer typos; frozen=True matches the
    project-wide value-object discipline (every hand-written wire schema and
    value-object is frozen, so a typed error's params cannot be silently
    mutated between ``raise`` and the ``_handle_domain_error`` boundary that
    renders the detail_template).
    """
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    content = (output_dir / "example_not_found_params.py").read_text()
    assert 'model_config = ConfigDict(extra="forbid", frozen=True)' in content
    assert "from pydantic import BaseModel, ConfigDict" in content


def test_codegen_rejects_reserved_param_names(tmp_path: Path) -> None:
    """errors.yaml params named after RFC 7807 / LIP envelope keys are rejected at codegen."""
    yaml_text = """
version: 1
errors:
  COLLIDES_WITH_STATUS:
    http_status: 500
    description: Collides
    title: Collides
    detail_template: "x {status}"
    params:
      status: integer
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"Param name 'status'.*reserved"):
        load_and_validate(path)


@pytest.mark.parametrize(
    ("bad_name", "match_fragment"),
    [
        # Python reserved keyword — emitting `def __init__(self, *, class:
        # str)` would be a SyntaxError. Without this branch test, a
        # regression dropping the ``keyword.iskeyword`` arm from
        # _validate_params would only surface when codegen runs on a YAML
        # adding a keyword param.
        pytest.param("class", "Invalid param name 'class'", id="reserved-keyword"),
        # Non-identifier (digit-leading) — emitting `def __init__(self, *,
        # 1bad: str)` would be a SyntaxError. Without this branch test, a
        # regression dropping the ``isidentifier`` arm would silently
        # ship broken Python.
        pytest.param("1bad", "Invalid param name '1bad'", id="leading-digit"),
        # Non-identifier (hyphen) — same regression class as above.
        pytest.param("bad-name", "Invalid param name 'bad-name'", id="hyphen-in-name"),
    ],
)
def test_codegen_rejects_invalid_param_identifiers(
    tmp_path: Path, bad_name: str, match_fragment: str
) -> None:
    """_validate_params rejects names that aren't valid Python identifiers
    or that are reserved keywords; both arms cover separate regression classes
    (the codegen would otherwise emit invalid Python at the
    ``def __init__(self, *, <name>: <type>)`` line).
    """
    yaml_text = f"""
version: 1
errors:
  BAD_PARAM_NAME:
    http_status: 400
    description: Bad param name test
    title: Bad Param
    detail_template: "v"
    params:
      "{bad_name}": string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=match_fragment):
        load_and_validate(path)


@pytest.mark.parametrize(
    "bad_substring",
    [
        # Embedded triple-quote — would close the generated docstring
        # early and corrupt the rendered Python module.
        pytest.param('a"""b', id="embedded-triple-quote"),
        # Embedded backslash — interpreted by Python's docstring parser
        # as an escape sequence; can produce SyntaxWarning or change the
        # rendered character.
        pytest.param("a\\b", id="embedded-backslash"),
    ],
)
def test_codegen_rejects_description_with_forbidden_substrings(
    tmp_path: Path, bad_substring: str
) -> None:
    """_validate_description_safe_for_docstring rejects substrings that
    would corrupt the generated single-line docstring (triple-quote /
    backslash). PyYAML safe_load handles the embedded-newline case
    naturally (it would parse as a multi-line string and the substring
    check still triggers), so this test focuses on the two "looks
    fine in YAML, breaks in Python" failure modes.
    """
    # Build the YAML by escaping the backslash for safe_load — embedding
    # the literal char into the YAML string is what we test against.
    description_yaml_value = bad_substring.replace("\\", "\\\\").replace('"', '\\"')
    yaml_text = f"""
version: 1
errors:
  BAD_DESC:
    http_status: 400
    description: "{description_yaml_value}"
    title: Bad Desc
    detail_template: "v"
    params: {{}}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match="forbidden substring"):
        load_and_validate(path)


@pytest.mark.parametrize(
    ("bad_template", "match_fragment"),
    [
        # `{x:>10}` is a format spec — would be honored by str.format and
        # could enable padding-based amplification or surprise in detail
        # output. The codegen forbids it for parity with the
        # attribute-access / positional-placeholder rejections.
        pytest.param("v {x:>10}", "format spec / conversion", id="format-spec-padding"),
        # `{x!r}` is a conversion — would change the rendered output to
        # repr() of the param value, leaking quoted strings (and
        # arbitrary attribute access via repr() on custom types).
        pytest.param("v {x!r}", "format spec / conversion", id="conversion-repr"),
    ],
)
def test_codegen_rejects_template_format_specs_and_conversions(
    tmp_path: Path, bad_template: str, match_fragment: str
) -> None:
    """_validate_detail_template rejects format specs and conversions on
    placeholders. Closes the third arm of the placeholder-safety guard
    (the other two — positional, attribute-access — already have branch
    tests at lines 516+ and 538+).
    """
    yaml_text = f"""
version: 1
errors:
  BAD_TEMPLATE_FORMAT:
    http_status: 400
    description: Bad template format spec test
    title: Bad Template
    detail_template: "{bad_template}"
    params:
      x: string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=match_fragment):
        load_and_validate(path)


def test_codegen_rejects_title_over_cap(tmp_path: Path) -> None:
    """Codegen enforces the 128-char cap on title (matches ProblemDetails wire schema).

    Symmetric with test_codegen_rejects_description_over_cap. Without
    this codegen-time check, a YAML edit setting a 200-char title would
    pass load_and_validate, generate a working *_error.py module, and
    only fail at request time when the wire-schema validator on
    ProblemDetails.title rejected the over-cap value — silently demoting
    the typed error into the catch-all 500 InternalError.
    """
    long_title = "x" * 129
    yaml_text = f"""
version: 1
errors:
  TOO_LONG_TITLE:
    http_status: 400
    description: ok
    title: "{long_title}"
    detail_template: "x"
    params: {{}}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"TOO_LONG_TITLE.*title exceeds 128-char cap"):
        load_and_validate(path)


def test_codegen_rejects_positional_template_placeholders(tmp_path: Path) -> None:
    """detail_template with positional placeholders ({0}) is rejected at codegen."""
    yaml_text = """
version: 1
errors:
  POSITIONAL:
    http_status: 400
    description: Positional
    title: Positional
    detail_template: "value {0}"
    params:
      x: string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"positional placeholder"):
        load_and_validate(path)


def test_codegen_rejects_attribute_access_in_template(tmp_path: Path) -> None:
    """detail_template with attribute access ({x.attr}) is rejected at codegen."""
    yaml_text = """
version: 1
errors:
  ATTR_ACCESS:
    http_status: 400
    description: Attr access
    title: Attr Access
    detail_template: "value {x.__class__}"
    params:
      x: string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"attribute access or indexing"):
        load_and_validate(path)


def test_codegen_rejects_template_referencing_undeclared_param(
    tmp_path: Path,
) -> None:
    """detail_template referencing a placeholder absent from params is rejected at codegen."""
    yaml_text = """
version: 1
errors:
  MISMATCHED:
    http_status: 400
    description: Mismatched
    title: Mismatched
    detail_template: "saw {present} but template wants {missing}"
    params:
      present: string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(
        ValueError, match=r"references \['missing'\] but params declares \['present'\]"
    ):
        load_and_validate(path)


def test_codegen_cleans_up_orphan_files(tmp_path: Path, output_dir: Path) -> None:
    """When a code is removed from errors.yaml, its generated files are deleted on regeneration."""
    from scripts.generate import generate_python

    initial_yaml = """
version: 1
errors:
  KEPT:
    http_status: 400
    description: Will stay
    title: Kept
    detail_template: "kept"
    params: {}
  REMOVED:
    http_status: 400
    description: Will be removed
    title: Removed
    detail_template: "removed"
    params: {}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(initial_yaml)
    generate_python(path, output_dir)
    assert (output_dir / "removed_error.py").exists()
    assert (output_dir / "kept_error.py").exists()

    # Drop REMOVED from the YAML and regenerate.
    updated_yaml = """
version: 1
errors:
  KEPT:
    http_status: 400
    description: Will stay
    title: Kept
    detail_template: "kept"
    params: {}
"""
    path.write_text(updated_yaml)
    generate_python(path, output_dir)
    assert (output_dir / "kept_error.py").exists()
    assert not (output_dir / "removed_error.py").exists(), (
        "Codegen must clean up orphaned files when a code is removed from errors.yaml."
    )


def test_codegen_handles_special_chars_in_title_and_template(
    tmp_path: Path, output_dir: Path
) -> None:
    """Newlines, tabs, quotes, and unicode in title/detail_template don't break codegen."""
    yaml_text = """
version: 1
errors:
  WEIRD:
    http_status: 400
    description: Weird chars
    title: "A\\tB\\n\\"C\\""
    detail_template: "Got value=\\"{x}\\" — non-ASCII: \\u00e9"
    params:
      x: string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import generate_python

    generate_python(path, output_dir)
    # File compiles cleanly under ast.parse — proof the literal is valid Python.
    src = (output_dir / "weird_error.py").read_text()
    ast.parse(src)
    # The unicode character round-trips through json.dumps(ensure_ascii=False).
    assert "é" in src


def test_codegen_rejects_template_with_unused_declared_param(tmp_path: Path) -> None:
    """params declaring a name the detail_template never references is rejected.

    The lockstep partner of test_codegen_rejects_template_referencing_undeclared_param.
    A YAML edit that adds a param but forgets the corresponding template
    reference (or renames the placeholder and leaves the param behind) is a
    silent data-loss bug — the typed param ships in the response body but
    the rendered ``detail`` never names it. The codegen rejects this at
    build time so the contributor is forced to keep both halves in lockstep.
    """
    yaml_text = """
version: 1
errors:
  ORPHAN_PARAM:
    http_status: 400
    description: Orphan param
    title: Orphan
    detail_template: "saw {present}"
    params:
      present: string
      unused: integer
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(
        ValueError, match=r"declares params \['unused'\] but detail_template never references"
    ):
        load_and_validate(path)


@pytest.mark.parametrize(
    "control_char",
    ["\x00", "\x01", "\x07", "\x0b", "\x0c", "\x1f", "\x7f"],
)
def test_codegen_rejects_control_chars_in_detail_template(control_char: str) -> None:
    """Control bytes in a detail_template are rejected at codegen validation.

    Control bytes (``\\x00``..``\\x1f`` excluding the ``\\t``/``\\n``
    whitespace carve-outs, and ``\\x7f`` DEL) would ride from the YAML
    template into the rendered ``detail`` field on the wire body AND into
    dev-mode ConsoleRenderer log lines (the runtime ``ascii_safe``
    discipline applied to user-input does NOT cover template-rendered
    detail). The validator must reject this. (PyYAML's safe_load itself
    rejects most C0 controls at parse time, so this test calls
    ``_validate_detail_template`` directly to exercise the in-codegen
    defense-in-depth layer.)
    """
    template = f"before{control_char}after"
    with pytest.raises(ValueError, match="control character"):
        _validate_detail_template("CONTROL_CHARS", template, {})


@pytest.mark.parametrize(
    "whitespace_char",
    ["\t", "\n"],
)
def test_codegen_accepts_whitespace_chars_in_detail_template(whitespace_char: str) -> None:
    """Tab/newline are accepted in detail templates (counter-test for the control-char rejector).

    The validator returns ``None`` on success; binding the return value to
    a local + asserting ``is None`` enforces the "no test without an
    explicit assertion" sacred rule (a future regression that made the
    validator return a Match-like sentinel would still trip a CLAUDE.md
    "Never write a test with no assertions" test that bound only on the
    "must not raise" comment.)
    """
    template = f"before{whitespace_char}after"
    result = _validate_detail_template("WHITESPACE_OK", template, {})
    assert result is None


def test_codegen_rejects_5xx_with_non_allowlisted_string_param(tmp_path: Path) -> None:
    """5xx errors with non-allowlisted free-form string params are rejected.

    The catch-all 500 handler takes care to never leak user-supplied
    strings into the response body. A typed 5xx with a free-form string
    param would silently bypass that discipline by spreading the param at
    root level on the wire body — leaking whatever the caller passed.
    The codegen must reject the YAML at build time so a future error
    cannot regress this PII discipline. (PII guard in
    ``scripts/generate.py:_validate_no_5xx_string_params``.)
    """
    yaml_text = """
version: 1
errors:
  LEAKY_INTERNAL_ERROR:
    http_status: 500
    description: A 5xx with a free-form string
    title: Leaky 5xx
    detail_template: "Failed: {file_path}"
    params:
      file_path: string
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match="must not include user-supplied free-form strings"):
        load_and_validate(path)


def test_codegen_accepts_5xx_with_integer_param(tmp_path: Path) -> None:
    """A 5xx error with only integer params passes the PII guard (counter-test)."""
    yaml_text = """
version: 1
errors:
  COUNTED_INTERNAL_ERROR:
    http_status: 500
    description: A 5xx with only integer params
    title: Counted 5xx
    detail_template: "Failed after {attempts} attempts"
    params:
      attempts: integer
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import load_and_validate

    loaded = load_and_validate(path)
    # Pin the post-condition: the loader returned the parsed YAML mapping
    # with the integer-only error definition intact. Without this assert,
    # a future regression that made ``load_and_validate`` no-op on success
    # (returning ``None``) would still pass a "must not raise" stub test.
    assert "COUNTED_INTERNAL_ERROR" in loaded["errors"]
    assert loaded["errors"]["COUNTED_INTERNAL_ERROR"]["params"] == {"attempts": "integer"}


def test_codegen_does_not_unlink_files_without_generator_sentinel(
    tmp_path: Path, output_dir: Path
) -> None:
    """Hand-written sibling files in output_dir survive regeneration.

    The orphan-cleanup safeguard at ``scripts/generate.py`` keys on the
    ``Generated`` sentinel prefix in the docstring of every codegen
    output. A hand-authored module sitting next to generated files (e.g.
    a future ``app/exceptions/_generated/_typed_alias.py`` from a
    contributor adding a manual helper) must NOT be unlinked even if its
    name is not in the keep-set. This is the only protection between the
    codegen and irreversible ``unlink()`` of user-authored code.
    """
    yaml_text = """
version: 1
errors:
  KEPT:
    http_status: 400
    description: Will stay
    title: Kept
    detail_template: "kept"
    params: {}
"""
    path = tmp_path / "errors.yaml"
    path.write_text(yaml_text)

    from scripts.generate import generate_python

    # Pre-create a hand-authored sibling whose first line is NOT the
    # codegen sentinel. The orphan-cleanup pass must skip it.
    hand_authored = output_dir / "hand_authored.py"
    hand_authored.write_text('"""Hand-authored helper, not generated."""\nVALUE = 42\n')

    generate_python(path, output_dir)

    assert hand_authored.exists(), (
        "Codegen orphan-cleanup MUST skip files without the generator sentinel — "
        "otherwise a wrong output_dir invocation could wipe unrelated user code."
    )
    # Sanity: the kept code IS generated.
    assert (output_dir / "kept_error.py").exists()


def test_str_format_raises_keyerror_when_template_placeholder_absent_from_params() -> None:
    """The codegen's detail() body relies on str.format raising KeyError when a
    detail_template references a placeholder that the params model does not
    declare. This is the visibility mechanism for the developer error
    'errors.yaml template/params mismatch' — exercising the semantic here is
    sufficient because the generated body is one statement: ``return
    self.detail_template.format(**self.params.model_dump())``.
    """
    template = "Saw {present} but template wants {missing}."
    params_dump = {"present": "x"}
    with pytest.raises(KeyError, match="missing"):
        template.format(**params_dump)


# LIP-E004-F004 follow-up: codegen now pre-validates template/params alignment
# at build time (load_and_validate uses string.Formatter().parse to compare
# placeholders against declared params). A mismatched errors.yaml entry is
# rejected before any file is written. The original "permitted at codegen,
# discovered at runtime" choice is replaced by build-time enforcement; the
# rejection path is exercised by
# test_codegen_rejects_template_referencing_undeclared_param above.

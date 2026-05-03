"""Tests for the error contracts code generator."""

import ast
from pathlib import Path

import pytest

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

# Errors.yaml fragment used by test_codegen_detail_raises_keyerror_on_template_param_mismatch
# to verify the detail() method reports a developer error when the template references
# a placeholder that the params model does not declare.
MISMATCHED_TEMPLATE_YAML = """
version: 1
errors:
  TEMPLATE_MISMATCH:
    http_status: 400
    description: Template references unknown placeholder
    title: Template Mismatch
    detail_template: "Saw {present} but template wants {missing}."
    params:
      present: string
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


def test_codegen_rejects_duplicate_codes(tmp_path: Path, output_dir: Path) -> None:
    """Codegen should reject YAML with duplicate error codes."""
    # YAML spec merges duplicate keys silently, so we detect via custom loader
    path = tmp_path / "errors.yaml"
    path.write_text(DUPLICATE_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"Duplicate error code: NOT_FOUND"):
        load_and_validate(path)


def test_codegen_rejects_invalid_http_status(tmp_path: Path, output_dir: Path) -> None:
    """Codegen should reject error codes with non-error HTTP status."""
    path = tmp_path / "errors.yaml"
    path.write_text(INVALID_STATUS_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(
        ValueError, match=r"Invalid HTTP status 200 for BAD_ERROR\. Must be 400-599\."
    ):
        load_and_validate(path)


def test_codegen_rejects_invalid_param_type(tmp_path: Path, output_dir: Path) -> None:
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
    # formats. Round-7 lane-3 fix: cast targets the CONCRETE *Params class
    # so a future schema typo is a static error at the format-string call
    # site, not a silent string-format failure at runtime.
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


def test_codegen_rejects_missing_title(tmp_path: Path, output_dir: Path) -> None:
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


def test_codegen_rejects_missing_detail_template(tmp_path: Path, output_dir: Path) -> None:
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


def test_codegen_emits_template_format_call_for_parameterized_errors(
    sample_errors_path: Path, output_dir: Path
) -> None:
    """Parameterized error's detail() body uses str.format(**params.model_dump()) via a cast."""
    from scripts.generate import generate_python

    generate_python(sample_errors_path, output_dir)

    content = (output_dir / "example_not_found_error.py").read_text()
    # Body type-narrows via cast (survives `python -O`) then renders the
    # template. Round-7 lane-3 fix: cast targets the CONCRETE *Params class.
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


def test_codegen_rejects_reserved_param_names(tmp_path: Path, output_dir: Path) -> None:
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


def test_codegen_rejects_positional_template_placeholders(tmp_path: Path, output_dir: Path) -> None:
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


def test_codegen_rejects_attribute_access_in_template(tmp_path: Path, output_dir: Path) -> None:
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
    tmp_path: Path, output_dir: Path
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

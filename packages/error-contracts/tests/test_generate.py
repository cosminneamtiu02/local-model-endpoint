"""Tests for the error contracts code generator."""

import ast
import json
from pathlib import Path

import pytest


SAMPLE_YAML = """
version: 1
errors:
  NOT_FOUND:
    http_status: 404
    description: Resource not found
    params: {}
  EXAMPLE_NOT_FOUND:
    http_status: 404
    description: Widget not found
    params:
      widget_id: string
  EXAMPLE_NAME_TOO_LONG:
    http_status: 422
    description: Name too long
    params:
      name: string
      max_length: integer
      actual_length: integer
  INTERNAL_ERROR:
    http_status: 500
    description: Sample internal error for codegen test
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


def test_codegen_produces_valid_python(sample_errors_path: Path, output_dir: Path):
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


def test_codegen_produces_valid_typescript(sample_errors_path: Path, output_dir: Path):
    """Codegen should produce a valid TypeScript file with types."""
    from scripts.generate import generate_typescript

    ts_path = generate_typescript(sample_errors_path, output_dir / "generated.ts")

    content = ts_path.read_text()
    assert "ErrorCode" in content
    assert '"NOT_FOUND"' in content
    assert '"EXAMPLE_NOT_FOUND"' in content
    assert "widget_id: string" in content
    assert "ErrorParamsByCode" in content


def test_codegen_produces_valid_required_keys(
    sample_errors_path: Path, output_dir: Path
):
    """Codegen should produce a valid required-keys.json."""
    from scripts.generate import generate_required_keys

    json_path = generate_required_keys(
        sample_errors_path, output_dir / "required-keys.json"
    )

    data = json.loads(json_path.read_text())
    assert data["version"] == 1
    assert data["namespace"] == "errors"
    assert "keys" in data
    assert "NOT_FOUND" in data["keys"]
    assert "EXAMPLE_NOT_FOUND" in data["keys"]
    assert "INTERNAL_ERROR" in data["keys"]
    assert "params_by_key" in data
    assert data["params_by_key"]["EXAMPLE_NOT_FOUND"] == ["widget_id"]
    assert data["params_by_key"]["NOT_FOUND"] == []
    assert data["params_by_key"]["INTERNAL_ERROR"] == []


def test_codegen_rejects_duplicate_codes(tmp_path: Path, output_dir: Path):
    """Codegen should reject YAML with duplicate error codes."""
    # YAML spec merges duplicate keys silently, so we detect via custom loader
    path = tmp_path / "errors.yaml"
    path.write_text(DUPLICATE_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(ValueError, match=r"Duplicate error code: NOT_FOUND"):
        load_and_validate(path)


def test_codegen_rejects_invalid_http_status(tmp_path: Path, output_dir: Path):
    """Codegen should reject error codes with non-error HTTP status."""
    path = tmp_path / "errors.yaml"
    path.write_text(INVALID_STATUS_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(
        ValueError, match=r"Invalid HTTP status 200 for BAD_ERROR\. Must be 400-599\."
    ):
        load_and_validate(path)


def test_codegen_rejects_invalid_param_type(tmp_path: Path, output_dir: Path):
    """Codegen should reject params with unsupported types."""
    path = tmp_path / "errors.yaml"
    path.write_text(INVALID_PARAM_TYPE_YAML)

    from scripts.generate import load_and_validate

    with pytest.raises(
        ValueError, match=r"Invalid param type 'list' for BAD_PARAMS\.items\."
    ):
        load_and_validate(path)

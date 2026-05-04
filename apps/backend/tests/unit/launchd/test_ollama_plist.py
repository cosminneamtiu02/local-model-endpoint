"""Unit tests for the Ollama launchd plist template (LIP-E005-F003).

The plist is a repo-shipped configuration template at
``infra/launchd/com.lip.ollama.plist.tmpl``; ``task ollama:install``
substitutes ``__HOME__`` with $HOME at install time so the same file
serves multiple developer machines. These tests validate that the
template exists, parses, lints under ``plutil``, and contains the five
v1 env vars plus the structural keys (``Label``, ``ProgramArguments``,
``RunAtLoad``, ``KeepAlive``, ``ProcessType``, ``StandardOutPath``,
``StandardErrorPath``).

The accompanying ``docs/ollama-launchd.md`` is also asserted to exist and
contain the operator-facing section anchors named in the spec.
"""

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

EXPECTED_ENV: dict[str, str] = {
    "OLLAMA_KEEP_ALIVE": "300s",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
}

# Top-level structural keys the plist must declare. Mirror EXPECTED_ENV's
# table form so a future contributor adding a structural key updates one
# constant rather than writing a new test.
EXPECTED_TOPLEVEL: dict[str, object] = {
    "Label": "com.lip.ollama",
    "ProcessType": "Background",
    "RunAtLoad": True,
    "KeepAlive": True,
}

REQUIRED_DOC_SECTIONS: tuple[str, ...] = (
    "What this is",
    "Install",
    "Uninstall",
    "Status check",
    "Env vars explained",
    "Customizing",
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "Taskfile.yml").exists():
            return parent
    msg = f"Could not find repo root walking up from {here}"
    raise RuntimeError(msg)


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return _repo_root()


@pytest.fixture(scope="module")
def plist_path(repo_root: Path) -> Path:
    return repo_root / "infra" / "launchd" / "com.lip.ollama.plist.tmpl"


@pytest.fixture
def parsed_plist(plist_path: Path) -> dict[str, object]:
    """Parsed plist dict — function-scoped so a future test that mutates the
    dict cannot leak state into siblings. The parse cost (sub-1ms
    plistlib.load on the small template) doesn't justify module scope."""
    with plist_path.open("rb") as fh:
        loaded = plistlib.load(fh)
    assert isinstance(loaded, dict)
    return loaded


def test_plist_file_at_infra_path_is_file(plist_path: Path) -> None:
    assert plist_path.is_file(), f"plist not found at {plist_path}"


@pytest.mark.skipif(shutil.which("plutil") is None, reason="plutil only on macOS")
def test_plutil_lint_exits_zero(plist_path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        ["plutil", "-lint", str(plist_path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"plutil -lint failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.parametrize(("key", "expected"), list(EXPECTED_TOPLEVEL.items()))
def test_toplevel_keys_match_v1_calibration(
    parsed_plist: dict[str, object],
    key: str,
    expected: object,
) -> None:
    """Each top-level structural key matches its expected value."""
    assert key in parsed_plist, f"missing top-level key {key}"
    assert parsed_plist[key] == expected, f"{key} expected {expected!r}, got {parsed_plist[key]!r}"


def test_environment_variables_match_v1_calibration(
    parsed_plist: dict[str, object],
) -> None:
    env = parsed_plist["EnvironmentVariables"]
    assert isinstance(env, dict)
    for key, expected_value in EXPECTED_ENV.items():
        assert key in env, f"missing env var {key}"
        assert env[key] == expected_value, f"{key} expected {expected_value!r}, got {env[key]!r}"


def test_program_arguments_invoke_ollama_serve(
    parsed_plist: dict[str, object],
) -> None:
    args = parsed_plist["ProgramArguments"]
    assert isinstance(args, list)
    assert len(args) >= 2, "ProgramArguments must have at least 2 entries"
    assert isinstance(args[0], str)
    assert args[0].endswith("ollama"), f"first arg should end with 'ollama', got {args[0]!r}"
    assert args[1] == "serve"


def test_log_paths_end_with_dot_log(parsed_plist: dict[str, object]) -> None:
    stdout_path = parsed_plist["StandardOutPath"]
    stderr_path = parsed_plist["StandardErrorPath"]
    assert isinstance(stdout_path, str)
    assert isinstance(stderr_path, str)
    assert stdout_path.endswith(".log"), stdout_path
    assert stderr_path.endswith(".log"), stderr_path


def test_log_paths_use_home_placeholder(parsed_plist: dict[str, object]) -> None:
    """Template form: log paths must use ``__HOME__`` (substituted at install
    time), never a hardcoded developer-specific absolute path. Guards against
    accidentally re-baking ``/Users/<someone>/...`` into the template."""
    stdout_path = parsed_plist["StandardOutPath"]
    stderr_path = parsed_plist["StandardErrorPath"]
    assert isinstance(stdout_path, str)
    assert isinstance(stderr_path, str)
    assert stdout_path.startswith("__HOME__/"), stdout_path
    assert stderr_path.startswith("__HOME__/"), stderr_path


def test_docs_file_exists_with_required_sections(repo_root: Path) -> None:
    doc_path = repo_root / "docs" / "ollama-launchd.md"
    assert doc_path.is_file(), f"doc not found at {doc_path}"
    body = doc_path.read_text(encoding="utf-8")
    for section in REQUIRED_DOC_SECTIONS:
        assert section in body, f"doc missing required section anchor: {section!r}"

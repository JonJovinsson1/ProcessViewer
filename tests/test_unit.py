"""Unit tests for pure functions in process_viewer."""
from __future__ import annotations

import json

import pytest

import process_viewer as pv


# ---------- fmt_bytes ----------

@pytest.mark.parametrize("value,expected", [
    (0, "0 B"),
    (500, "500 B"),
    (1023, "1023 B"),
    (1024, "1 KB"),
    (1024 * 500, "500 KB"),
    (1024 * 1024, "1 MB"),
    (1024 * 1024 * 100, "100 MB"),
    (1024 ** 3, "1.00 GB"),
    (int(1024 ** 3 * 3.4), "3.40 GB"),
    (1024 ** 3 * 16, "16.00 GB"),
])
def test_fmt_bytes(value: int, expected: str) -> None:
    assert pv.fmt_bytes(value) == expected


# ---------- is_programming_process ----------

class FakeProc:
    def __init__(self, name: str, cmdline: list[str] | None = None) -> None:
        self._name = name
        self._cmdline = cmdline or []

    def name(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        return self._cmdline


def _matches(name: str, cmdline: list[str] | None = None, **kwargs) -> bool:
    proc = FakeProc(name, cmdline)
    cl = " ".join(cmdline).lower() if cmdline else ""
    return pv.is_programming_process(proc, cmdline=cl, **kwargs)


@pytest.mark.parametrize("name", [
    "python", "python3", "python3.12", "node", "node22",
    "go", "go1.21", "rustc", "cargo", "java", "ruby",
    "Code Helper", "Code Helper (Renderer)",
    "PYTHON",  # case-insensitive
])
def test_matches_known_names(name: str) -> None:
    assert _matches(name) is True


@pytest.mark.parametrize("name", [
    "google",                  # regression: don't match because startswith "go"
    "Google Chrome Helper",    # regression: don't match despite "go" prefix
    "finder",
    "safari",
    "terminal",
    "kernel_task",
])
def test_rejects_non_programming(name: str) -> None:
    assert _matches(name) is False


def test_matches_claude_code_via_cmdline() -> None:
    assert _matches(
        "node",
        cmdline=[
            "/usr/bin/node",
            "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        ],
    ) is True


def test_matches_codex_via_cmdline() -> None:
    assert _matches("node", cmdline=["/opt/homebrew/bin/codex-cli", "run"]) is True


def test_matches_vscode_main_via_cmdline() -> None:
    assert _matches(
        "Electron",
        cmdline=[
            "/Applications/Visual Studio Code.app/Contents/MacOS/Electron",
            "--type=renderer",
        ],
    ) is True


def test_exclude_substring() -> None:
    assert _matches("chrome helper", exclude=frozenset({"chrome"})) is False
    assert _matches("Google Chrome Helper", exclude=frozenset({"chrome"})) is False


def test_exclude_via_cmdline() -> None:
    # Something matchable by cmdline substring, excluded via a cmdline substring.
    assert _matches(
        "node",
        cmdline=["/opt/homebrew/bin/codex-cli"],
        exclude=frozenset({"codex-cli"}),
    ) is False


def test_ignored_names_exact_match() -> None:
    # "node" is in PROGRAMMING_NAMES but exact-ignored here.
    assert _matches("node", ignored_names=frozenset({"node"})) is False
    # Ignore list is exact match, not substring — "node" should not nuke "node-gyp".
    # (node-gyp isn't in the name set anyway, but prove exact-match semantics.)
    assert _matches(
        "python", ignored_names=frozenset({"pyth"})
    ) is True


def test_extra_include() -> None:
    assert _matches("mybinary") is False
    assert _matches("mybinary", extra_include=frozenset({"mybinary"})) is True


def test_versioned_fallback() -> None:
    # python3.13 matches via the versioned regex fallback to "python".
    assert _matches("python3.13") is True
    # node22 similarly.
    assert _matches("node22") is True


# ---------- ignore list persistence ----------

@pytest.fixture
def tmp_ignore(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    ig = cfg / "ignore.json"
    monkeypatch.setattr(pv, "CONFIG_DIR", cfg)
    monkeypatch.setattr(pv, "IGNORE_FILE", ig)
    return ig


def test_load_missing_file(tmp_ignore) -> None:
    assert pv.load_ignore_list() == set()


def test_save_and_load_round_trip(tmp_ignore) -> None:
    pv.save_ignore_list(frozenset({"foo", "bar", "BAZ"}))
    assert tmp_ignore.exists()
    loaded = pv.load_ignore_list()
    assert loaded == {"foo", "bar", "baz"}


def test_load_malformed_json(tmp_ignore) -> None:
    tmp_ignore.parent.mkdir(parents=True, exist_ok=True)
    tmp_ignore.write_text("this is not json {")
    assert pv.load_ignore_list() == set()


def test_load_wrong_shape(tmp_ignore) -> None:
    tmp_ignore.parent.mkdir(parents=True, exist_ok=True)
    tmp_ignore.write_text(json.dumps({"not": "a list"}))
    assert pv.load_ignore_list() == set()


def test_save_creates_parent_dir(tmp_ignore) -> None:
    assert not tmp_ignore.parent.exists()
    pv.save_ignore_list(frozenset({"x"}))
    assert tmp_ignore.parent.exists()
    assert tmp_ignore.exists()


# ---------- GPU helper (smoke test) ----------

def test_gpu_returns_none_or_float() -> None:
    v = pv.get_gpu_utilization()
    assert v is None or isinstance(v, float)
    if isinstance(v, float):
        assert 0.0 <= v <= 100.0

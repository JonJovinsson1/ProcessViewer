"""Integration tests driving the real Textual app via Pilot.

These exercise every keybinding, modal, and the refresh loop without needing
a terminal. They do not mock psutil — the app runs against live processes.
"""
from __future__ import annotations

import subprocess
import sys
import time

import psutil
import pytest

import process_viewer as pv
from process_viewer import HelpScreen, IgnoreListScreen, ProcessViewer


@pytest.fixture
def isolated_ignore(monkeypatch, tmp_path):
    """Point the ignore-list file at tmp_path so tests don't touch real config."""
    cfg = tmp_path / "cfg"
    ig = cfg / "ignore.json"
    monkeypatch.setattr(pv, "CONFIG_DIR", cfg)
    monkeypatch.setattr(pv, "IGNORE_FILE", ig)
    return ig


@pytest.fixture
def sleeper():
    """Spawn a long-lived python subprocess that the app will pick up, and
    guarantee it's cleaned up even on test failure."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Give psutil a moment to see it.
    time.sleep(0.05)
    yield proc
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---------- boot / smoke ----------

async def test_app_boots_and_renders(isolated_ignore):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Metric panels got at least one sample.
        assert len(app.cpu_panel.history) > 0
        assert len(app.ram_panel.history) > 0
        # Table should have all six columns registered.
        assert len(app.table.columns) == 6


async def test_refresh_tick_updates_metrics(isolated_ignore):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        before = app.cpu_panel.history[-1]
        # Force several refreshes manually — faster than waiting for the 1-s timer.
        for _ in range(5):
            app.refresh_data()
            await pilot.pause()
        # Just prove it didn't crash and history kept growing.
        assert len(app.cpu_panel.history) == pv.HIST_LEN


# ---------- sort cycling ----------

async def test_sort_cycles_all_options(isolated_ignore):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.sort_idx == 0  # starts on CPU
        seen = [app.sort_idx]
        for _ in range(len(app.SORT_OPTIONS)):
            await pilot.press("s")
            await pilot.pause()
            seen.append(app.sort_idx)
        # Cycled through every option and wrapped back to 0.
        assert seen == [0, 1, 2, 3, 0]


async def test_sort_label_shown_not_internal_key(isolated_ignore):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = app._stats_text
        # Display labels — not raw keys.
        assert "CPU" in rendered
        assert "cpu" not in rendered  # no raw internal key
        assert "rss" not in rendered
        assert "processes" in rendered


# ---------- help modal ----------

async def test_help_modal_opens_and_closes(isolated_ignore):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        baseline = len(app.screen_stack)
        await pilot.press("question_mark")
        await pilot.pause()
        assert len(app.screen_stack) == baseline + 1
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == baseline
        assert not isinstance(app.screen, HelpScreen)


async def test_help_modal_closes_with_q(isolated_ignore):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("q")
        await pilot.pause()
        # App itself should NOT have quit — 'q' inside the help modal only closes it.
        assert not isinstance(app.screen, HelpScreen)
        assert app.is_running


# ---------- ignore list ----------

async def test_ignore_modal_shows_current_list(isolated_ignore):
    app = ProcessViewer(ignored_names=frozenset({"alpha", "beta"}))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("I")
        await pilot.pause()
        assert isinstance(app.screen, IgnoreListScreen)
        assert app.screen.ignored == {"alpha", "beta"}
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, IgnoreListScreen)


async def test_ignore_selected_adds_to_list_and_persists(isolated_ignore, sleeper):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Wait until our sleeper shows up in the table.
        sleeper_pid = sleeper.pid
        for _ in range(10):
            app.refresh_data()
            await pilot.pause()
            if sleeper_pid in app._row_pids:
                break
        assert sleeper_pid in app._row_pids, "sleeper never appeared in the table"

        # Move the cursor to the sleeper's row.
        target_row = None
        for i in range(app.table.row_count):
            key = app.table.coordinate_to_cell_key((i, 0)).row_key.value
            if key == str(sleeper_pid):
                target_row = i
                break
        assert target_row is not None
        app.table.move_cursor(row=target_row)
        await pilot.pause()

        # Press 'i' to ignore.
        before = set(app.ignored_names)
        await pilot.press("i")
        await pilot.pause()
        assert app.ignored_names != before
        # Name got added (some lowercase form of "python...").
        added = app.ignored_names - before
        assert len(added) == 1
        name = next(iter(added))
        assert name  # non-empty

        # Persistence: ignore file exists and contains the new name.
        assert isolated_ignore.exists()
        assert name in isolated_ignore.read_text()

        # And the sleeper is now filtered out on next refresh.
        app.refresh_data()
        await pilot.pause()
        assert sleeper_pid not in app._row_pids


async def test_ignore_modal_clear_all(isolated_ignore):
    app = ProcessViewer(ignored_names=frozenset({"alpha", "beta", "gamma"}))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("I")
        await pilot.pause()
        assert isinstance(app.screen, IgnoreListScreen)
        await pilot.press("c")
        await pilot.pause()
        assert app.ignored_names == frozenset()
        assert app.screen.ignored == set()


async def test_ignore_selected_with_no_selection_flashes_warning(isolated_ignore):
    app = ProcessViewer(
        # Force zero visible processes by ignoring everything common.
        exclude=frozenset({"a", "e", "i", "o", "u", "y", "n", "r", "s", "t", "l"}),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        # Table may genuinely be empty. If it isn't, skip.
        if app.table.row_count > 0:
            pytest.skip("filter wasn't aggressive enough")
        await pilot.press("i")
        await pilot.pause()
        assert "No process selected" in app._action_text


# ---------- kill actions ----------

async def test_terminate_selected_kills_sleeper(isolated_ignore, sleeper):
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        sleeper_pid = sleeper.pid
        for _ in range(10):
            app.refresh_data()
            await pilot.pause()
            if sleeper_pid in app._row_pids:
                break
        assert sleeper_pid in app._row_pids

        # Select the sleeper row.
        for i in range(app.table.row_count):
            key = app.table.coordinate_to_cell_key((i, 0)).row_key.value
            if key == str(sleeper_pid):
                app.table.move_cursor(row=i)
                break
        await pilot.pause()

        await pilot.press("k")
        # Give the subprocess a moment to exit.
        for _ in range(20):
            await pilot.pause()
            if sleeper.poll() is not None:
                break
        assert sleeper.poll() is not None, "sleeper did not terminate"

        assert "Terminated" in app._action_text or "Killed" in app._action_text


# ---------- status bar content ----------

async def test_status_bar_format(isolated_ignore):
    app = ProcessViewer(ignored_names=frozenset({"x", "y"}))
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = app._stats_text
        assert "processes" in rendered
        assert "Sort:" in rendered
        assert "Ignored: [b]2[/b]" in rendered

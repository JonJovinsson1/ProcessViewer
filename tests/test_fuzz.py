"""Fuzz / soak test: hammer the app with random keypresses and many refresh
ticks to flush out crashes that only happen under repeated, unusual input.

Tests in this file are marked `fuzz` so they can be skipped from the normal
suite and run on demand via `./test.sh --fuzz`."""
from __future__ import annotations

import random

import pytest

import process_viewer as pv
from process_viewer import ProcessViewer

pytestmark = pytest.mark.fuzz


# Keys that are safe to fire at any time. Deliberately excludes 'q' (would
# quit the app mid-run), 'k'/'K' (would actually kill processes on the host),
# and modifiers that Textual's Pilot doesn't simulate well.
FUZZ_KEYS = [
    "s",            # cycle sort
    "r",            # manual refresh
    "down", "up",   # cursor movement
    "pagedown", "pageup",
    "home", "end",
    "question_mark",  # open help
    "escape",         # dismiss modal (or noop on main screen)
    "I",              # open ignore-list modal
    "i",              # ignore currently-selected process
    "c",              # clear-all (only does something inside ignore modal)
    "d",              # delete (only does something inside ignore modal)
    "tab",
]


@pytest.fixture
def isolated_ignore(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    ig = cfg / "ignore.json"
    monkeypatch.setattr(pv, "CONFIG_DIR", cfg)
    monkeypatch.setattr(pv, "IGNORE_FILE", ig)
    return ig


async def test_fuzz_random_keys_200_iterations(isolated_ignore):
    """Fire 200 random keypresses with interleaved refreshes. Assert no crash
    and the app is still running and responsive at the end."""
    rng = random.Random(42)
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        for i in range(200):
            await pilot.press(rng.choice(FUZZ_KEYS))
            if i % 20 == 0:
                app.refresh_data()
            await pilot.pause()
        # Survival assertions.
        assert app.is_running
        assert 0 <= app.sort_idx < len(app.SORT_OPTIONS)
        assert isinstance(app.ignored_names, frozenset)
        # Stats label should still be populated and non-garbled.
        assert "processes" in app._stats_text
        assert "Sort:" in app._stats_text


async def test_fuzz_rapid_sort_cycling(isolated_ignore):
    """Cycle the sort 500 times in tight succession."""
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        for _ in range(500):
            await pilot.press("s")
        await pilot.pause()
        assert app.is_running
        assert 0 <= app.sort_idx < len(app.SORT_OPTIONS)


async def test_fuzz_modal_thrashing(isolated_ignore):
    """Open/close the help + ignore modals alternately, many times."""
    app = ProcessViewer(ignored_names=frozenset({"alpha", "beta"}))
    async with app.run_test() as pilot:
        await pilot.pause()
        baseline = len(app.screen_stack)
        for _ in range(50):
            await pilot.press("question_mark")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("I")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        assert len(app.screen_stack) == baseline
        assert app.is_running


async def test_fuzz_many_refreshes(isolated_ignore):
    """Call refresh_data 200 times in a row to shake out any diff-update bugs."""
    app = ProcessViewer()
    async with app.run_test() as pilot:
        await pilot.pause()
        for _ in range(200):
            app.refresh_data()
        await pilot.pause()
        assert app.is_running
        # Table's internal row-tracking set should still match the column count.
        assert len(app.table.columns) == 6

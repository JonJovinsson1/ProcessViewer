"""Headless screenshot via Textual's Pilot API."""
import asyncio
import getpass
import math
import random
from pathlib import Path

import process_viewer
from process_viewer import ProcessViewer

EXCLUDED = frozenset({
    "code helper",
    "codex helper",
    "chrome",
    "chromium",
})

GENERIC_USER = "dev"
_NBSP = "&#160;"


def _redactions() -> list[tuple[str, str]]:
    """Build the redaction list from the current user's home and login name.

    The User column is rendered as `&#160;<username>&#160;`; padding with NBSPs
    preserves the cell width so Textual's `textLength` attribute doesn't stretch
    the letters across the original column.
    """
    home = str(Path.home()).rstrip("/")
    user = getpass.getuser()
    pad = _NBSP * max(0, len(user) - len(GENERIC_USER))
    return [
        (f"{home}/", "~/"),
        (home, "~"),
        (f"{_NBSP}{user}{_NBSP}", f"{_NBSP}{GENERIC_USER}{pad}{_NBSP}"),
        (user, GENERIC_USER),
    ]


def redact_svg(path: str) -> None:
    svg = Path(path).read_text()
    for old, new in _redactions():
        svg = svg.replace(old, new)
    Path(path).write_text(svg)


def _fake_gpu_stream():
    """Plausible GPU trace: slow sine + noise + occasional burst."""
    t = 0
    while True:
        base = 45 + 25 * math.sin(t / 7.0)
        spike = 20 if random.random() < 0.1 else 0
        yield max(3.0, min(95.0, base + spike + random.uniform(-6, 6)))
        t += 1


async def main() -> None:
    gpu_gen = _fake_gpu_stream()
    process_viewer.get_gpu_utilization = lambda: next(gpu_gen)

    app = ProcessViewer(exclude=EXCLUDED)
    app.sort_idx = 1  # Memory, descending
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.5)
        # Fill the 60-slot sparkline history with real 1Hz samples.
        for _ in range(62):
            app.refresh_data()
            await pilot.pause(1.0)
        app.save_screenshot("marketing_screenshot.svg")
    redact_svg("marketing_screenshot.svg")


if __name__ == "__main__":
    asyncio.run(main())

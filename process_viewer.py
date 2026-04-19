"""Programmer Process Viewer — live TUI for programming-related processes."""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

import psutil
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Sparkline,
    Static,
)

APP_VERSION = "1.0.0"

PROGRAMMING_NAMES: frozenset[str] = frozenset({
    "python", "python3", "python3.10", "python3.11", "python3.12", "python3.13",
    "pypy", "pypy3", "ipython", "jupyter", "jupyter-lab", "jupyter-notebook",
    "node", "deno", "bun", "npm", "yarn", "pnpm", "tsc", "ts-node", "vite",
    "webpack", "esbuild", "rollup", "next", "nest",
    "ruby", "irb", "rails", "rake",
    "go", "gopls", "dlv",
    "rustc", "cargo", "rust-analyzer",
    "java", "javac", "kotlin", "kotlinc", "scala", "sbt", "gradle", "mvn",
    "ghc", "ghci", "runghc", "stack", "cabal",
    "dotnet", "mono", "fsharp",
    "php", "perl", "lua", "julia", "dart", "flutter",
    "gunicorn", "uvicorn", "hypercorn", "celery", "flask", "django",
    "pytest", "pylint", "mypy", "ruff", "black",
    "clang", "clang++", "gcc", "g++", "make", "cmake", "ninja",
    "ocaml", "erl", "elixir", "iex", "mix",
    "code helper", "code helper (renderer)", "code helper (plugin)",
    "code helper (gpu)",
})

# Matched against the joined, lowercased cmdline — catches CLIs that run under
# node/python (Claude Code, Codex) and the main VS Code process.
PROGRAMMING_CMDLINE_SUBSTRINGS: frozenset[str] = frozenset({
    "visual studio code",
    "/code.app/",
    "claude-code",
    "anthropic-ai/claude",
    "/claude ",
    "codex-cli",
    "openai/codex",
    "/codex ",
})

HIST_LEN = 60
_VERSIONED_RE = re.compile(r"^([a-z+#]+)[\d._\-]*$")

# Bare interpreters — when a process is one of these, the script path from
# cmdline is a more useful Name than the exe name.
INTERPRETER_NAMES: frozenset[str] = frozenset({
    "python", "pypy", "ruby", "perl", "php", "lua",
    "node", "deno", "bun",
})
SCRIPT_EXTS: tuple[str, ...] = (
    ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".lua",
)


def friendly_name(name: str, cmdline: list[str]) -> str:
    """Return script basename when name is a bare interpreter, else name."""
    base = name.lower()
    m = _VERSIONED_RE.match(base)
    stripped = m.group(1) if m else base
    if stripped not in INTERPRETER_NAMES and base not in INTERPRETER_NAMES:
        return name
    for arg in cmdline[1:]:
        low = arg.lower()
        if any(low.endswith(ext) for ext in SCRIPT_EXTS):
            return Path(arg).name
    return name

CONFIG_DIR = Path.home() / ".config" / "programmer-process-viewer"
IGNORE_FILE = CONFIG_DIR / "ignore.json"


# ---------- helpers ----------

def fmt_bytes(n: float) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{int(n)} B"


def get_gpu_utilization() -> float | None:
    """System-wide GPU utilization via ioreg. macOS only, no sudo needed."""
    try:
        out = subprocess.check_output(
            ["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"],
            text=True, timeout=1.0, stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    m = re.search(r'"Device Utilization %"=(\d+)', out)
    if m:
        return float(m.group(1))
    return None


def load_ignore_list() -> set[str]:
    if not IGNORE_FILE.exists():
        return set()
    try:
        data = json.loads(IGNORE_FILE.read_text())
        if isinstance(data, list):
            return {str(x).lower() for x in data}
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def save_ignore_list(names: frozenset[str]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        IGNORE_FILE.write_text(json.dumps(sorted(names), indent=2))
    except OSError:
        pass


def is_programming_process(
    proc: psutil.Process,
    extra_include: frozenset[str] = frozenset(),
    exclude: frozenset[str] = frozenset(),
    ignored_names: frozenset[str] = frozenset(),
    cmdline: str | None = None,
) -> bool:
    try:
        name = proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    # Ignore list — exact name match.
    if name in ignored_names:
        return False

    # Compute cmdline once so exclusions and cmdline-based inclusions share it.
    if cmdline is None:
        try:
            cmdline = " ".join(proc.cmdline()).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            cmdline = ""

    # Exclusions apply to both name and cmdline, so `--exclude codex-cli` works
    # even when the process's name alone (e.g. "node") would otherwise match.
    for ex in exclude:
        if not ex:
            continue
        if ex in name or (cmdline and ex in cmdline):
            return False

    # Inclusion: exact name match.
    if name in PROGRAMMING_NAMES or name in extra_include:
        return True

    # Inclusion: versioned binaries like python3.12, node22, go1.21.
    m = _VERSIONED_RE.match(name)
    if m:
        base = m.group(1)
        if base in PROGRAMMING_NAMES or base in extra_include:
            return True

    # Inclusion: cmdline substring match (Claude Code, Codex, VS Code main).
    if cmdline:
        for sub in PROGRAMMING_CMDLINE_SUBSTRINGS:
            if sub in cmdline:
                return True

    return False


# ---------- widgets ----------

class MetricPanel(Static):
    """Bordered panel: title + live value in border, sparkline inside."""

    def __init__(self, title: str, unit: str = "%", **kwargs) -> None:
        super().__init__(**kwargs)
        self.title_text = title
        self.unit = unit
        self.history: collections.deque[float] = collections.deque(
            [0.0] * HIST_LEN, maxlen=HIST_LEN
        )
        self.border_title = f" {title} "

    def compose(self) -> ComposeResult:
        self.spark = Sparkline(list(self.history), summary_function=max)
        yield self.spark

    def update_value(self, value: float | None, detail: str | None = None) -> None:
        if value is None:
            self.border_title = f" {self.title_text} — n/a "
            self.history.append(0.0)
        else:
            label = f" {self.title_text}  {value:5.1f}{self.unit}"
            if detail:
                label += f"  ·  {detail}"
            self.border_title = label + " "
            self.history.append(value)
        self.spark.data = list(self.history)


# ---------- modals ----------

HELP_TEXT = """\
[b]Programmer Process Viewer[/b]  [dim]v{version}[/dim]

[b $accent]Navigation[/b $accent]
  [b]↑  ↓[/b]         Move selection
  [b]Page Up/Dn[/b]   Scroll faster

[b $accent]Actions[/b $accent]
  [b]k[/b]            Terminate selected (SIGTERM)
  [b]K[/b]            Force kill selected (SIGKILL)
  [b]i[/b]            Ignore selected process (persistent)
  [b]shift+I[/b]      Manage ignored list
  [b]s[/b]            Cycle sort column
  [b]r[/b]            Refresh now
  [b]?[/b]            Show this help
  [b]q[/b]            Quit

[dim]Ignored processes are stored at
~/.config/programmer-process-viewer/ignore.json[/dim]
"""


class HelpScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("question_mark", "app.pop_screen", "Close"),
        Binding("q", "app.pop_screen", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(HELP_TEXT.format(version=APP_VERSION), id="help-body")


class IgnoreListScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("q", "app.pop_screen", "Close"),
        Binding("d", "remove", "Remove"),
        Binding("delete", "remove", "Remove"),
        Binding("backspace", "remove", "Remove"),
        Binding("c", "clear_all", "Clear all"),
    ]

    def __init__(self, ignored: frozenset[str]) -> None:
        super().__init__()
        self.ignored: set[str] = set(ignored)

    def compose(self) -> ComposeResult:
        with Vertical(id="ignore-box"):
            yield Static("[b]Ignored processes[/b]", id="ignore-title")
            self.list_view = ListView(id="ignore-list")
            yield self.list_view
            yield Static(
                "[dim][b]d[/b] remove  ·  [b]c[/b] clear all  ·  [b]esc[/b] close[/dim]",
                id="ignore-footer",
            )

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        self.list_view.clear()
        names = sorted(self.ignored)
        if not names:
            self.list_view.append(ListItem(Label("[dim](none)[/dim]")))
            return
        for n in names:
            self.list_view.append(ListItem(Label(n)))

    def action_remove(self) -> None:
        if not self.ignored:
            return
        idx = self.list_view.index
        if idx is None:
            return
        names = sorted(self.ignored)
        if 0 <= idx < len(names):
            self.ignored.discard(names[idx])
            self.app.set_ignored(frozenset(self.ignored))  # type: ignore[attr-defined]
            self._populate()

    def action_clear_all(self) -> None:
        self.ignored.clear()
        self.app.set_ignored(frozenset())  # type: ignore[attr-defined]
        self._populate()


# ---------- app ----------

class ProcessViewer(App):
    CSS = """
    Screen { layout: vertical; background: $background; }

    Header { background: $boost; }

    #metrics { height: 9; padding: 1 1 0 1; }
    MetricPanel {
        border: round $accent;
        padding: 0 1;
        width: 1fr;
        height: 100%;
        margin-right: 1;
    }
    MetricPanel:last-of-type { margin-right: 0; }
    MetricPanel > .border-title { color: $accent; }
    MetricPanel > Sparkline { height: 1fr; }
    Sparkline > .sparkline--max-color { color: $success; }
    Sparkline > .sparkline--min-color { color: $success 40%; }

    DataTable {
        height: 1fr;
        margin: 1 1 0 1;
        border: round $accent 30%;
    }
    DataTable > .datatable--header { background: $boost; color: $accent; text-style: bold; }
    DataTable > .datatable--cursor { background: $accent 30%; }

    #statusbar {
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    #stats { width: 3fr; color: $text-muted; }
    #action { width: 2fr; content-align: right middle; }

    /* Help modal */
    HelpScreen { align: center middle; background: $background 70%; }
    #help-box {
        width: 54;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #help-body { height: auto; }

    /* Ignore list modal */
    IgnoreListScreen { align: center middle; background: $background 70%; }
    #ignore-box {
        width: 54;
        height: 22;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #ignore-title { height: 1; margin-bottom: 1; color: $accent; }
    #ignore-list { height: 1fr; border: round $accent 30%; }
    #ignore-footer { height: 1; margin-top: 1; content-align: center middle; }
    """

    TITLE = "Programmer Process Viewer"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("k", "kill_selected", "Kill"),
        Binding("K", "force_kill_selected", "Force kill", show=False),
        Binding("i", "ignore_selected", "Ignore"),
        Binding("I", "manage_ignore", "Ignore list"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("r", "refresh_now", "Refresh", show=False),
        Binding("question_mark", "show_help", "Help"),
    ]

    # (internal_key, display_label, reverse_sort)
    SORT_OPTIONS: list[tuple[str, str, bool]] = [
        ("cpu", "CPU", True),
        ("rss", "Memory", True),
        ("name", "Name", False),
        ("pid", "PID", False),
    ]

    def __init__(
        self,
        extra_include: frozenset[str] = frozenset(),
        exclude: frozenset[str] = frozenset(),
        ignored_names: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        self.extra_include = extra_include
        self.exclude = exclude
        self.ignored_names = ignored_names
        self.cpu_panel = MetricPanel("CPU")
        self.ram_panel = MetricPanel("RAM")
        self.gpu_panel = MetricPanel("GPU")
        self.table = DataTable(cursor_type="row", zebra_stripes=True)
        self.stats_label = Static("", id="stats")
        self.action_label = Static("", id="action")
        self.sort_idx = 0
        self._row_pids: set[int] = set()
        self._action_timer = None
        # Shadow copies of the rendered strings so tests (and future logic)
        # can inspect the current status without touching Textual internals.
        self._stats_text: str = ""
        self._action_text: str = ""
        self._prime_cpu_percent()

    def _prime_cpu_percent(self) -> None:
        psutil.cpu_percent(interval=None)
        for p in psutil.process_iter(["name"]):
            try:
                p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="metrics"):
            yield self.cpu_panel
            yield self.ram_panel
            yield self.gpu_panel
        yield self.table
        with Horizontal(id="statusbar"):
            yield self.stats_label
            yield self.action_label
        yield Footer()

    def on_mount(self) -> None:
        self.table.add_column("PID", key="pid", width=7)
        self.table.add_column("Name", key="name", width=24)
        self.table.add_column("CPU %", key="cpu", width=7)
        self.table.add_column("Memory", key="rss", width=10)
        self.table.add_column("User", key="user", width=12)
        self.table.add_column("Command", key="cmd")
        self.set_interval(1.0, self.refresh_data)
        self.refresh_data()

    # ---------- data refresh ----------

    def refresh_data(self) -> None:
        cpu_total = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ncpu = psutil.cpu_count() or 1
        self.cpu_panel.update_value(cpu_total, detail=f"{ncpu} cores")
        self.ram_panel.update_value(
            vm.percent,
            detail=f"{fmt_bytes(vm.used)} / {fmt_bytes(vm.total)}",
        )
        self.gpu_panel.update_value(get_gpu_utilization())

        rows: dict[int, tuple[str, float, float, str, str]] = {}
        for p in psutil.process_iter(["pid", "name", "username"]):
            try:
                cmdline_list = p.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                cmdline_list = []
            cmd_raw = " ".join(cmdline_list)
            if not is_programming_process(
                p,
                self.extra_include,
                self.exclude,
                self.ignored_names,
                cmdline=cmd_raw.lower(),
            ):
                continue
            try:
                with p.oneshot():
                    cpu = p.cpu_percent(interval=None) / ncpu
                    rss = float(p.memory_info().rss)
                    cmd = cmd_raw or p.name()
                    rows[p.info["pid"]] = (
                        friendly_name(p.info["name"] or "?", cmdline_list),
                        cpu,
                        rss,
                        p.info.get("username") or "?",
                        cmd,
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Remove rows for processes that are gone.
        for pid in list(self._row_pids):
            if pid not in rows:
                try:
                    self.table.remove_row(str(pid))
                except Exception:
                    pass
                self._row_pids.discard(pid)

        # Update existing rows in place; add new rows at the bottom.
        for pid, (name, cpu, rss, user, cmd) in rows.items():
            cmd_short = cmd if len(cmd) <= 120 else cmd[:117] + "..."
            cpu_str = f"{cpu:5.1f}"
            rss_str = fmt_bytes(rss)
            row_key = str(pid)
            if pid in self._row_pids:
                self.table.update_cell(row_key, "name", name)
                self.table.update_cell(row_key, "cpu", cpu_str)
                self.table.update_cell(row_key, "rss", rss_str)
                self.table.update_cell(row_key, "user", user)
                self.table.update_cell(row_key, "cmd", cmd_short)
            else:
                self.table.add_row(
                    str(pid), name, cpu_str, rss_str, user, cmd_short, key=row_key
                )
                self._row_pids.add(pid)

        # Sort.
        sort_key, _label, reverse = self.SORT_OPTIONS[self.sort_idx]
        if sort_key == "cpu":
            self.table.sort("cpu", key=lambda v: float(v), reverse=reverse)
        elif sort_key == "rss":
            rss_by_pid = {str(pid): r[2] for pid, r in rows.items()}
            self.table.sort(
                "pid", key=lambda v: rss_by_pid.get(v, 0.0), reverse=reverse
            )
        elif sort_key == "pid":
            self.table.sort("pid", key=lambda v: int(v), reverse=reverse)
        else:
            self.table.sort("name", reverse=reverse)

        self._update_stats_bar(len(rows))

    def _update_stats_bar(self, count: int | None = None) -> None:
        if count is None:
            count = len(self._row_pids)
        _key, label, reverse = self.SORT_OPTIONS[self.sort_idx]
        arrow = "↓" if reverse else "↑"
        parts = [
            f"[b]{count}[/b] processes",
            f"Sort: [b]{label}[/b] {arrow}",
            f"Ignored: [b]{len(self.ignored_names)}[/b]",
        ]
        text = "   ·   ".join(parts)
        self._stats_text = text
        self.stats_label.update(text)

    # ---------- actions ----------

    def _selected_pid(self) -> int | None:
        if self.table.row_count == 0:
            return None
        try:
            row_key = self.table.coordinate_to_cell_key(
                self.table.cursor_coordinate
            ).row_key
        except Exception:
            return None
        if row_key.value is None:
            return None
        try:
            return int(row_key.value)
        except ValueError:
            return None

    def _flash_action(self, markup: str) -> None:
        self._action_text = markup
        self.action_label.update(markup)
        if self._action_timer is not None:
            self._action_timer.stop()

        def clear() -> None:
            self._action_text = ""
            self.action_label.update("")

        self._action_timer = self.set_timer(3.0, clear)

    def _kill(self, force: bool) -> None:
        pid = self._selected_pid()
        if pid is None:
            self._flash_action("[yellow]No process selected[/yellow]")
            return
        try:
            p = psutil.Process(pid)
            name = p.name()
            if force:
                p.kill()
                self._flash_action(f"[red]Killed[/red] {name} ({pid})")
            else:
                p.terminate()
                self._flash_action(f"[yellow]Terminated[/yellow] {name} ({pid})")
        except psutil.NoSuchProcess:
            self._flash_action(f"[dim]PID {pid} already gone[/dim]")
        except psutil.AccessDenied:
            self._flash_action(f"[red]Access denied[/red] killing PID {pid}")
        except Exception as e:
            self._flash_action(f"[red]Error:[/red] {e}")
        self.refresh_data()

    def action_kill_selected(self) -> None:
        self._kill(force=False)

    def action_force_kill_selected(self) -> None:
        self._kill(force=True)

    def action_refresh_now(self) -> None:
        self.refresh_data()

    def action_cycle_sort(self) -> None:
        self.sort_idx = (self.sort_idx + 1) % len(self.SORT_OPTIONS)
        self.refresh_data()

    def action_ignore_selected(self) -> None:
        pid = self._selected_pid()
        if pid is None:
            self._flash_action("[yellow]No process selected[/yellow]")
            return
        try:
            name = psutil.Process(pid).name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._flash_action("[red]Could not read process name[/red]")
            return
        new_set = frozenset(self.ignored_names | {name})
        self.set_ignored(new_set)
        self._flash_action(f"[cyan]Ignoring[/cyan] {name}")

    def action_manage_ignore(self) -> None:
        self.push_screen(IgnoreListScreen(self.ignored_names))

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def set_ignored(self, names: frozenset[str]) -> None:
        self.ignored_names = names
        save_ignore_list(names)
        self.refresh_data()


# ---------- entry point ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ppv",
        description="Programmer Process Viewer — live TUI for programming processes.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"Programmer Process Viewer {APP_VERSION}",
    )
    parser.add_argument(
        "--chrome", action="store_true",
        help="Include Google Chrome processes (excluded by default).",
    )
    parser.add_argument(
        "--include", nargs="*", default=[], metavar="NAME",
        help="Extra process names to include (exact match, lowercase).",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], metavar="SUBSTR",
        help="Process-name substrings to exclude.",
    )
    args = parser.parse_args()

    exclude = {s.lower() for s in args.exclude}
    if not args.chrome:
        exclude.update({"chrome", "chromium"})

    ProcessViewer(
        extra_include=frozenset(s.lower() for s in args.include),
        exclude=frozenset(exclude),
        ignored_names=frozenset(load_ignore_list()),
    ).run()


if __name__ == "__main__":
    main()

"""Shared fixtures for the V2 tests.

The rule for this suite: nothing may touch the network, launch anything, open a
window, take a screenshot, restart the machine, or write to the user's real
memory file. Each is replaced here, so a failing test is a real fault and not an
accident.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis2.config.settings import Settings  # noqa: E402
from jarvis2.core.assistant import JarvisAssistant  # noqa: E402
from jarvis2.core.memory import LongTermMemory, MemoryStore  # noqa: E402


class FakeClock:
    """A fixed time, so a reply about the clock can be checked exactly."""

    def __init__(self, year=2026, month=10, day=5, hour=14, minute=30):
        import datetime

        self.moment = datetime.datetime(year, month, day, hour, minute)

    def now(self):
        return self.moment

    def install(self, monkeypatch):
        import jarvis2.skills.system as system

        real = system.datetime.datetime

        class Frozen(real):
            @classmethod
            def now(cls, tz=None):
                return self.moment

        monkeypatch.setattr(system.datetime, "datetime", Frozen)
        return self


@pytest.fixture(autouse=True)
def no_power_commands(monkeypatch):
    """Stops any test from actually shutting down or restarting this machine.

    Autouse and unconditional. A test that approves a confirmation would
    otherwise run ``shutdown /s /f /t 1`` for real, because that is exactly
    what approving means. Commands are recorded so a test can still check what
    would have run.
    """
    import subprocess

    ran = []

    class Completed:
        returncode = 0
        stdout = b""
        stderr = b""

    def record(argv, **kwargs):
        ran.append((list(argv) if not isinstance(argv, (str, bytes))
                    else argv, kwargs))
        return Completed()

    monkeypatch.setattr(subprocess, "run", record)
    yield ran


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch, tmp_path):
    """Keeps tests away from the network, the screen, and the real home."""
    import webbrowser

    # Nothing is opened. A failing test must mean a real fault and not a
    # window that appeared.
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a))

    # No screenshot of the developer's own screen.
    class FakeImage:
        def save(self, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")

    try:
        import pyautogui

        monkeypatch.setattr(pyautogui, "screenshot", FakeImage)
    except ImportError:
        pass

    # No name file and no memory file outside the temporary folder.
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    yield opened


@pytest.fixture(autouse=True)
def no_shared_indexes():
    """Empties the file indexes between tests.

    They are kept between questions on purpose, because a scan of a real home
    folder costs seconds. Between tests they have to go, or a test searches the
    temporary folder of whichever test ran before it and finds nothing, or worse,
    finds a file it did not create.
    """
    from jarvis2.files import search

    search.clear_caches()
    yield
    search.clear_caches()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake user home holding the folders the assistant searches."""
    from jarvis2.files.search import DOCUMENT_FOLDERS

    for folder in DOCUMENT_FOLDERS:
        (tmp_path / folder).mkdir(exist_ok=True)

    import os

    real_expanduser = os.path.expanduser
    root = str(tmp_path)

    def fake_expanduser(path="~"):
        """Redirects only "~" and "~/..." at the fake home.

        Everything else goes to the real function. Answering with the home for
        every argument would quietly rewrite every path a test passes in, which
        is exactly the kind of failure that looks like a bug in the code under
        test rather than in the test.
        """
        text = str(path)
        if text == "~":
            return root
        if text.startswith("~") and text[1:2] in ("\\", "/"):
            return str(tmp_path / text[2:].lstrip("\\/"))
        return real_expanduser(text)

    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)
    return tmp_path


@pytest.fixture
def settings(tmp_path):
    """Settings pointed at a temporary folder, with nothing enabled that talks
    to the outside world."""
    return Settings(
        assistant_name="Jarvis",
        voice_enabled=False,
        memory_enabled=True,
        memory_dir="memory",
        confirm_dangerous_actions=True,
        automation_enabled=False,
        extra={"root": str(tmp_path)})


@pytest.fixture
def memory(tmp_path, settings):
    return LongTermMemory(MemoryStore(tmp_path / "memory", enabled=True))


@pytest.fixture
def assistant(settings, memory):
    """An assistant with no V1 assistant, no model and no real side effects."""
    return JarvisAssistant(
        settings=settings, memory=memory)


@pytest.fixture
def frozen_clock(monkeypatch):
    return FakeClock().install(monkeypatch)


# ----------------------------------------------------------------------
# Skills run against a context that does nothing to the machine.
# ----------------------------------------------------------------------
class RecordingContext:
    """A SkillContext whose outside world is a list."""

    def __init__(self, settings, memory=None, opened=None, results=None,
                 confirmations=None, registry=None, provider=None,
                 session=None, wikipedia=None):
        from jarvis2.safety.confirmations import ConfirmationManager

        self.settings = settings
        self.memory = memory
        self.opened = opened if opened is not None else []
        self.results = results or {}
        self.confirmations = confirmations or ConfirmationManager()
        self.registry = registry
        self.provider = provider
        self.session = session
        self.wikipedia = wikipedia
        self.permissions = None
        self.bus = None
        self.blocked = []

    async def run_blocking(self, function, *args, **kwargs):
        """Returns a canned result, or calls a callable for real."""
        key = function.__name__ if hasattr(function, "__name__") else str(function)
        if key in self.results:
            return self.results[key]
        if isinstance(function, str):
            return self.results.get(function)
        return function(*args, **kwargs)

    def run_blocking_sync(self, function, *args, **kwargs):
        return function(*args, **kwargs)

    def open_path(self, path: str) -> None:
        self.opened.append(path)

    def log(self, action: str, **data):
        pass


@pytest.fixture
def context(settings, memory):
    return RecordingContext(settings, memory=memory)

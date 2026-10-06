"""Finding an installed application.

V1 scans the Start Menu and the desktop for shortcuts, which is what finds
anything that has been installed rather than merely put on the path. That scan is
reused when V1 is loaded. When it is not, there is still a useful answer: the
executables Windows can find on PATH, which covers notepad, calc, mspaint and
the rest.

Split out so that a skill asking "is this installed" does not need the whole V1
assistant behind it.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from jarvis2.logging_utils import get_logger

_log = get_logger("applications")

# Spoken names for programs Windows ships with, mapped to the executable.
PATH_APPS = {
    "notepad": "notepad.exe",
    "notes": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "control panel": "control.exe",
    "registry editor": "regedit.exe",
    "system information": "msinfo32.exe",
    "device manager": "devmgmt.msc",
    "disk cleanup": "cleanmgr.exe",
    "characters": "charmap.exe",
    "snipping tool": "snippingtool.exe",
    "wordpad": "write.exe",
    "magnifier": "magnify.exe",
}

# Spoken names for programs installed on PATH, mapped to the executable.
PATH_ONLY = {
    "python": "python.exe",
    "vs code": "code",
    "vscode": "code",
    "code": "code",
    "git": "git.exe",
    "node": "node.exe",
    "chrome": "chrome",
    "firefox": "firefox",
}


@dataclass(frozen=True)
class Application:
    """One installed application."""

    label: str
    target: str
    #: How it was found, for the log and for explaining a miss.
    source: str = "shortcut"

    def as_dict(self) -> dict:
        return {"label": self.label, "target": self.target,
                "source": self.source}


def shortcut_folders() -> list:
    """The folders that hold shortcuts to installed applications."""
    folders = [
        os.path.join(os.environ.get("ProgramData", ""), "Microsoft", "Windows",
                     "Start Menu", "Programs"),
        os.path.join(os.environ.get("AppData", ""), "Microsoft", "Windows",
                     "Start Menu", "Programs"),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.environ.get("Public", ""), "Desktop"),
    ]
    return [folder for folder in folders if folder and os.path.isdir(folder)]


_scan_cache: dict | None = None


def installed_shortcuts() -> dict:
    """Shortcut name to shortcut path.

    Cached, because walking the Start Menu costs a moment and the answer does
    not change while the assistant is running.
    """
    global _scan_cache
    if _scan_cache is not None:
        return _scan_cache

    found: dict = {}
    for folder in shortcut_folders():
        for dirpath, _subfolders, files in os.walk(folder):
            for filename in files:
                if filename.lower().endswith(".lnk"):
                    label = os.path.splitext(filename)[0]
                    found.setdefault(label, os.path.join(dirpath, filename))

    _scan_cache = found
    return found


def _from_path(name: str) -> Application | None:
    """Looks for a program Windows can run by name."""
    executable = PATH_APPS.get(name) or PATH_ONLY.get(name)
    candidates = [executable] if executable else [name, f"{name}.exe"]

    for candidate in candidates:
        if not candidate:
            continue
        found = shutil.which(candidate)
        if found:
            return Application(
                label=name.title(), target=found, source="path"
            )
    return None


def find_application(name: str) -> Application | None:
    """The best match for an application name, or None.

    A program Windows ships with is looked for first, so "notepad" does not
    open a third party app of a similar name. Then the Start Menu, and then a
    close spelling of what was asked for.
    """
    query = (name or "").strip().lower()
    if not query:
        return None

    shortcut_free = _from_path(query)
    if shortcut_free is not None:
        return shortcut_free

    shortcuts = installed_shortcuts()

    for wanted in (query, query.title()):
        for label, target in shortcuts.items():
            if label.lower() == wanted.lower():
                return Application(label=label, target=target)

    # Shortest name wins, so "firefox" picks Firefox over Firefox Private
    # Browsing.
    partial = sorted(
        (label for label in shortcuts if query in label.lower()),
        key=len,
    )
    if partial:
        return Application(label=partial[0], target=shortcuts[partial[0]])

    import difflib

    close = difflib.get_close_matches(query, list(shortcuts), n=1, cutoff=0.6)
    if close:
        return Application(label=close[0], target=shortcuts[close[0]])

    return None


def clear_cache() -> None:
    """Forgets the shortcut scan, so a newly installed app can be found."""
    global _scan_cache
    _scan_cache = None

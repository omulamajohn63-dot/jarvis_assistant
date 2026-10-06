"""Checking a path before anything is opened, moved or deleted.

Two jobs. First, resolve whatever came in into one real path, so ".." and a
shortcut cannot point somewhere other than where they appear to. Second, refuse
the places that matter: Windows itself, program directories, and anything that
is an executable when the user asked for a document.

A path that arrives from a language model is a suggestion. This is where the
suggestion is checked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Directories that are never what a person means when they say "open this".
PROTECTED_NAMES = frozenset({
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "system volume information",
    "$recycle.bin",
    "recovery",
    "boot",
    "perflogs",
    "windows.old",
})

# Places that only an administrator should be writing to.
SYSTEM_ROOTS = ("c:/windows", "c:/program files", "c:/program files (x86)")

# Extensions that run something when they are opened. These are refused when a
# document was asked for, whatever the file is called.
EXECUTABLE_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1", ".ps1xml",
    ".msi", ".msp", ".hta", ".cpl", ".jar", ".lnk",
})

# A file that pretends to be a document is exactly what this is for.
DOCUMENT_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".csv", ".log",
    ".xlsx", ".xls", ".xlsm", ".pptx", ".ppt", ".odt", ".ods", ".odp",
})

MEDIA_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".wma", ".ogg", ".opus",
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v",
})


@dataclass(frozen=True)
class PathVerdict:
    """Whether a path may be touched, and why not when it may not."""

    path: str
    allowed: bool
    reason: str = ""
    exists: bool = False
    is_directory: bool = False

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "allowed": self.allowed,
            "reason": self.reason,
            "exists": self.exists,
        }


def resolve(raw: str, base: str | None = None) -> Path:
    """Turns any path into one absolute, symlink-free path.

    Relative paths are taken from ``base``, which is what keeps a search result
    from quietly meaning something different depending on where Jarvis was
    started.
    """
    if not raw or not str(raw).strip():
        raise ValueError("no path given")

    text = str(raw).strip().strip('"').strip("'")
    if not text:
        raise ValueError("no path given")

    expanded = os.path.expandvars(os.path.expanduser(text))
    path = Path(expanded)
    if not path.is_absolute():
        path = Path(base or Path.cwd()) / path

    # resolve() collapses "..", which is the whole point: a path that looks like
    # it is in Downloads must not be able to climb out of it.
    resolved = path.resolve(strict=False)

    # A Windows path reached through the short 8.3 name, or one whose casing
    # differs from what is on disk, still has to land on the same place.
    try:
        resolved = Path(os.path.normcase(str(resolved)))
    except (OSError, ValueError):
        pass
    return resolved


def _same(left: Path, right: Path) -> bool:
    """True when two paths name the same place, however they are written."""
    try:
        return os.path.normcase(str(left)) == os.path.normcase(str(right))
    except (OSError, ValueError):
        return left == right


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def is_protected(path: str | Path) -> bool:
    """True for Windows' own directories and the Recycle Bin."""
    text = str(path).replace("\\", "/").rstrip("/")
    lowered = text.lower()

    for name in PROTECTED_NAMES:
        if f"/{name}" in f"/{lowered}" or lowered.endswith(f"/{name}"):
            return True
        if lowered == name:
            return True

    for root in SYSTEM_ROOTS:
        if _within(Path(text), Path(root)):
            return True
    return False


def is_within(path: str | Path, folder: str | Path) -> bool:
    return _within(Path(str(path)), Path(str(folder)))


def extension_of(path: str | Path) -> str:
    return os.path.splitext(str(path))[1].lower()


def looks_executable(path: str | Path) -> bool:
    return extension_of(path) in EXECUTABLE_EXTENSIONS


def validate(
    raw: str,
    base: str | None = None,
    allow_protected: bool = False,
    expect: str = "any",
) -> PathVerdict:
    """Checks one path and returns the resolved one only if it is acceptable.

    ``expect`` narrows what will be accepted: "document", "media" or "folder".
    It is what stops a request to open a document turning into a request to run
    something.
    """
    try:
        resolved = resolve(raw, base)
    except ValueError as error:
        return PathVerdict(str(raw), False, str(error))

    exists = resolved.exists()
    is_directory = resolved.is_dir() if exists else False

    if not allow_protected and is_protected(resolved):
        return PathVerdict(
            str(resolved), False,
            "that is a system directory, so Jarvis will not touch it",
            exists, is_directory,
        )

    if expect == "document" and looks_executable(resolved):
        # A file that runs when opened is never what "open my document" meant.
        # Checked whether or not it exists, since a path is refused before it is
        # touched and a missing file must not become a way past this.
        return PathVerdict(
            str(resolved), False,
            f"that is a {extension_of(resolved).lstrip('.').upper()} program, "
            "not a document",
            exists, is_directory,
        )

    if expect == "folder" and exists and not is_directory:
        return PathVerdict(
            str(resolved), False, "that is a file, not a folder",
            exists, is_directory,
        )

    return PathVerdict(str(resolved), True, "", exists, is_directory)


def validate_many(
    paths: list,
    base: str | None = None,
    allow_protected: bool = False,
    expect: str = "any",
) -> list:
    return [
        validate(path, base, allow_protected, expect) for path in paths
    ]


def is_safe_to_delete(path: str | Path, allow_protected: bool = False) -> bool:
    """The check before anything is destroyed.

    Files under the home directory, the desktop, Documents, Downloads and the
    temporary folder may go. A drive root, a system directory, or the user's own
    profile root may not: deleting those is not something an assistant should be
    one mistaken sentence away from.

    A named folder is refused as well as its contents. Deleting a file called
    ``Documents\\cv.pdf`` is a normal request; deleting ``Documents`` itself is
    not, and the two must not be confused.
    """
    try:
        resolved = Path(os.path.normcase(str(resolve(path))))
    except (ValueError, OSError):
        return False

    if not allow_protected and is_protected(resolved):
        return False

    home = Path(os.path.normcase(str(
        Path(os.path.expanduser("~")).resolve(strict=False)
    )))

    protected_folders = [home]
    deletable_roots = []
    for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music",
                 "Videos"):
        folder = home / name
        protected_folders.append(folder)
        deletable_roots.append(folder)

    temporary = os.environ.get("TEMP") or os.environ.get("TMP")
    if temporary:
        deletable_roots.append(
            Path(os.path.normcase(str(Path(temporary).resolve(strict=False))))
        )

    # Checked before any containment test, because the home directory contains
    # every other folder and would otherwise answer first and allow all of them.
    for folder in protected_folders:
        if _same(resolved, folder):
            return False

    for folder in deletable_roots:
        if _within(resolved, folder):
            return True
    return False


def display(path: str | Path, home: str | Path | None = None) -> str:
    """A path shortened for showing, so a reply does not become a wall of text.

    Only a path that really is inside the home directory is shortened. Anything
    else is left alone, so a system path cannot be cut down to nonsense.
    """
    text = str(path)
    base = str(home) if home is not None else os.path.expanduser("~")

    try:
        if _same(Path(text), Path(base)):
            return "~"
        if os.path.normcase(text).startswith(os.path.normcase(base) + os.sep):
            return "~" + text[len(base):].replace("\\", "/")
    except (OSError, ValueError):
        pass
    return text.replace("\\", "/")


def matching_kind(path: str | Path) -> str:
    """What sort of thing a path is, from its extension."""
    extension = extension_of(path)
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    if extension in MEDIA_EXTENSIONS:
        return "media"
    if extension in EXECUTABLE_EXTENSIONS:
        return "program"
    return "file"

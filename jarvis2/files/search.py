"""Finding a file whose name somebody described out loud.

The work here is guessing what "collo blue top shotta" and "my cv" name, and
then putting the matches in an order a person can navigate. Everything is a pure
function of a name and a library, which is what makes it testable without a disk.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from jarvis2.logging_utils import get_logger

_log = get_logger("files.search")

# Folders searched for media, documents and anything else the user keeps.
USER_FOLDERS = ("Downloads", "Music", "Videos", "Desktop", "Pictures")

# Documents live in the same folders plus Documents.
DOCUMENT_FOLDERS = USER_FOLDERS + ("Documents",)

# Folders that name a group in the results list. Documents are included so a
# file there is reported as "Documents" and not as the top folder of its path.
RESULT_FOLDERS = USER_FOLDERS + ("Documents",)

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".wma", ".ogg", ".opus",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v",
}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".csv", ".log",
    ".xlsx", ".xls", ".xlsm", ".pptx", ".ppt",
}

# Directories that never hold the user's media but are expensive to walk.
JUNK_FOLDERS = {
    ".venv", "venv", "node_modules", "site-packages", ".git", "__pycache__",
    "$recycle.bin", "system volume information",
}

# Word and Excel leave a small "~$" owner file beside the real one while a
# document is open, and it is never what the user meant to open.
LOCK_FILE_PREFIX = "~$"

# A spoken name must match at least this share of a file name's words. Single
# word queries either hit or miss, so this only filters multi word queries.
MATCH_FLOOR = 0.6

# How long a shared run of letters has to be before two words count as the same
# name. Two letters sit inside far too many words to be evidence on their own.
MIN_LOOSE_MATCH = 3

# How much of the longer of two words a shared prefix has to cover. This is what
# separates a name from a coincidence: "youtube" shares "you" with the word
# "you", which is most of the short word but under half of the longer one, so
# they are not the same name.
MIN_PREFIX_COVERAGE = 0.7


@dataclass(frozen=True)
class Match:
    """One file that was found, and how well its name fitted."""

    label: str
    path: str
    score: float


# ----------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------
def clean_name(text: str) -> str:
    """Reduces a file or spoken name to comparable lowercase words."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", str(text))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def shared_prefix(first: str, second: str) -> int:
    """How many characters two words begin with in common."""
    count = 0
    for left, right in zip(first, second, strict=False):
        if left != right:
            break
        count += 1
    return count


def token_matches(token: str, word: str) -> bool:
    """True when a spoken word really does name a word in the file name."""
    if token == word:
        return True

    # Short words have to match exactly. Anything looser matches too much to be
    # useful: "you" would otherwise claim every name beginning with it.
    if len(token) < MIN_LOOSE_MATCH or len(word) < MIN_LOOSE_MATCH:
        return False

    # "collo" and "blue" both sit inside "colloblue", which is how a spaced out
    # song title still matches.
    if token in word:
        return True

    shared = shared_prefix(token, word)
    return (
        shared >= MIN_LOOSE_MATCH
        and shared / max(len(token), len(word)) >= MIN_PREFIX_COVERAGE
    )


def match_score(query: str, label: str) -> float:
    """Scores how much of a spoken name appears in a file name, from 0 to 1.

    Tokens are matched loosely, so "collo blue top shotta" still matches
    "COLLOBLUE - TOP SHOTTA FT KBC".
    """
    tokens = clean_name(os.path.splitext(str(query))[0]).split()
    words = clean_name(label).split()
    if not tokens or not words:
        return 0.0

    hits = sum(1 for token in tokens if any(token_matches(token, w) for w in words))
    return hits / len(tokens)


def rank_matches(library: dict, query: str, limit: int | None = None) -> list:
    """Ranks a name-to-paths library against a query, best match first.

    Each entry is a Match. One name can appear more than once, for example a
    song saved as both .mp3 and .m4a.
    """
    if not library:
        return []

    ranked = []
    for label in library:
        if label.lower() == query:
            score = 1.0
        else:
            score = match_score(query, label)
            if score < MATCH_FLOOR:
                continue
        ranked.append((score, label))

    ranked.sort(key=lambda item: item[0], reverse=True)

    matches = []
    for score, label in ranked[:limit]:
        for path in library[label]:
            matches.append(Match(label=label, path=path, score=score))
    return matches


# ----------------------------------------------------------------------
# Scanning
# ----------------------------------------------------------------------
def _ignore_walk_error(error) -> None:
    """Swallows access-denied errors from folders such as System Volume Information."""
    return None


def scan_roots(roots, extensions=None) -> dict:
    """Maps each name found to every file found with that name.

    Walks each root all the way down while skipping dependency directories, so
    files are found wherever they sit. A name can map to several files, for
    example song.mp3 and song.m4a.
    """
    library: dict = {}
    wanted = {e.lower() for e in extensions} if extensions else None

    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, subfolders, files in os.walk(root, onerror=_ignore_walk_error):
            subfolders[:] = [
                name for name in subfolders
                if name.lower() not in JUNK_FOLDERS
            ]
            for filename in files:
                if filename.startswith(LOCK_FILE_PREFIX):
                    continue
                if wanted is not None:
                    if os.path.splitext(filename)[1].lower() not in wanted:
                        continue
                label = os.path.splitext(filename)[0]
                library.setdefault(label, []).append(
                    os.path.join(dirpath, filename)
                )

    for paths in library.values():
        paths.sort()
    return library


class Library:
    """An index of the user's folders, built once and kept.

    The scan costs seconds, so it is done on first use and reused. A drive that
    is plugged in later is noticed by the external library, which re-checks the
    drive list on every call.
    """

    def __init__(self, roots, extensions=None):
        # ``roots`` may be a callable, and the shared indexes pass one. Resolving
        # the folders at import time would freeze the home directory as it was
        # when the module loaded, which is wrong the moment a test, or a user,
        # points the assistant somewhere else.
        self._roots = roots
        self.extensions = extensions
        self._library: dict | None = None
        self._lock = threading.Lock()

    @property
    def roots(self) -> list:
        return list(self._roots() if callable(self._roots) else self._roots)

    def all(self) -> dict:
        if self._library is None:
            with self._lock:
                if self._library is None:
                    roots = self.roots
                    _log.info("indexing %s", ", ".join(roots) or "nothing")
                    self._library = scan_roots(roots, self.extensions or set())
        return self._library

    def clear(self) -> None:
        with self._lock:
            self._library = None


def _home() -> str:
    return os.path.expanduser("~")


def _folders(folders) -> list:
    return [os.path.join(_home(), folder) for folder in folders]


def _library_for(extensions) -> Library:
    """The index that covers a set of extensions, built once and kept.

    Two shared indexes exist rather than one, because a document search must not
    walk every picture and video in the library to find a PDF. Keeping them here
    is what makes the scan happen once: a fresh Library per call would re-walk
    the disk on every question.
    """
    if extensions is None or extensions == MEDIA_EXTENSIONS:
        return _USER_LIBRARY
    if extensions == DOCUMENT_EXTENSIONS:
        return _DOCUMENT_LIBRARY
    return Library(lambda: _folders(USER_FOLDERS), extensions)


_USER_LIBRARY = Library(lambda: _folders(USER_FOLDERS), MEDIA_EXTENSIONS)
_DOCUMENT_LIBRARY = Library(lambda: _folders(DOCUMENT_FOLDERS),
                            DOCUMENT_EXTENSIONS)

_external_cache: dict = {}


def _external_library(extensions) -> Library:
    """An index of every drive that is not the system drive."""
    from jarvis2.files import drives

    roots = tuple(drives.extra_drives())
    key = (roots, tuple(sorted(extensions or ())))

    cached = _external_cache.get(key)
    if cached is not None:
        return cached

    # A fresh entry when the drives changed, so one plugged in mid-session gets
    # indexed and one unplugged is dropped.
    _external_cache.clear()
    library = Library(roots, extensions)
    _external_cache[key] = library
    return library


def clear_caches() -> None:
    """Forgets every index, so a file added a moment ago can be found."""
    _external_cache.clear()
    _USER_LIBRARY.clear()
    _DOCUMENT_LIBRARY.clear()


def find(query: str, extensions=None, search_drives: bool = False) -> list:
    """Every file matching a spoken name, best match first.

    Other drives are only walked when asked for, so "open chrome" does not pay
    for a full scan of every disk behind the answer.
    """
    wanted = str(query).strip().lower()
    if not wanted:
        return []

    library = {
        label: list(paths)
        for label, paths in _library_for(extensions).all().items()
    }

    if search_drives:
        for label, paths in _external_library(
                extensions or MEDIA_EXTENSIONS).all().items():
            library.setdefault(label, []).extend(paths)

    return rank_matches(library, wanted)


def find_documents(query: str, search_drives: bool = False) -> list:
    return find(query, DOCUMENT_EXTENSIONS, search_drives)


def find_media(query: str, search_drives: bool = False) -> list:
    return find(query, MEDIA_EXTENSIONS, search_drives)


# ----------------------------------------------------------------------
# Presenting results
# ----------------------------------------------------------------------
def media_location(path: str) -> tuple:
    """Names the place a file lives, as (drive, folder)."""
    drive = os.path.splitdrive(path)[0].upper()
    lowered = path.lower()
    home = _home().lower()

    for folder in RESULT_FOLDERS:
        if os.path.join(home, folder).lower() + os.sep in lowered:
            return drive, folder

    remainder = os.path.dirname(os.path.splitdrive(path)[1]).lstrip("\\/")
    top = remainder.split(os.sep)[0] if remainder else "drive root"
    return drive, top


def _location_sort_key(location: tuple) -> tuple:
    """Sorts the system drive's folders first, then the other drives."""
    drive, folder = location
    system = os.path.splitdrive(_home())[0].upper()
    return (drive != system, drive, folder)


def file_size(path: str) -> str:
    """Formats a file size for the results list."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "size unknown"
    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.1f} GB"
    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"
    return f"{size // 1024} KB"


def order_matches(matches: list) -> list:
    """Sorts matches into display order: by drive and folder, then by name.

    The numbering shown to the user is taken from this order, so the list and
    the numbers Jarvis accepts must not be sorted separately.
    """
    groups: dict = {}
    for match in matches:
        label, path = (match.label, match.path) if isinstance(match, Match) else match
        groups.setdefault(media_location(path), []).append((label, path))

    ordered = []
    for location in sorted(groups, key=_location_sort_key):
        ordered.extend(sorted(groups[location], key=lambda item: item[0].lower()))
    return ordered


def build_results_view(entries: list, start: int, query: str,
                       all_entries: list) -> dict:
    """One page of results as data, ready to show.

    The numbering carried here is the numbering the user is shown, so an
    interface can render clickable rows that mean exactly what they say.
    """
    counts: dict = {}
    for _label, path in all_entries:
        location = media_location(path)
        counts[location] = counts.get(location, 0) + 1

    system = os.path.splitdrive(_home())[0].upper()
    searched = sorted(
        {media_location(item[1])[0] for item in all_entries},
        key=lambda drive: (drive != system, drive),
    )

    rows = []
    locations = []
    current = None
    for label, path in entries:
        location = media_location(path)
        if location != current:
            current = location
            locations.append({
                "drive": location[0],
                "folder": location[1],
                "count": counts.get(location, 0),
            })
        rows.append({
            "n": start + len(rows),
            "label": label,
            "ext": os.path.splitext(path)[1].lstrip(".").upper(),
            "size": file_size(path),
            "path": path,
            "drive": location[0],
            "folder": location[1],
        })

    remaining = len(all_entries) - (start - 1 + len(entries))
    return {
        "query": query,
        "start": start,
        "total": len(all_entries),
        "drives": searched,
        "locations": locations,
        "rows": rows,
        "remaining": max(remaining, 0),
    }


def build_list_view(titles: list, start: int, query: str, total: int) -> dict:
    """A list of article titles, shaped like a file listing.

    The same shape, so one piece of code can draw either. The fields that only
    mean something for files are left blank.
    """
    rows = [
        {
            "n": start + index,
            "label": title,
            "ext": "",
            "size": "",
            "path": "",
            "drive": "",
            "folder": "",
        }
        for index, title in enumerate(titles)
    ]
    return {
        "query": query,
        "start": start,
        "total": total,
        "drives": ["Wikipedia"],
        "locations": [],
        "rows": rows,
        "remaining": max(total - (start - 1 + len(titles)), 0),
    }


def single_result_view(query: str, label: str, path: str) -> dict:
    """A lone match, which needs no choosing between numbers."""
    return build_results_view([(label, path)], 1, query, [(label, path)])


# ----------------------------------------------------------------------
# Picking from a numbered list
# ----------------------------------------------------------------------
# How a person picks without saying the number. -1 means the last one, whose
# position depends on how many there are.
ORDINAL_WORDS = {
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6, "six": 6,
    "seventh": 7, "7th": 7, "seven": 7,
    "eighth": 8, "8th": 8, "eight": 8,
    "ninth": 9, "9th": 9, "nine": 9,
    "tenth": 10, "10th": 10, "ten": 10,
    "last": -1, "final": -1,
}

# Wording that carries no position of its own, dropped before looking for one.
CHOICE_FILLER = {
    "the", "one", "ones", "result", "results", "number", "no", "that",
    "please", "give", "show", "me", "pick", "choose", "option",
    "file", "entry", "it", "is",
}


def choice_position(answer: str, total: int) -> int | None:
    """The position an answer names, counted from one, or None.

    A number, a word for a number and "the last one" all reach the same list,
    so saying "the third one" is as good as typing 3. None means the words
    pointed at nothing in particular, and guessing there would pick the wrong
    file.
    """
    from jarvis2.files.text import words_of

    text = str(answer).strip().lower().strip(" .?!,")
    if not text or total < 1:
        return None

    if text.isdigit():
        index = int(text)
        return index if 1 <= index <= total else None

    numbered = re.search(r"\b(\d+)\s*(?:st|nd|rd|th)\b", text)
    if numbered:
        index = int(numbered.group(1))
        return index if 1 <= index <= total else None

    for word in sorted(words_of(text) - CHOICE_FILLER, key=len, reverse=True):
        if word in ORDINAL_WORDS:
            index = ORDINAL_WORDS[word]
            if index == -1:
                return total
            return index if 1 <= index <= total else None

    return None

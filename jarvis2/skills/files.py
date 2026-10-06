"""Files, documents and media.

One shape for all three: search, and if the answer is not unique, ask. The
searching is in jarvis2.files, which is pure logic over a library and needs no
state. This module's own work is the part that has to be right — check the file
really is there, and never claim one was opened when it was not.
"""

from __future__ import annotations

import os

from jarvis2.core.models import Choice, Request, SkillResult
from jarvis2.files import documents as doc
from jarvis2.files import search as finder
from jarvis2.files.text import strip_articles
from jarvis2.logging_utils import get_logger
from jarvis2.safety import paths as path_safety
from jarvis2.skills.base import Skill, SkillContext

_log = get_logger("skills.files")

OPEN_VERBS = ("open ", "launch ", "start ", "run ", "show me ", "find ")
READ_VERBS = ("read aloud ", "read out loud ", "read out ", "read ")
PLAY_VERBS = ("play ", "watch ", "listen to ", "listen ", "start playing ")

ARTICLES = ("the ", "my ", "a ", "an ")

# A request naming nothing in particular. "play something" is a question, not a
# request to play a random file.
GENERIC = {
    "something", "anything", "it", "that", "this", "file", "files",
    "document", "documents", "doc", "docs", "note", "notes", "song", "songs",
    "music", "video", "videos", "track", "movie", "movies", "album",
}


def strip_verb(text: str) -> tuple:
    """Takes the leading verb and article off a request.

    Returns (action, subject). ``action`` is "open", "read", "play" or None when
    the sentence did not start with one of those, which is how a skill hands a
    request it does not understand back to the router.
    """
    current = " ".join(str(text).split()).strip().lower()

    for action, verbs in (("read", READ_VERBS), ("play", PLAY_VERBS),
                          ("open", OPEN_VERBS)):
        for verb in verbs:
            if current.startswith(verb):
                return action, strip_articles(current[len(verb):].strip()).strip(" .")
    return None, current


class _SearchSkill(Skill):
    """Shared searching, listing and opening."""

    noun = "file"
    kind = "media"

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        """Takes the sentence apart and hands the subject to the subclass."""
        action, subject = strip_verb(request.normalized)
        if action is None:
            return SkillResult(
                succeeded=False,
                text=f"I did not catch what to do with {request.normalized}.",
            )
        if not subject:
            return SkillResult(
                succeeded=False,
                text=f"I did not catch which {self.noun} you meant.",
            )
        return await self.perform(action, subject, context, request)

    async def perform(self, action: str, subject: str, context: SkillContext,
                      request: Request) -> SkillResult:
        raise NotImplementedError

    async def _results(self, subject: str, context: SkillContext) -> list:
        """Finds candidates, searching other drives only if nothing came first.

        Searching every drive takes seconds, so it is a second pass. That is what
        keeps "open chrome" from paying for a full walk of every disk.
        """
        search = finder.find_media if self.kind == "media" \
            else finder.find_documents

        found = await context.run_blocking(search, subject, False)
        if found:
            return found
        return await context.run_blocking(search, subject, True)

    async def _resolve(self, candidates: list, action: str, subject: str,
                       context: SkillContext) -> SkillResult:
        """Opens one result, or lists them and asks which."""
        checked = []
        for match in candidates:
            if not path_safety.validate(match.path).allowed:
                continue
            checked.append((match.label, match.path))

        if not checked:
            return SkillResult(
                succeeded=False,
                text=f"I could not find a {self.noun} called {subject}.",
            )

        if len(checked) == 1:
            return await self.open_one(checked[0][0], checked[0][1], action,
                                       context)

        ordered = finder.order_matches(checked)
        choices = [
            Choice(
                number=index,
                label=label,
                detail=os.path.splitext(path)[1].lstrip(".").upper(),
                payload=path,
            )
            for index, (label, path) in enumerate(ordered, 1)
        ]

        where = _where_they_are(ordered)
        return SkillResult(
            succeeded=True,
            text=(f"I found {len(choices)} {self.noun}s called {subject}. "
                  f"Most are in {where}. Which one?"),
            choices=choices,
            question=f"{len(choices)} matches for {subject}",
        )

    async def open_one(self, label: str, path: str, action: str,
                       context: SkillContext) -> SkillResult:
        return self._opened(label, path, "Opening", context)

    def _opened(self, label: str, path: str, verb: str,
                context: SkillContext) -> SkillResult:
        """Hands a verified path to the operating system and says so."""
        verdict = path_safety.validate(path)
        if not verdict.allowed:
            return SkillResult(succeeded=False, text=verdict.reason)

        if not os.path.isfile(path) and not os.path.isdir(path):
            return SkillResult(succeeded=False,
                               text=f"{label} is no longer there.")

        try:
            context.run_blocking_sync(context.open_path, path)
        except OSError as error:
            # Reported rather than swallowed, and never dressed up as success.
            return SkillResult(succeeded=False,
                               text=f"I could not open {label}.",
                               error=str(error))

        return SkillResult(
            succeeded=True,
            text=f"{verb} {label}.",
            opened=[path],
            actions=[{"action": "open", "target": path}],
            metadata={"label": label, "path": path},
        )


class DocumentSkill(_SearchSkill):
    name = "documents"
    description = (
        "Find a document by name and open it in its usual program, or read the "
        "opening of it out loud."
    )
    actions = ("search_files", "open_folder", "read_document")
    keywords = ("open", "launch", "start", "read", "find", "show", "document",
                "cv", "resume", "syllabus", "pdf", "docx", "report", "notes",
                "invoice", "receipt", "assignment", "letter", "excel", "slides")
    noun = "document"
    kind = "document"

    async def can_handle(self, request: Request) -> float:
        action, subject = strip_verb(request.normalized)
        if action not in {"open", "read"}:
            return 0.0

        # "open chrome" is an application, not a document.
        if subject in {"chrome", "edge", "firefox", "notepad", "calculator",
                       "youtube", "google"}:
            return 0.0

        lowered = request.normalized
        document_words = ("cv", "resume", "document", "doc", "pdf", "docx",
                          "xlsx", "pptx", "syllabus", "report", "notes",
                          "invoice", "receipt", "assignment", "letter",
                          "excel", "slides", "powerpoint", "spreadsheet")
        if any(word in lowered for word in document_words):
            return 0.75
        return 0.5

    async def perform(self, action: str, subject: str, context: SkillContext,
                      request: Request) -> SkillResult:
        candidates = await self._results(subject, context)
        if not candidates:
            return SkillResult(
                succeeded=False,
                text=f"I could not find a document called {subject}.",
            )
        return await self._resolve(candidates, action, subject, context)

    async def open_one(self, label: str, path: str, action: str,
                       context: SkillContext) -> SkillResult:
        if action == "read":
            return await self._read(label, path, context)
        return self._opened(label, path, "Opening", context)

    async def _read(self, label: str, path: str,
                    context: SkillContext) -> SkillResult:
        """Reads the opening of a document, saying so when it stops early."""
        if not os.path.isfile(path):
            return SkillResult(succeeded=False,
                               text=f"{label} is no longer there.")

        if not doc.can_read(path):
            # An old format such as .doc has no reader. Saying so and opening it
            # is more use than failing.
            kind = doc.extension_name(path) or "that"
            opened = self._opened(label, path, "Opening", context)
            return SkillResult(
                succeeded=opened.succeeded,
                text=(f"I cannot read {kind} files, so I will open {label} "
                      "instead."),
                opened=opened.opened,
                actions=opened.actions,
                error=opened.error,
            )

        body, truncated = await context.run_blocking(doc.prepare, path)
        if not body:
            return SkillResult(succeeded=False,
                               text=f"I could not find any text in {label}.")

        return SkillResult(
            succeeded=True,
            text=body + (" That is the opening part only." if truncated else ""),
            metadata={"label": label, "path": path, "truncated": truncated},
        )


class MediaSkill(_SearchSkill):
    name = "media"
    description = "Find a song or a video by name and play it."
    actions = ("search_files", "play_media")
    keywords = ("play", "watch", "listen", "song", "music", "video", "movie")
    noun = "file"
    kind = "media"

    async def can_handle(self, request: Request) -> float:
        action, _subject = strip_verb(request.normalized)
        return 0.85 if action == "play" else 0.0

    async def perform(self, action: str, subject: str, context: SkillContext,
                      request: Request) -> SkillResult:
        candidates = await self._results(subject, context)
        if not candidates:
            return SkillResult(
                succeeded=False,
                text=f"I could not find a song or video called {subject}.",
            )
        return await self._resolve(candidates, action, subject, context)

    async def open_one(self, label: str, path: str, action: str,
                       context: SkillContext) -> SkillResult:
        return self._opened(label, path, "Playing", context)


class FolderSkill(Skill):
    name = "files"
    description = (
        "Open a folder such as Downloads, Music or Documents, or open a drive."
    )
    actions = ("open_folder", "list_folder", "search_files")
    keywords = ("folder", "drive", "downloads", "documents", "music",
                "videos", "pictures", "desktop")

    # What a person may say, and the folder it means.
    FOLDERS = {
        "downloads": "Downloads", "download": "Downloads",
        "music": "Music", "videos": "Videos", "video": "Videos",
        "pictures": "Pictures", "images": "Pictures", "photos": "Pictures",
        "desktop": "Desktop", "documents": "Documents",
        "docs": "Documents", "home": None,
    }

    def _subject(self, lowered: str) -> str:
        """The folder a request names, with the verb, article and suffix off.

        The article matters: "open my downloads" and "open downloads" have to
        reach the same answer, or the words a person naturally uses will not
        work while the shortened form does.
        """
        subject = lowered
        for verb in OPEN_VERBS:
            if subject.startswith(verb):
                subject = subject[len(verb):].strip()
                break

        for suffix in (" folder", " directory", " dir", " drive"):
            if subject.endswith(suffix):
                subject = subject[: -len(suffix)].strip()
                break

        for article in ARTICLES:
            if subject.startswith(article):
                subject = subject[len(article):].strip()
                break

        return subject.rstrip(" .:")

    async def can_handle(self, request: Request) -> float:
        if not any(request.normalized.startswith(verb) for verb in OPEN_VERBS):
            return 0.0

        # "open my cv" is a document, not a folder.
        if any(word in request.normalized
               for word in ("cv", "resume", "pdf", "docx")):
            return 0.0

        subject = self._subject(request.normalized)
        if not subject:
            return 0.0
        if subject in self.FOLDERS or (len(subject) == 1 and subject.isalpha()):
            return 0.85
        return 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        subject = self._subject(request.normalized)
        home = os.path.expanduser("~")

        # A bare drive letter, so "open i:" opens that drive.
        if len(subject) == 1 and subject.isalpha():
            root = f"{subject.upper()}:{os.sep}"
            if os.path.isdir(root):
                return self._opened(f"drive {subject.upper()}", root, context)
            return SkillResult(succeeded=False,
                               text=f"There is no drive {subject.upper()}.")

        name = self.FOLDERS.get(subject)
        if name is None and subject:
            import difflib

            close = difflib.get_close_matches(
                subject, list(self.FOLDERS), n=1, cutoff=0.6
            )
            name = self.FOLDERS[close[0]] if close else None

        if name is None and subject:
            return SkillResult(
                succeeded=False,
                text=f"I do not know a folder called {subject}.",
            )

        target = home if name is None else os.path.join(home, name)
        label = name or "your home folder"
        if not os.path.isdir(target):
            return SkillResult(
                succeeded=False,
                text=f"There is no {label} folder on this computer.",
            )
        return self._opened(label, target, context)

    def _opened(self, label: str, target: str,
                context: SkillContext) -> SkillResult:
        verdict = path_safety.validate(target, expect="folder")
        if not verdict.allowed:
            return SkillResult(succeeded=False, text=verdict.reason)

        try:
            context.run_blocking_sync(context.open_path, target)
        except OSError as error:
            return SkillResult(succeeded=False,
                               text=f"I could not open {label}.",
                               error=str(error))

        return SkillResult(
            succeeded=True,
            text=f"Opening {label}.",
            opened=[target],
            actions=[{"action": "open_folder", "target": target}],
        )


def _where_they_are(entries: list) -> str:
    """Where most of the results are, named the way a person would say it."""
    places: dict = {}
    for _label, path in entries:
        location = finder.media_location(path)
        places[location] = places.get(location, 0) + 1

    if not places:
        return "your folders"

    drive, folder = max(places, key=lambda key: places[key])
    if folder == "drive root":
        return f"the root of {drive}"
    return f"{folder} on {drive}"

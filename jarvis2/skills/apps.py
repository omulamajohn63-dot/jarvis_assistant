"""Applications, websites, screenshots, and the assistant's own conversation."""

from __future__ import annotations

import os

from jarvis2.core.models import Request, SkillResult
from jarvis2.files.text import unwrap_command
from jarvis2.safety import paths as path_safety
from jarvis2.skills.applications import find_application
from jarvis2.skills.base import Skill, SkillContext

# Names people use for applications, and what they are looking for.
APP_ALIASES = {
    "browser": "chrome", "chrome": "chrome", "google": "chrome",
    "edge": "edge", "firefox": "firefox", "safari": "safari",
    "editor": "code", "vs code": "code", "vscode": "code", "code": "code",
    "notepad": "notepad", "notes": "notepad", "calculator": "calculator",
    "calc": "calculator", "paint": "paint", "explorer": "explorer",
    "files": "explorer", "task manager": "task manager",
    "command prompt": "cmd", "cmd": "cmd", "terminal": "terminal",
    "powershell": "powershell", "word": "word", "excel": "excel",
    "powerpoint": "powerpoint", "outlook": "outlook", "spotify": "spotify",
    "settings": "settings", "taskbar": "explorer",
}

OPEN_VERBS = ("open ", "launch ", "start ", "run ", "switch to ")

# A shortcut is the usual form; an executable is what the PATH lookup finds.
PROGRAM_EXTENSIONS = frozenset({".lnk", ".exe", ".bat", ".cmd", ".com", ".msc"})


def _is_a_program(path: str) -> bool:
    """True when a path is something Windows can be asked to launch."""
    return path_safety.extension_of(path) in PROGRAM_EXTENSIONS

# Names the website branches handle, so "open google" opens the site and is not
# also treated as a document request.
SITES = {
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "gmail": "https://mail.google.com",
    "wikipedia": "https://en.wikipedia.org",
    "github": "https://github.com",
    "maps": "https://maps.google.com",
    "drive": "https://drive.google.com",
    "chatgpt": "https://chat.openai.com",
    "whatsapp": "https://web.whatsapp.com",
    "linkedin": "https://linkedin.com",
    "netflix": "https://netflix.com",
    "spotify web": "https://open.spotify.com",
    "stackoverflow": "https://stackoverflow.com",
}


def subject_of(text: str) -> str:
    """What was asked for, once the sentence has been taken apart.

    The wake word and the politeness come off first, because "hey jarvis please
    open chrome" and "open chrome" are the same instruction and a skill that only
    answers one phrasing is a skill that looks broken.
    """
    current = unwrap_command(text)

    for verb in OPEN_VERBS:
        if current.startswith(verb):
            current = current[len(verb):].strip()
            break

    for article in ("the ", "my ", "a ", "an "):
        if current.startswith(article):
            current = current[len(article):].strip()

    for suffix in (" app", " application", " program", " folder"):
        if current.endswith(suffix):
            current = current[: -len(suffix)].strip()

    return current


class ApplicationSkill(Skill):
    name = "apps"
    description = "Open an installed application by name."
    actions = ("open_application",)
    keywords = ("open", "launch", "start", "run", "switch to")

    async def can_handle(self, request: Request) -> float:
        lowered = unwrap_command(request.normalized)

        if not any(lowered.startswith(verb) for verb in OPEN_VERBS):
            return 0.0

        subject = subject_of(lowered)

        if not subject or subject in SITES:
            return 0.0
        return 0.9 if subject in APP_ALIASES else 0.6

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        subject = subject_of(request.normalized)

        wanted = APP_ALIASES.get(subject, subject)
        match = await context.run_blocking(
            find_application, wanted
        )

        if not match:
            return SkillResult(
                succeeded=False,
                text=f"I could not find an application called {subject}.",
            )

        label, target = match.label, match.target

        # Launching an installed program is allowed from Program Files, which is
        # where most of them live. The protected rule exists for paths a person
        # or a model typed, not for a shortcut found by scanning the Start Menu.
        # What is checked instead is that the target really is a program, so a
        # lookup that went wrong cannot open an arbitrary system file.
        if not _is_a_program(target):
            return SkillResult(
                succeeded=False,
                text=f"I found {label}, but it is not something I can launch.",
            )

        try:
            context.run_blocking_sync(context.open_path, target)
        except OSError as error:
            return SkillResult(
                succeeded=False,
                text=f"I could not open {label}.",
                error=str(error),
            )

        return SkillResult(
            succeeded=True,
            text=f"Opening {label}.",
            opened=[target],
            actions=[{"action": "open_application", "target": label}],
        )


class BrowserSkill(Skill):
    name = "browser"
    description = (
        "Open a website, or search Google for something and open the results."
    )
    actions = ("open_website", "search_web")
    keywords = ("open", "search", "google", "browse", "website", "url",
                "search google for")

    async def can_handle(self, request: Request) -> float:
        lowered = unwrap_command(request.normalized)

        for site in SITES:
            if f"open {site}" in lowered or lowered == site:
                return 0.95

        if any(lowered.startswith(prefix) for prefix in
               ("search google for", "google for", "search the web for",
                "look up on google", "search for")):
            return 0.9

        # "open foo.com" or "go to foo.com"
        for token in lowered.split():
            if "." in token and len(token) > 4 and not token.endswith("."):
                if token.split(".")[-1] in {"com", "org", "net", "io", "co",
                                            "in", "uk", "dev", "info", "edu"}:
                    return 0.85
        return 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        lowered = unwrap_command(request.normalized)

        for site, address in SITES.items():
            if f"open {site}" in lowered or lowered == site:
                return self._open(address, site, context)

        for prefix in ("search google for", "google for", "search the web for",
                       "look up on google", "search for"):
            if lowered.startswith(prefix):
                subject = lowered[len(prefix):].strip()
                if not subject:
                    return SkillResult(
                        succeeded=True, text="What should I search for?"
                    )
                query = subject.replace(" ", "+")
                return self._open(
                    f"https://www.google.com/search?q={query}",
                    f"a Google search for {subject}", context,
                )

        for token in lowered.split():
            cleaned = token.strip(".,")
            if "." in cleaned and cleaned.split(".")[-1] in {
                "com", "org", "net", "io", "co", "in", "uk", "dev", "info",
                "edu",
            }:
                address = cleaned if cleaned.startswith("http") else f"https://{cleaned}"
                return self._open(address, cleaned, context)

        return SkillResult(succeeded=False, text="I did not catch a website.")

    def _open(self, address: str, label: str,
              context: SkillContext) -> SkillResult:
        import webbrowser

        try:
            context.run_blocking_sync(webbrowser.open, address)
        except Exception as error:
            return SkillResult(
                succeeded=False,
                text=f"I could not open {label}.",
                error=str(error),
            )

        return SkillResult(
            succeeded=True,
            text=f"Opening {label}.",
            opened=[address],
            actions=[{"action": "open_website", "target": address}],
            sources=[{"title": label, "url": address, "kind": "web"}],
            metadata={"url": address},
        )


class ScreenshotSkill(Skill):
    name = "screenshot"
    description = "Take a screenshot of the screen and save it."
    actions = ("take_screenshot",)
    keywords = ("screenshot", "screen shot", "capture", "snap")

    # Where to save, best first. Some profiles have a Pictures folder that
    # refuses to be written to, and a screenshot is not worth failing over.
    FOLDERS = ("Pictures", "Desktop", "Downloads")

    # Asking for a screenshot by saying what it is for, rather than by saying
    # the word: "save it as invoice.png" only means something here.
    NAMING = ("save it as", "save as", "screenshot as", "name it")

    async def can_handle(self, request: Request) -> float:
        lowered = request.normalized

        if any(word in lowered for word in self.keywords):
            return 0.95
        if any(marker in lowered for marker in self.NAMING):
            # Only if something to capture is named. "save it as a copy" on its
            # own is not a screenshot request.
            return 0.6 if any(
                word in lowered
                for word in ("screen", "window", "desktop", "picture",
                             "image", "it", "this")
            ) else 0.0
        return 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        import asyncio

        def take():
            import pyautogui

            image = pyautogui.screenshot()
            home = os.path.expanduser("~")
            problems = []

            for folder_name in self.FOLDERS:
                folder = os.path.join(home, folder_name)
                name = self._wanted_name(request) or "screenshot.png"
                target = os.path.join(folder, name)
                try:
                    os.makedirs(folder, exist_ok=True)
                    image.save(target)
                    return target, problems
                except OSError as error:
                    problems.append(f"{folder}: {error}")
            return None, problems

        target, problems = await asyncio.to_thread(take)

        if not target:
            return SkillResult(
                succeeded=False,
                text="I took the screenshot but could not save it anywhere.",
                data={"problems": problems},
            )

        return SkillResult(
            succeeded=True,
            text=f"Screenshot saved as {path_safety.display(target)}.",
            opened=[target],
            actions=[{"action": "take_screenshot", "target": target}],
            metadata={"path": target},
        )

    def _wanted_name(self, request: Request) -> str:
        """A filename the user asked for, or None."""
        lowered = request.normalized
        for marker in ("screenshot as ", "save it as ", "save as ",
                       "name it "):
            if marker in lowered:
                wanted = lowered.split(marker, 1)[1].strip()
                wanted = "".join(
                    character for character in wanted
                    if character.isalnum() or character in " -_."
                ).strip()
                if wanted:
                    if not wanted.lower().endswith(".png"):
                        wanted += ".png"
                    return wanted
        return None

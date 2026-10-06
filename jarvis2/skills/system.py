"""Time, the date, power, and the state of the assistant itself."""

from __future__ import annotations

import datetime
import re

from jarvis2.core.models import Request, SkillResult
from jarvis2.skills.base import Skill, SkillContext

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

DAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)

# A power command is only recognised when the whole message is one of these.
POWER_PHRASES = {
    "shutdown": {
        "shutdown", "shut down", "shut down windows", "shut down pc",
        "shut down computer", "shut down this computer", "shut down my computer",
        "shut down the computer", "power off", "power off pc",
        "power off computer", "power off windows", "turn off", "turn off computer",
        "turn off pc",
    },
    "restart": {
        "restart", "restart windows", "restart pc", "restart computer",
        "restart this computer", "restart my computer", "restart the computer",
        "reboot", "reboot pc", "reboot computer", "reboot windows",
        "reboot this computer",
    },
}

SESSION_END_PHRASES = {
    "exit", "quit", "offline", "go offline", "shut down jarvis",
    "goodbye", "bye", "stop listening", "you can go", "thats all",
}

# Wording wrapped around a command without changing what it does.
COMMAND_FILLER = (
    "now", "please", "already", "then", "too", "as well",
    "computer", "pc", "laptop", "system", "machine", "desktop",
    "my computer", "this computer", "the computer", "my pc", "this pc",
    "my laptop", "my system",
)


def normalize_command(text: str) -> str:
    """Reduces a command to the bare form that identifies it.

    "Hey Jarvis, please shut down my computer now." and "shut down windows"
    both come out as "shut down". The loop runs until nothing more comes off,
    because the wording overlaps: removing "now" leaves "shut down my computer",
    which loses "computer", which leaves an article that has to go as well.
    """
    current = text.strip().lower().strip(" .?!,")
    articles = ("the ", "my ", "a ", "an ")

    shortened = True
    while shortened:
        shortened = False

        for prefix in ("please ", "can you ", "could you ", "would you ",
                       "hey jarvis "):
            if current.startswith(prefix):
                current = current[len(prefix):].strip(" .?!,")
                shortened = True

        for article in articles:
            if current.startswith(article):
                current = current[len(article):].strip(" .?!,")
                shortened = True
            if current.endswith(" " + article.strip()):
                current = current[: -len(article)].strip(" .?!,")
                shortened = True

        for filler in COMMAND_FILLER:
            if current.endswith(" " + filler):
                current = current[: -(len(filler) + 1)].strip(" .?!,")
                shortened = True

    return current


def power_intent(text: str) -> str | None:
    """Which power action a message asks for, if any.

    Matching is on the whole message rather than on the word appearing
    somewhere in it. That is the difference between "restart" doing what it says
    and "how do I restart Windows safely" looking the question up.
    """
    normalized = normalize_command(text)
    for action, phrases in POWER_PHRASES.items():
        if normalized in phrases:
            return action
    return None


def ends_session(text: str) -> bool:
    return normalize_command(text) in SESSION_END_PHRASES


# Words that only frame a question about the clock or the date, rather than
# naming a subject. "what is the time machine" mentions "time" but also
# "machine", so it is a question about the machine and not about the clock.
CLOCK_FILLER = {
    "what", "whats", "is", "are", "was", "the", "current", "now", "tell",
    "me", "please", "it", "of", "day", "today", "date", "time", "clock",
    "o'clock", "right", "exactly",
}

CLOCK_WORDS = {"time", "clock", "o'clock"}
DATE_WORDS = {"date", "day", "today", "calendar"}


def words_of(text: str) -> set:
    """Whole words, lowercased, with a possessive's "s" taken off."""
    found = re.findall(r"[a-z0-9']+", text.lower())
    return {
        word[:-2] if word.endswith("'s") else word
        for word in found
    }


class ClockSkill(Skill):
    name = "clock"
    description = "Tell the current time or the current date."
    actions = ("tell_time", "tell_date")
    keywords = ("time", "clock", "date", "today", "o'clock", "day")

    async def can_handle(self, request: Request) -> float:
        words = words_of(request.normalized)
        if not words & (CLOCK_WORDS | DATE_WORDS):
            return 0.0
        # Anything outside the filler means a subject was named, so this is a
        # question about that subject rather than about the clock.
        return 0.9 if words <= CLOCK_FILLER else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        now = datetime.datetime.now()
        words = words_of(request.normalized)

        if words & CLOCK_WORDS:
            return SkillResult(
                succeeded=True,
                text=f"It's {now.strftime('%I:%M %p').lstrip('0')}",
                data={"kind": "time", "value": now.isoformat()},
            )

        if words & DATE_WORDS:
            return SkillResult(
                succeeded=True,
                text=(
                    f"Today is {DAYS[now.weekday()]} "
                    f"{now.day} {MONTHS[now.month - 1]} {now.year}."
                ),
                data={"kind": "date", "value": now.isoformat()},
            )

        return SkillResult(succeeded=False, text="I did not catch a time or a date.")


class PowerSkill(Skill):
    name = "power"
    description = (
        "Shut down or restart Windows. Always asks the user first, and never "
        "runs from a question that merely mentions the word."
    )
    actions = ("shutdown", "restart")
    keywords = ()

    async def can_handle(self, request: Request) -> float:
        return 1.0 if power_intent(request.normalized) else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        action = power_intent(request.normalized)
        if not action:
            return SkillResult(succeeded=False, text="I did not catch that.")

        # The action is held rather than run. Nothing happens until
        # confirmations.resolve is called with the id that comes back here, and
        # the callable is stored with it so the arguments cannot be changed
        # between asking and answering.
        async def approved():
            return await self._run(action, context)

        confirmation = context.confirmations.evaluate_and_ask(
            action, "", run=approved,
            details={"source": request.source.value},
        )

        if confirmation is None:
            return await self._run(action, context)

        return SkillResult(
            succeeded=True,
            text=confirmation.prompt,
            confirmation=confirmation,
            actions=[{"action": "requested", "target": action}],
        )

    async def _run(self, action: str, context: SkillContext) -> SkillResult:
        import asyncio

        from jarvis2.voice.output import SpeechOutput

        if action == "shutdown":
            text = "Shutting down. Goodbye."
            argv = ["shutdown", "/s", "/f", "/t", "1"]
        else:
            text = "Restarting. One moment."
            argv = ["shutdown", "/r", "/f", "/t", "1"]

        SpeechOutput(context.settings).speak(text)

        def carry_out():
            import subprocess

            # A fixed argument list and no shell, so nothing that was said can
            # become a second command.
            completed = subprocess.run(argv, shell=False, check=False,
                                       capture_output=True)
            return completed.returncode

        returncode = await asyncio.to_thread(carry_out)

        if returncode:
            return SkillResult(
                succeeded=False,
                text="Windows would not do that.",
                error=f"shutdown returned {returncode}",
            )
        return SkillResult(
            succeeded=True, text=text,
            actions=[{"action": action, "target": "windows"}],
        )


class ExitSkill(Skill):
    name = "exit"
    description = "End the session. Leaves Windows running."
    actions = ()
    keywords = ()

    async def can_handle(self, request: Request) -> float:
        return 1.0 if ends_session(request.normalized) else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        name = context.settings.assistant_name
        return SkillResult(
            succeeded=True,
            text="Going offline. Goodbye.",
            actions=[{"action": "session_end", "target": name}],
            metadata={"stop": True},
        )


class ModeSkill(Skill):
    name = "mode"
    description = "Choose whether to listen or to be typed to."
    actions = ("set_input_mode",)
    keywords = ("keyboard mode", "voice mode", "stop listening",
                "start listening", "type mode", "listen mode")

    async def can_handle(self, request: Request) -> float:
        return 0.9 if any(
            phrase in request.normalized for phrase in self.keywords) else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        lowered = request.normalized

        voice = any(phrase in lowered for phrase in
                    ("voice mode", "start listening", "listen mode"))
        mode = "voice" if voice else "keyboard"

        session = context.session
        if session is not None:
            session.settings = session.settings.with_overrides(
                input_mode=mode
            )

        return SkillResult(
            succeeded=True,
            text=("I will listen from now on."
                  if voice else "I will wait for you to type."),
            actions=[{"action": "set_input_mode", "target": mode}],
        )


class StatusSkill(Skill):
    name = "status"
    description = "Report what this Jarvis can do and how it is set up."
    actions = ("list_skills",)
    keywords = ("what can you do", "help", "who are you", "who are you?",
                "what are you", "capabilities", "commands")

    async def can_handle(self, request: Request) -> float:
        return 0.95 if any(
            phrase in request.normalized
            for phrase in self.keywords
        ) else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        # The session carries the registry in normal use; the bare context is
        # accepted so this can be exercised on its own.
        registry = getattr(context.session, "registry", None) or context.registry
        skills = registry.describe() if registry else []

        summary = context.settings.public_summary
        capabilities = sorted({entry["description"] for entry in skills
                               if entry["description"]})

        return SkillResult(
            succeeded=True,
            text=(
                "I can search and open files, control applications, read "
                "documents, answer questions, browse the web, play media, take "
                "screenshots and help automate tasks."
            ),
            data={
                "capabilities": capabilities,
                "settings": summary,
                "skills": skills,
            },
        )


class SpeakerSkill(Skill):
    name = "speaker"
    description = "Stop or resume speaking replies, and change the volume."
    actions = ("set_muted", "set_volume")
    keywords = ("be quiet", "stop talking", "speak up", "quiet", "unmute",
                "volume", "louder", "quieter", "mute")

    async def can_handle(self, request: Request) -> float:
        text = request.normalized
        for phrase in self.keywords:
            if phrase in text:
                return 0.9
        return 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        text = request.normalized
        session = context.session

        if "volume" in text or "louder" in text or "quieter" in text:
            if "louder" in text:
                level = min(1.0, context.settings.voice_volume + 0.2)
            elif "quieter" in text:
                level = max(0.0, context.settings.voice_volume - 0.2)
            else:
                level = context.settings.voice_volume
            if session:
                session.settings = session.settings.with_overrides(
                    voice_volume=round(level, 2)
                )
            return SkillResult(
                succeeded=True,
                text=f"Volume is at {int(level * 100)} percent.",
                actions=[{"action": "set_volume", "target": str(level)}],
            )

        # Decided from the words, not toggled. "Be quiet" while already quiet
        # must still leave it quiet: a toggle would answer "I will speak again"
        # to somebody who just asked it to be quiet.
        quiet = ("be quiet", "stop talking", "stop speaking", "quiet",
                 "mute", "shut up")
        loud = ("speak up", "unmute", "speak again", "talk to me", "say more",
                "keep talking")

        if any(phrase in text for phrase in quiet):
            muted = True
        elif any(phrase in text for phrase in loud):
            muted = False
        else:
            muted = not context.settings.voice_enabled

        if session:
            session.settings = session.settings.with_overrides(
                voice_enabled=not muted
            )
        if session:
            session.apply_mute(muted)

        return SkillResult(
            succeeded=True,
            text=("I will print my replies instead of speaking them."
                  if muted else "I will speak again."),
            actions=[{"action": "set_muted", "target": str(muted)}],
        )

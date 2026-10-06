"""The interface every skill implements.

A skill says three things: what it is called, what it can do, and which safety
actions performing its work counts as. Everything else is the same, so adding a
capability means writing one class and registering it, not touching the router,
the web layer or the tests.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from jarvis2.core.models import Choice, Request, SkillResult
from jarvis2.logging_utils import get_logger

_log = get_logger("skills")


@dataclass
class SkillContext:
    """Everything a skill is given besides the request.

    Passed in rather than reached for, so a skill can be tested with fakes and
    so no skill can quietly acquire a dependency the others do not have.
    """

    settings: Any
    permissions: Any
    confirmations: Any
    bus: Any = None
    # Shared state for the session: the last thing opened, a numbered list
    # waiting for a choice, the conversation so far, the registry.
    session: Any = None
    # The memory store, or None when memory is off.
    memory: Any = None
    # The AI provider, or None when none is configured.
    provider: Any = None
    # The bridge to the V1 assistant, which does the searching and reading.
    wikipedia: Any = None
    # Which actions this installation is allowed to perform.
    #: Coroutine: run_blocking(func, *args, **kwargs)
    run_blocking: Any = None
    #: Called with a path to hand it to the operating system.
    open_path: Any = None

    def log(self, action: str, **data: Any) -> None:
        _log.info(action, extra={"data": data})

    def run_blocking_sync(self, function, *args, **kwargs):
        """Runs blocking work from inside code that is already off the loop.

        Skills are async and should await run_blocking. This exists for the few
        places that cannot, such as a callable handed to the confirmation
        manager and therefore called from a plain function.
        """
        if self.run_blocking is None:
            return function(*args, **kwargs)

        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return function(*args, **kwargs)
        if loop.is_running():
            # Called from inside the loop, so the work is done here rather than
            # waiting on a future nobody is going to await.
            return function(*args, **kwargs)
        return loop.run_until_complete(self.run_blocking(function, *args, **kwargs))


class Skill(abc.ABC):  # noqa: B024
    """One thing Jarvis can do.

    Subclasses set ``name``, ``description`` and ``actions``, and implement
    ``can_handle`` and ``execute``. Nothing else is required.
    """

    #: The name a model and the registry both refer to this by. Unique.
    name: str = ""

    #: Shown to the AI layer and returned by GET /api/skills. Written in plain
    #: language, because it is read by something deciding what to ask for.
    description: str = ""

    #: The safety actions performing this counts as. Checked against the
    #: permission set before the skill is ever run.
    actions: tuple = ()

    #: Words that give this skill a head start when scoring. Optional.
    keywords: tuple = ()

    #: Set when the skill needs to know the settings object to work.
    requires: tuple = ()

    @property
    def risk(self):
        """The risk of the worst thing this skill does."""
        from jarvis2.safety.permissions import highest_risk
        from jarvis2.safety.policy import Risk

        if not self.actions:
            return Risk.LOW
        return highest_risk(self.actions)

    @property
    def tool_schema(self) -> dict:
        """The description of this skill given to an AI provider.

        Built from the class rather than written twice, so the model is never
        told about something the code does not do.
        """
        from jarvis2.ai.prompts import tool_for_skill

        return tool_for_skill(self)

    async def can_handle(self, request: Request) -> float:
        """How well this skill fits a request, from 0 (not at all) to 1.

        Returning a number rather than a bool lets a router choose between two
        skills that both plausibly fit, instead of whichever was registered
        first.
        """
        text = request.normalized
        if not text:
            return 0.0

        hits = sum(1 for word in self.keywords if word in text)
        if not hits:
            return 0.0
        return min(1.0, 0.5 + 0.1 * hits)

    async def execute(self, request: Request, context: SkillContext) -> SkillResult:
        """Does the work.

        The result's ``succeeded`` must come from what actually happened. Saying
        a file was opened when it was not is the single worst thing this
        assistant can do, so nothing infers success from a skill having run.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    def describe(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "actions": list(self.actions),
            "risk": self.risk.label,
            "keywords": list(self.keywords),
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


class PassiveSkill(Skill):
    """For a request that is already answered.

    Used when there is nothing to do but answer: a greeting, or a question the
    conversation layer has already worked out.
    """

    reply: str = ""

    def __init__(self, name: str = "", description: str = "", reply: str = ""):
        self.name = name or type(self).name
        self.description = description or type(self).description
        self.reply = reply or type(self).reply

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        return SkillResult(succeeded=True, text=self.reply)


def choices_from(pairs: list, question: str = "") -> list:
    """Builds a numbered list from (label, payload) pairs."""
    return [
        Choice(number=index, label=str(label), payload=payload)
        for index, (label, payload) in enumerate(pairs, 1)
    ]

"""Finding the skill that fits a request.

The registry is the only place that knows what skills exist. The AI layer is
given their descriptions rather than a copy of their internals, so a new skill
becomes available to the model by being registered and nothing else.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from jarvis2.logging_utils import get_logger
from jarvis2.safety import permissions as permissions_module
from jarvis2.skills.base import Skill

_log = get_logger("registry")


@dataclass
class Candidate:
    """One skill that might handle a request, with how well it fits."""

    skill: Skill
    score: float

    @property
    def name(self) -> str:
        return self.skill.name


class SkillRegistry:
    """Holds the skills and picks between them."""

    def __init__(self, skills: Iterable[Skill] = (), permissions=None):
        self._skills: dict[str, Skill] = {}
        self.permissions = permissions or permissions_module.default_permissions()
        for skill in skills:
            self.register(skill)

    # ------------------------------------------------------------------
    def register(self, skill: Skill) -> Skill:
        """Adds a skill, checking its name and its declared actions first."""
        if not skill.name:
            raise ValueError(f"{type(skill).__name__} has no name")
        if skill.name in self._skills:
            raise ValueError(f"a skill called {skill.name!r} is already registered")

        # A skill that asks for an action this installation does not allow is
        # refused now, at registration, rather than at the moment somebody uses
        # it. Failing to start is better than failing mid-conversation.
        if skill.actions:
            try:
                permissions_module.require(self.permissions, skill.actions)
            except permissions_module.PermissionError_ as error:
                raise ValueError(
                    f"{skill.name} declares actions this Jarvis may not perform: {error}"
                ) from error

        self._skills[skill.name] = skill
        _log.debug("registered skill %s (%s)", skill.name, skill.risk.label)
        return skill

    def unregister(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self):
        return iter(self._skills.values())

    @property
    def names(self) -> list:
        return list(self._skills)

    def describe(self) -> list:
        """What this Jarvis can do, in a form an interface can render."""
        return [skill.describe() for skill in self._skills.values()]

    def tool_schemas(self) -> list:
        """The same thing as a list of tool definitions for an AI provider."""
        return [skill.tool_schema for skill in self._skills.values()]

    # ------------------------------------------------------------------
    async def candidates(self, request) -> list:
        """Every skill that fits, best first.

        A skill whose ``can_handle`` raises is skipped rather than allowed to
        take the whole request down: one broken skill should not stop Jarvis
        from answering.
        """
        found: list[Candidate] = []

        for skill in self._skills.values():
            try:
                score = await skill.can_handle(request)
            except Exception as error:
                _log.warning(
                    "skill %s failed to score a request", skill.name,
                    exc_info=True, extra={"error": str(error)},
                )
                continue

            if score and score > 0:
                found.append(Candidate(skill, float(score)))

        found.sort(key=lambda candidate: candidate.score, reverse=True)
        return found

    async def select(self, request, minimum: float = 0.0) -> Candidate | None:
        """The single best skill, or None when nothing fits well enough."""
        found = await self.candidates(request)
        if not found:
            return None
        best = found[0]
        return best if best.score >= minimum else None

    def route(self, name: str, arguments: dict, context) -> Candidate:
        """Looks a skill up by name, for a tool request from a model.

        Raises rather than guessing, so a model that asks for a skill which does
        not exist is told so instead of being given the nearest thing.
        """
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"there is no skill called {name!r}")
        return Candidate(skill, 1.0)

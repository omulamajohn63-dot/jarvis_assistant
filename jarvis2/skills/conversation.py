"""Talking, remembering, and answering.

The conversation skill is the one place that reads what has already happened in
a session, which is what lets "the previous file" and "that one" mean something.
"""

from __future__ import annotations

from jarvis2.core.models import Request, SkillResult
from jarvis2.skills.base import Skill, SkillContext

GREETINGS = {
    "hello", "hi", "hey", "morning", "evening", "good morning",
    "good afternoon", "good evening", "howdy",
}

# What somebody says when they want to hear what has been kept. Checked before
# anything about remembering, because "what do you remember about me" is a
# question about memory, not a request to store the words "about me".
RECALL_PHRASES = (
    "what do you remember", "what do you know about me",
    "what have you remembered", "what do you remember about",
)

# What somebody says when they want something forgotten.
FORGET_PHRASES = ("forget", "clear my memory", "disable memory",
                  "stop remembering", "forget everything")


class ConversationSkill(Skill):
    name = "conversation"
    description = (
        "Answer a question, hold a conversation, remember what the user asks "
        "you to remember, and forget it again."
    )
    actions = ("answer_question", "recall_memory", "greet")
    keywords = ("who are you", "what can you do", "remember", "forget",
                "what did i", "what was the file", "hello", "hi", "hey")

    async def can_handle(self, request: Request) -> float:
        lowered = request.normalized
        for phrase in self.keywords + RECALL_PHRASES + FORGET_PHRASES:
            if phrase in lowered:
                return 0.9
        if lowered in GREETINGS:
            return 0.9
        return 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        lowered = request.normalized

        if lowered in GREETINGS:
            return self._greet(context)

        # Recall and forget are decided before remember, or a question about
        # memory is answered by remembering it.
        if any(phrase in lowered for phrase in RECALL_PHRASES):
            return self._recall(context)

        if any(phrase in lowered for phrase in FORGET_PHRASES):
            return self._forget(lowered, context)

        if "remember" in lowered:
            return await self._remember(request, context)

        # Anything else needs the AI layer, which the router sends it to.
        return SkillResult(
            succeeded=False,
            text="",
            metadata={"needs_ai": True},
        )

    # ------------------------------------------------------------------
    def _greet(self, context: SkillContext) -> SkillResult:
        import datetime

        hour = datetime.datetime.now().hour
        part = (
            "Good morning" if hour < 12
            else "Good afternoon" if hour < 16
            else "Good evening"
        )
        return SkillResult(
            succeeded=True,
            text=f"{part}! How can I help?",
            actions=[{"action": "greet",
                      "target": context.settings.assistant_name}],
        )

    async def _remember(self, request: Request,
                        context: SkillContext) -> SkillResult:
        if not context.settings.memory_enabled or context.memory is None:
            return SkillResult(succeeded=False, text="Memory is switched off.")

        lowered = request.normalized
        fact = lowered.split("remember", 1)[1].strip()
        for marker in ("that ", "this "):
            if fact.startswith(marker):
                fact = fact[len(marker):]
        fact = fact.strip(" ,")

        if not fact:
            return SkillResult(succeeded=True,
                               text="What should I remember?")

        stored = await context.run_blocking(context.memory.remember, fact)
        if stored is None:
            # The store refused it. Saying why matters more than pretending.
            return SkillResult(
                succeeded=False,
                text="I will not remember that one, because it looks like "
                     "something private.",
            )

        return SkillResult(
            succeeded=True,
            text="I will remember that.",
            actions=[{"action": "remember", "target": fact}],
        )

    def _forget(self, lowered: str, context: SkillContext) -> SkillResult:
        if context.memory is None:
            return SkillResult(succeeded=False, text="Memory is switched off.")

        if "disable" in lowered:
            if context.session is not None:
                context.session.settings = context.session.settings.with_overrides(
                    memory_enabled=False
                )
            return SkillResult(
                succeeded=True,
                text="I will stop remembering things from now on.",
                actions=[{"action": "disable_memory", "target": "on"}],
            )

        if "clear" in lowered:
            context.memory.clear()
            return SkillResult(
                succeeded=True,
                text="I have forgotten everything.",
                actions=[{"action": "clear_memory", "target": "all"}],
            )

        context.memory.forget_last()
        return SkillResult(
            succeeded=True,
            text="I have forgotten that.",
            actions=[{"action": "forget", "target": "last"}],
        )

    def _recall(self, context: SkillContext) -> SkillResult:
        if not context.settings.memory_enabled or context.memory is None:
            return SkillResult(
                succeeded=False,
                text="I am not remembering anything at the moment.",
            )

        facts = context.memory.facts()
        if not facts:
            return SkillResult(
                succeeded=True,
                text="I have not been told anything worth remembering yet.",
            )

        listed = "; ".join(facts)
        return SkillResult(
            succeeded=True,
            text=f"I remember: {listed}.",
            data={"facts": facts},
        )

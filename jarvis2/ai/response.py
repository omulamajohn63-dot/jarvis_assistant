"""Turning what a model asked for into something that actually happened.

Two steps, and the order is the safety property. The tool request is checked
first: the name must be a registered skill, the arguments must fit the schema,
and the skill must be allowed to perform them. Only then is anything run, and
only through the same path a typed command would take, so a tool call is not a
way round the confirmation that the same action would get otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis2.ai.prompts import bound_messages
from jarvis2.ai.provider import (
    AIResponse,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
)
from jarvis2.core.models import Request, SkillResult
from jarvis2.logging_utils import get_logger
from jarvis2.safety import permissions as permissions_module

_log = get_logger("ai.response")

# How many times a model may pick a tool before it is asked to explain itself.
MAX_TOOL_ROUNDS = 4


@dataclass
class ToolOutcome:
    """What happened when a tool a model asked for was run."""

    call: ToolCall
    succeeded: bool
    text: str
    data: dict


class ToolValidator:
    """Checks a tool request before anything is run."""

    def __init__(self, registry, permissions=None):
        self.registry = registry
        self.permissions = permissions or permissions_module.default_permissions()

    def validate(self, call: ToolCall) -> tuple:
        """Returns (skill, error). Exactly one of the two is None."""
        name = (call.name or "").strip()

        if not name:
            return None, "no tool was named"

        skill = self.registry.get(name)
        if skill is None:
            # Named plainly rather than mapped to the nearest thing. A model
            # guessing here would produce a wrong action with a right name.
            return None, f"there is no tool called {name!r}"

        arguments = call.arguments
        if not isinstance(arguments, dict):
            return None, "the arguments were not an object"

        allowed = set(skill.tool_schema["function"]["parameters"].get(
            "properties", {}
        ))
        if allowed:
            unexpected = sorted(set(arguments) - allowed)
            if unexpected:
                return None, (
                    f"{name} does not take {', '.join(unexpected)}"
                )

        if skill.actions:
            try:
                permissions_module.require(self.permissions, skill.actions)
            except permissions_module.PermissionError_ as error:
                return None, str(error)

        return skill, None


class ResponseBuilder:
    """Asks a provider, runs what it asked for, and answers about the result."""

    def __init__(self, settings, registry, conversation, memory=None,
                 validator: ToolValidator = None, runner=None):
        self.settings = settings
        self.registry = registry
        self.conversation = conversation
        self.memory = memory
        self.validator = validator or ToolValidator(registry)
        #: Called as runner(skill, request) to run one tool. The assistant
        #: supplies this so a tool goes through the same execution path, and the
        #: same confirmation, as the same command typed by hand.
        self.runner = runner

    # ------------------------------------------------------------------
    def build_messages(self, question: str, memories: list | None = None) -> list:
        from jarvis2.ai.prompts import build_system_prompt

        system = build_system_prompt(
            self.settings, list(self.registry), memories,
        )
        messages = [{"role": "system", "content": system}]
        for turn in self.conversation.history(self.settings.ai_history_turns):
            if turn.request:
                messages.append({"role": "user", "content": turn.request})
            if turn.reply:
                messages.append({"role": "assistant", "content": turn.reply})
        messages.append({"role": "user", "content": question})

        return bound_messages(
            messages, self.settings.ai_history_turns,
            self.settings.ai_history_chars,
        )

    def tools(self) -> list:
        return self.registry.tool_schemas()

    # ------------------------------------------------------------------
    async def run(self, request: Request) -> SkillResult:
        """Answers with a model, running any tool it asks for.

        Returns a SkillResult whose ``succeeded`` reflects what really
        happened. A model that cannot be reached is not an error here: the
        caller falls back to the deterministic router.
        """
        provider = request.metadata.get("provider")
        if provider is None:
            raise ProviderUnavailable("no provider")

        question = request.text
        messages = self.build_messages(question, self._memories())
        tools = self.tools()

        performed: list[ToolOutcome] = []

        for _round in range(MAX_TOOL_ROUNDS):
            answer = await provider.generate(messages, tools=tools)

            if not answer.wants_a_tool:
                return self._final(answer, performed)

            for call in answer.tool_calls:
                outcome = await self._run_tool(call, request)
                performed.append(outcome)
                messages.append({
                    "role": "assistant",
                    "content": f"I used {call.name}.",
                })
                messages.append({
                    "role": "user",
                    "content": _tool_feedback(outcome),
                })

            messages = bound_messages(
                messages, self.settings.ai_history_turns,
                self.settings.ai_history_chars,
            )

        # Still asking for tools after several rounds. Rather than let it keep
        # going, the answer it has is used.
        _log.warning("model kept asking for tools after %d rounds",
                     MAX_TOOL_ROUNDS)
        return SkillResult(
            succeeded=True,
            text=answer.text or "I could not finish that.",
            actions=[{"action": "tool_rounds_exceeded", "target": "model"}],
        )

    # ------------------------------------------------------------------
    async def _run_tool(self, call: ToolCall, request: Request) -> ToolOutcome:
        """Checks a tool request, then runs it through the normal path."""
        skill, error = self.validator.validate(call)
        if skill is None:
            # Told plainly, so the model can correct itself on the next round.
            return ToolOutcome(call, False, error or "that tool is not available", {})

        if self.runner is None:
            return ToolOutcome(call, False, "nothing can run tools here", {})

        try:
            result = await self.runner(
                skill, request.with_arguments(call.arguments)
            )
        except Exception as failure:
            _log.error("tool %s failed", call.name, exc_info=True)
            return ToolOutcome(
                call, False,
                f"{call.name} failed: {type(failure).__name__}: {failure}", {},
            )

        return ToolOutcome(
            call, result.succeeded, result.text or "It did not say.",
            {"opened": result.opened, "choices": len(result.choices)},
        )

    def _memories(self) -> list | None:
        if not self.settings.memory_enabled or self.memory is None:
            return None
        facts = self.memory.facts()
        return facts or None

    def _final(self, answer: AIResponse, performed: list) -> SkillResult:
        """Turns the model's last answer into a result.

        If a tool it asked for failed, that is stated rather than smoothed over.
        A model which reports success for something that failed is the failure
        mode worth being blunt about.
        """
        text = (answer.text or "").strip()
        succeeded = True
        sources: list = []
        opened: list = []
        error: str | None = None

        for outcome in performed:
            opened.extend(outcome.data.get("opened") or [])
            if not outcome.succeeded:
                succeeded = False
                error = outcome.text

        if not text and performed:
            text = performed[-1].text

        if not text:
            text = "I did not have an answer for that."
            succeeded = False

        return SkillResult(
            succeeded=succeeded,
            text=text,
            sources=sources,
            opened=opened,
            actions=[{"action": "ai", "target": answer.provider or "model"}],
            error=error,
        )


def _tool_feedback(outcome: ToolOutcome) -> str:
    """What the model is told after a tool ran.

    Success or failure is reported exactly as it happened, so the model cannot
    talk itself into believing a failed action worked.
    """
    if outcome.succeeded:
        return f"{outcome.call.name} succeeded. Result: {outcome.text}"
    return (
        f"{outcome.call.name} did not succeed. Result: {outcome.text}. "
        "Tell the user what happened rather than claiming it worked."
    )


def fallback_text(error: Exception) -> str:
    """What to say when the model could not be reached at all.

    Degraded, not silent: the deterministic router has already handled the
    request, so this only appears if there was nothing to fall back to.
    """
    if isinstance(error, ProviderUnavailable):
        return (
            "I could not reach the AI service, so I am running without it."
        )
    if isinstance(error, ProviderError):
        return f"The AI service had a problem: {error}"
    return "Something went wrong reaching the AI service."

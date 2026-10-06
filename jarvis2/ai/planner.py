"""Multi-step tasks.

"Open my CV and my job applications folder" is two things to do, and the second
one only makes sense once the first has happened. A plan is a list of steps that
is checked before anything runs, then worked through one at a time, with each
result visible to the step after it.

Two rules keep this honest. A step never runs until the whole plan has been
through the safety policy, so a risky step at the end cannot be reached by
accident through an innocent first step. And a step that needs the user to choose
stops the plan there rather than being guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis2.ai.provider import (
    AIResponse,
    ProviderError,
    ProviderUnavailable,
    parse_json,
)
from jarvis2.core.models import Request, Response, Status
from jarvis2.logging_utils import get_logger

_log = get_logger("planner")

# Longest first, so "and then" is matched before "and".
CONNECTORS = (
    "and then", "after that", "and after", "and also", "and", "then",
    "also", "afterwards", "plus",
)

# A step is a command in its own right. Anything else in the plan is not a step
# and must not be run.
MAX_STEPS = 6


@dataclass
class PlanStep:
    """One thing to do."""

    tool: str
    arguments: dict = field(default_factory=dict)
    text: str = ""
    # False once a step is found to need the user, which stops the plan.
    runnable: bool = True
    risk: str = "low"
    # Filled in as the step runs.
    result: Response | None = None

    def as_dict(self) -> dict:
        entry = {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "text": self.text,
            "runnable": self.runnable,
            "risk": self.risk,
            "done": self.result is not None,
        }
        if self.result is not None:
            entry["opened"] = list(self.result.opened)
            entry["status"] = self.result.status.value
        return entry


@dataclass
class Plan:
    """A whole task, in order."""

    goal: str
    steps: list = field(default_factory=list)
    # The reason the plan stopped early, if it did.
    stopped_because: str = ""

    def __len__(self) -> int:
        return len(self.steps)

    @property
    def runnable_steps(self) -> list:
        return [step for step in self.steps if step.runnable]

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "steps": [step.as_dict() for step in self.steps],
            "stoppedBecause": self.stopped_because,
        }


def split_clauses(text: str) -> list:
    """Splits "open cv and my folder" into the two things it asks for.

    A split is only made where a connector joins two imperatives, so "rock and
    roll" is not read as two instructions. Splitting on "and" alone would turn a
    single request into two, and the second would have nothing to do.
    """
    lowered = " ".join(text.lower().split())

    for connector in CONNECTORS:
        if connector in lowered:
            left, _, right = lowered.partition(connector)
            if not left.strip() or not right.strip():
                continue
            first = _starts_with_verb(left.strip())
            second = _starts_with_verb(right.strip())
            # Both halves have to be instructions, or it was one sentence that
            # happened to contain the word.
            if first and second:
                return [left.strip(), right.strip()]
    return [lowered]


def _starts_with_verb(phrase: str) -> bool:
    from jarvis2.skills.files import strip_verb

    return strip_verb(phrase)[0] is not None


class Planner:
    """Builds and runs plans."""

    def __init__(self, registry, conversation, runner=None):
        self.registry = registry
        self.conversation = conversation
        self.runner = runner

    # ------------------------------------------------------------------
    async def from_request(self, request: Request) -> Plan:
        """A plan built without a model, by splitting on connectives.

        Used when no model is configured, and as the first thing tried when one
        is: a plan made of whole clauses the user actually said is more reliable
        than one a model rewrote.
        """
        clauses = split_clauses(request.normalized)
        if len(clauses) <= 1:
            return Plan(goal=request.normalized, steps=[])

        steps = []
        for clause in clauses:
            skill = await self._skill_for(clause)
            if skill is None:
                steps.append(PlanStep(tool="", text=clause, runnable=False))
                continue
            steps.append(PlanStep(
                tool=skill.name, text=clause, risk=skill.risk.label,
                arguments={"text": clause},
            ))

        return Plan(goal=request.normalized, steps=steps[:MAX_STEPS])

    async def _skill_for(self, clause: str):
        """The best skill for one clause.

        Scored the same way the router scores, so a plan's steps and a single
        command reach the same skill for the same words.
        """
        from jarvis2.core.models import Request as Inner

        candidates = await self.registry.candidates(Inner(text=clause))
        return candidates[0].skill if candidates else None

    async def from_model(self, request: Request, provider) -> Plan:
        """A plan from a model, or the one built without it."""
        if provider is None:
            return await self.from_request(request)

        tools = self.registry.tool_schemas()
        tools.append({
            "type": "function",
            "function": {
                "name": "run_task",
                "description": (
                    "Break a multi-step request into the individual commands to "
                    "run, in order. Use one step per action."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "description": "The steps, in the order to do them",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "tool": {"type": "string"},
                                    "arguments": {"type": "object"},
                                },
                                "required": ["tool"],
                            },
                        },
                    },
                    "required": ["steps"],
                },
            },
        })

        try:
            answer = await provider.generate(
                [{"role": "user", "content": request.normalized}], tools=tools
            )
        except (ProviderUnavailable, ProviderError) as error:
            _log.info("planning without a model: %s", error)
            return await self.from_request(request)

        return await self._from_answer(request, answer)

    async def _from_answer(self, request: Request, answer: AIResponse) -> Plan:
        """Turns a model's plan into checked steps.

        A plan naming a tool that is not registered is marked unrunnable rather
        than matched to the nearest thing, so a model's mistake stops here
        instead of becoming a wrong action.
        """
        steps = []

        for call in answer.tool_calls:
            if call.name == "run_task":
                payload = parse_json(_as_text(call.arguments)) or {}
                for entry in payload.get("steps") or []:
                    if not isinstance(entry, dict):
                        continue
                    steps.append(self._make_step(entry))
                continue
            steps.append(self._make_step({
                "tool": call.name, "arguments": call.arguments,
            }))

        if not steps:
            # The model named no steps, so the clause split is used instead.
            return await self.from_request(request)

        plan = Plan(goal=request.normalized, steps=steps[:MAX_STEPS])
        first_unrunnable = next(
            (index for index, step in enumerate(plan.steps)
             if not step.runnable), None
        )
        if first_unrunnable is not None:
            # Everything after a step that cannot run is cancelled as well,
            # because a plan that started differently does not mean the same
            # thing half way through.
            plan.stopped_because = (
                f"I could not work out what to do about "
                f"\"{plan.steps[first_unrunnable].text}\""
            )
            for step in plan.steps[first_unrunnable:]:
                step.runnable = False
        return plan

    def _make_step(self, entry: dict) -> PlanStep:
        tool = str(entry.get("tool") or "").strip()
        arguments = entry.get("arguments")
        arguments = dict(arguments) if isinstance(arguments, dict) else {}

        skill = self.registry.get(tool)
        if skill is None:
            return PlanStep(tool=tool, arguments=arguments,
                            runnable=False, text=f"unknown tool {tool!r}")

        return PlanStep(
            tool=tool, arguments=arguments, risk=skill.risk.label,
            text=arguments.get("text") or arguments.get("query") or "",
        )

    # ------------------------------------------------------------------
    async def run(self, plan: Plan, request: Request, emit=None) -> list:
        """Works through a plan, stopping where it must.

        Every step goes through the same runner a single command uses, so a
        risky step is held for confirmation exactly as it would be if it had been
        asked for on its own.
        """
        if not plan.steps:
            return []

        results = []
        for index, step in enumerate(plan.steps):
            if not step.runnable:
                break
            if emit:
                await emit(step, index)

            if self.runner is None:
                break

            outcome = await self.runner(step, request)
            step.result = outcome
            results.append(outcome)

            # A step that fails, or that needs the user, stops everything.
            # Continuing would mean doing later steps on an assumption that has
            # just been shown to be wrong.
            if outcome.needs_input or outcome.status in {
                Status.FAILED, Status.STOP,
            }:
                plan.stopped_because = (
                    plan.stopped_because or outcome.text
                )
                for later in plan.steps[index + 1:]:
                    later.runnable = False
                break

        return results

    def describe(self, plan: Plan) -> str:
        """A plan in words, for the activity panel."""
        if not plan.steps:
            return plan.goal
        parts = [step.text or step.tool for step in plan.steps]
        return ", then ".join(part for part in parts if part)


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        import json

        return json.dumps(value)
    return str(value)

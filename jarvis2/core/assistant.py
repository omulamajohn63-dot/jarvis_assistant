"""The assistant.

Everything a user says arrives here, whether it came from the keyboard, the
microphone or the browser, and everything they hear or see leaves from here.
No interface holds a command, and no skill knows which interface asked.

The pipeline:

    normalize -> context -> route -> plan -> safety -> skill -> result -> reply

Each step falls back to the one before it failed, which is what makes the
assistant still useful with no AI provider, and what makes every V1 command keep
working whether or not anything was rewritten.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from jarvis2.ai.provider import ProviderError, ProviderUnavailable
from jarvis2.core import events as bus_events
from jarvis2.core.conversation import Conversation
from jarvis2.core.events import EventBus
from jarvis2.core.memory import LongTermMemory, MemoryStore, Preferences
from jarvis2.core.models import (
    Choice,
    Request,
    Response,
    SkillResult,
    Source,
    Status,
)
from jarvis2.core.router import Router
from jarvis2.logging_utils import configure, get_logger
from jarvis2.safety.confirmations import ConfirmationManager
from jarvis2.safety.permissions import default_permissions
from jarvis2.skills import build_default_registry
from jarvis2.skills.base import Skill, SkillContext

_log = get_logger("assistant")

# Asking for more than one thing at a time. Kept small on purpose: a plan that
# fires on ordinary sentences would break them.
SEVERAL_CUES = (" and then ", " and also ", " then open ", " after that ",
                " and open ", " and play ", " and read ")


def _wants_several_things(text: str) -> bool:
    """True when a request is plainly for more than one action.

    Only connectives that join two instructions count, and the first half has to
    look like a command. "and" alone is not enough, or "rock and roll" would
    become a two step plan.

    Only the first half is checked, because the connective carries the second
    verb itself: "open downloads and open documents" says "open" once.
    """
    if not any(cue in text for cue in SEVERAL_CUES):
        return False

    from jarvis2.skills.files import strip_verb

    first = text
    for cue in SEVERAL_CUES:
        if cue in first:
            first = first.split(cue, 1)[0]
            break

    return bool(strip_verb(first)[0])


class JarvisAssistant:
    """One instance is one conversation with one set of settings."""

    def __init__(self, settings=None, registry=None, provider=None,
                 wikipedia=None, bus: EventBus = None, memory=None,
                 permissions=None, speech=None):
        self.settings = settings
        self.permissions = permissions or default_permissions()
        self.registry = registry or build_default_registry(self.permissions)
        self.bus = bus or EventBus()
        self.conversation = Conversation(max_turns=settings.ai_history_turns
                                        if settings else 12)
        self.confirmations = ConfirmationManager(
            confirm_dangerous=settings.confirm_dangerous_actions
            if settings else True,
            confirm_medium=settings.require_confirmation_for_medium_risk
            if settings else False,
        )
        self.provider = provider
        self.memory = memory
        self.wikipedia = wikipedia
        # Whether replies are said out loud on this computer. The dashboard
        # plays its own audio, so there it is muted.
        self.muted = not settings.voice_enabled if settings else True
        self.speech = speech

        if self.memory is None and settings and settings.memory_enabled:
            root = Path(settings.extra.get("root", Path.cwd()))
            store = MemoryStore(
                root / settings.memory_dir,
                max_facts=settings.memory_max_facts,
            )
            self.memory = LongTermMemory(store)

        self.preferences = Preferences(self.memory, self.settings) \
            if self.memory else None

        self.router = Router(
            self.registry, self.conversation, provider=self.provider,
        )
        from jarvis2.ai.planner import Planner

        self.planner = Planner(
            self.registry, self.conversation, runner=self._run_plan_step
        )
        self._tool_runner = None

    # ==================================================================
    # Setup
    # ==================================================================
    def attach_tool_runner(self, runner) -> None:
        """Tells the AI layer how to run a skill, so a tool call is not a
        second, unchecked way in."""
        self._tool_runner = runner

    @property
    def context(self) -> SkillContext:
        return SkillContext(
            settings=self.settings,
            permissions=self.permissions,
            confirmations=self.confirmations,
            bus=self.bus,
            session=self,
            memory=self.memory,
            provider=self.provider,
            wikipedia=self.wikipedia,
            run_blocking=self._run_blocking,
            open_path=self._open_path,
        )

    async def _run_blocking(self, function, *args, **kwargs):
        """Runs blocking work off the event loop.

        Everything slow goes through here: scanning a drive, reading a document,
        calling a provider, handing a path to Windows. The loop stays free so the
        interface never waits on it.
        """
        return await asyncio.to_thread(function, *args, **kwargs)

    # ==================================================================
    # The pipeline
    # ==================================================================
    async def handle_input(self, text, source: Source = Source.TERMINAL,
                           **metadata) -> Response:
        """Handles one thing the user said."""
        request = Request(
            text=str(text or ""),
            source=source if isinstance(source, Source) else Source(source),
            metadata=metadata,
        )
        return await self.handle(request)

    async def handle(self, request: Request) -> Response:
        started = time.perf_counter()
        # Bound to the loop this request is running in, so a coroutine listener
        # can be scheduled onto it.
        self.bus.bind_loop()
        await bus_events.emit_request(self.bus, request)

        try:
            response = await self._dispatch(request)
        except Exception as error:
            # Logged in full here, summarised for the user. A traceback is not an
            # answer to "what is the time".
            _log.exception("request failed")
            response = Response(
                text="Something went wrong. I have written down what happened.",
                status=Status.FAILED,
                source=request.source,
                error=f"{type(error).__name__}: {error}",
            )
            await bus_events.emit_error(self.bus, "handle", str(error))

        response.took = time.perf_counter() - started

        if not request.normalized:
            response = Response(text="I did not catch that.", source=request.source)
            response.took = time.perf_counter() - started

        await self._remember_turn(request, response)
        await bus_events.emit_response(self.bus, response)
        return response

    async def _dispatch(self, request: Request) -> Response:
        if not request.normalized.strip():
            return Response(text="I did not catch that.",
                            source=request.source)

        # An answer to something already asked, before anything else can read
        # the words as a new command.
        if self.conversation.has_choices() and self._maybe_answer(request):
            return await self._answer_choice(request)

        # A request for more than one thing becomes a plan, but only once the
        # plan has been seen to be several steps rather than one clause that
        # happened to contain the word "and".
        if _wants_several_things(request.normalized):
            return await self._run_plan(request)

        route = await self.router.choose(request)

        if route.kind == "skill":
            return await self._run_skill(route.name, request)

        if route.kind == "ai":
            return await self._ask_ai(request)

        if route.kind == "choice":
            # The router saw words that pick from a waiting list but _maybe_answer
            # did not, which happens when they name nothing on it. Say so, and
            # drop the list, rather than falling through to a generic refusal
            # and leaving it there for the next command to trip over.
            return await self._answer_choice(request)

        if route.kind == "knowledge":
            return await self._ask_knowledge(request)

        return Response(
            text="I do not know how to do that yet.",
            status=Status.FAILED,
            source=request.source,
        )

    # ------------------------------------------------------------------
    async def _run_plan(self, request: Request) -> Response:
        """Plans a multi-step task and works through it."""
        await bus_events.emit_plan_started(self.bus, request.normalized)

        try:
            plan = await self.planner.from_model(request, self.provider)
        except Exception as error:
            _log.error("could not build a plan: %s", error)
            return await self._ask_knowledge(request)

        if not plan.steps:
            return await self._dispatch_single(request)

        async def announce(step, index):
            await bus_events.emit_plan_step(
                self.bus, index + 1, len(plan), step.tool, step.text
            )

        results = await self.planner.run(plan, request, emit=announce)

        await bus_events.emit_plan_finished(
            self.bus, plan.goal, len(plan), len(results)
        )

        if not results:
            response = Response(
                text=plan.stopped_because or "I could not work out how to "
                                             "do all of that.",
                status=Status.FAILED,
                source=request.source,
            )
            response.metadata["plan"] = plan.as_dict()
            return response

        # The last step that said something is what the user hears. Steps that
        # asked for a choice are reported first, because that is what needs
        # answering.
        asking = next(
            (result for result in results if result.needs_input), None
        )
        chosen = asking or results[-1]

        response = Response(
            text=chosen.text,
            status=chosen.status,
            source=request.source,
            skill=chosen.skill,
            choices=chosen.choices,
            question=chosen.question,
            confirmation=chosen.confirmation,
            opened=[path for result in results for path in result.opened],
            sources=[source for result in results for source in result.sources],
            actions=[action for result in results for action in result.actions],
            error=chosen.error,
        )
        response.metadata["plan"] = plan.as_dict()
        if plan.stopped_because and asking is None:
            response.metadata["note"] = plan.stopped_because

        return response

    async def _run_plan_step(self, step, request: Request) -> Response:
        """Runs one step of a plan, through the same path as a typed command."""
        skill = self.registry.get(step.tool)
        if skill is None:
            return Response(
                text=f"I do not know how to {step.text or step.tool}.",
                status=Status.FAILED,
                source=request.source,
            )

        text = step.text or str(step.arguments.get("query") or "")
        # The step's own clause becomes the request, because a skill reads the
        # request text. Passing the whole sentence instead would have "open
        # downloads and open documents" looking for one folder named after the
        # entire sentence.
        return await self._run_skill(
            skill.name,
            request.with_text(text, {**step.arguments, "text": text}),
        )

    async def _dispatch_single(self, request: Request) -> Response:
        """Re-enters the normal route for a request that is only one thing."""
        if self.conversation.has_choices() and self._maybe_answer(request):
            return await self._answer_choice(request)
        route = await self.router.choose(request)
        if route.kind == "skill":
            return await self._run_skill(route.name, request)
        if route.kind == "ai":
            return await self._ask_ai(request)
        if route.kind == "choice":
            return await self._answer_choice(request)
        if route.kind == "knowledge":
            return await self._ask_knowledge(request)
        return Response(text="I do not know how to do that yet.",
                        status=Status.FAILED, source=request.source)

    # ------------------------------------------------------------------
    def _maybe_answer(self, request: Request) -> bool:
        text = request.normalized
        if text.isdigit():
            return True
        return self.conversation.resolve_choice(text) is not None

    async def _answer_choice(self, request: Request) -> Response:
        """Picks from the list that is waiting."""
        choice = self.conversation.resolve_choice(request.normalized)

        # Read before clearing. The action is what says whether the entries were
        # listed to be opened, read aloud or looked up, and taking the list first
        # would take that with it.
        action = self.conversation.state.pending_action
        topic = self.conversation.state.pending_topic
        count = len(self.conversation.state.pending_choices)
        self.conversation.take_choices()

        if choice is None:
            return Response(
                text=f"I have {count} results. Say a number from 1 to {count}.",
                status=Status.NEEDS_CLARIFICATION,
                source=request.source,
            )

        return await self._run_choice(choice, request, action, topic)

    async def _run_choice(self, choice: Choice, request: Request,
                           action: str = "open",
                           topic: str = "") -> Response:
        """Carries out whatever the chosen entry was listed for.

        ``action`` is passed in rather than read from the session, because the
        list has already been taken by the time this runs.
        """
        payload = choice.payload

        if not isinstance(payload, str):
            return Response(
                text=f"I do not know what to do with {choice.label}.",
                status=Status.FAILED,
                source=request.source,
            )

        # An article title is not a path, so this has to come before anything
        # that looks at the filesystem. Validating "Blue screen of death" as a
        # file would refuse every answer the lookup could have given.
        if action == "lookup":
            return await self._lookup_choice(choice, request, topic)

        # A file that has since been moved, or a path that is not somewhere
        # worth touching, must not be reported as opened.
        from jarvis2.safety import paths as path_safety

        verdict = path_safety.validate(payload)
        if not verdict.allowed:
            return Response(
                text=f"I cannot open that. {verdict.reason.capitalize()}.",
                status=Status.FAILED,
                source=request.source,
            )

        if not Path(payload).exists():
            # The filesystem decides, not the listing the user was shown.
            return Response(
                text=f"{choice.label} is no longer there.",
                status=Status.FAILED,
                source=request.source,
            )

        if action == "read":
            return await self._read_choice(choice, request)

        try:
            await self._run_blocking(self._open_path, payload)
        except OSError as error:
            return Response(
                text=f"I could not open {choice.label}.",
                status=Status.FAILED,
                source=request.source,
                error=str(error),
            )

        return Response(
            text=f"Opening {choice.label}.",
            source=request.source,
            opened=[payload],
            actions=[{"action": "open", "target": payload}],
        )

    async def _read_choice(self, choice: Choice,
                           request: Request) -> Response:
        """Reads a chosen document aloud, rather than opening a window."""
        from jarvis2.files import documents as doc

        body, truncated = await self._run_blocking(
            doc.prepare, choice.payload,
        )

        if not body:
            return Response(
                text=f"I could not find any text in {choice.label}.",
                status=Status.FAILED,
                source=request.source,
            )

        return Response(
            text=body + (" That is the opening part only." if truncated else ""),
            source=request.source,
            metadata={"label": choice.label, "path": choice.payload},
        )

    async def _lookup_choice(self, choice: Choice, request: Request,
                             topic: str = "") -> Response:
        """Reads a chosen article aloud, rather than opening it as a file.

        A list of articles and a list of files look the same, and the only thing
        that tells them apart is what the list was for. Treating a title as a
        path would send "1" looking for a file called "Blue screen of death".
        """
        skill = self.registry.get("knowledge")
        if skill is None:
            return Response(
                text="I cannot look that up.",
                status=Status.FAILED,
                source=request.source,
            )

        result = await skill.read_title(
            choice.payload,
            topic or choice.label,
            self.context,
        )
        return result.to_response(request)

    def _open_path(self, path: str) -> None:
        """Hands a path to the operating system."""
        import os

        os.startfile(path)

    def apply_mute(self, muted: bool) -> None:
        """Stops or resumes speaking replies on this computer."""
        self.muted = muted
        if self.speech is not None:
            self.speech.mute() if muted else self.speech.unmute()

    def speak(self, text: str) -> None:
        """Says something, when the assistant is not muted."""
        if self.speech is not None and not self.muted:
            self.speech.speak(text)


    # ------------------------------------------------------------------
    async def _run_skill(self, name: str, request: Request) -> Response:
        """Runs one registered skill."""
        skill = self.registry.get(name)
        if skill is None:
            return Response(text="I lost that one.", status=Status.FAILED,
                            source=request.source)

        await bus_events.emit_skill(self.bus, skill.name, 1.0)
        await bus_events.emit_tool_started(self.bus, skill.name,
                                           request.arguments)

        started = time.perf_counter()
        context = self.context

        try:
            result = await skill.execute(request, context)
        except Exception as error:
            _log.exception("skill %s failed", skill.name)
            await bus_events.emit_tool_failed(self.bus, skill.name, str(error))
            return Response(
                text=f"I could not do that: {type(error).__name__}.",
                status=Status.FAILED,
                source=request.source,
                skill=skill.name,
                error=str(error),
            )

        took = time.perf_counter() - started

        # A skill that says it needs the AI layer is passed on rather than
        # reported as a failure.
        if not result.succeeded and result.metadata.get("needs_ai"):
            return await self._ask_ai(request)

        if result.confirmation is not None:
            await bus_events.emit_confirmation_required(
                self.bus, result.confirmation
            )
        else:
            await bus_events.emit_tool_completed(
                self.bus, skill.name, result.to_response(request), took
            )

        response = result.to_response(request)
        response.skill = skill.name

        if result.choices:
            # The skill says what its entries are for, so "1" after a list of
            # articles reads an article and "1" after a list of files opens a
            # file. Guessing here is what would send "1" looking for a file
            # called "Mercury (planet)".
            self.conversation.remember_choices(
                result.choices, result.question, result.action, result.topic,
            )
            response.status = Status.NEEDS_CLARIFICATION

        if result.metadata.get("stop"):
            response.status = Status.STOP

        if result.metadata.get("needs_memory_change"):
            await self._apply_memory_change(result, request)

        return response

    async def _ask_ai(self, request: Request) -> Response:
        """Asks the model, falling back if it cannot be reached."""
        from jarvis2.ai.providers import build_provider
        from jarvis2.ai.response import ResponseBuilder, fallback_text

        provider = self.provider or build_provider(self.settings)
        if provider is None:
            # No model configured. This is not a failure: the deterministic
            # router has been the whole assistant until now.
            return await self._ask_knowledge(request)

        builder = ResponseBuilder(
            self.settings, self.registry, self.conversation,
            memory=self.memory, runner=self.run_tool,
        )

        # The provider travels on the request rather than being held here, so
        # the builder has no hidden state and a test cannot reach a real model by
        # building an assistant that happens to have one.
        with_provider = request.with_arguments(request.arguments)
        with_provider.metadata["provider"] = provider

        try:
            result = await builder.run(with_provider)
        except (ProviderUnavailable, ProviderError) as error:
            _log.warning("falling back to the V1 assistant: %s", error)
            response = await self._ask_knowledge(request)
            response.metadata["degraded"] = fallback_text(error)
            return response

        return result.to_response(request)

    async def run_tool(self, skill: Skill, request: Request) -> SkillResult:
        """Runs one skill on a model's behalf.

        This is the only path a model can reach an action through, and it is the
        same one a typed command uses, so the safety checks and any confirmation
        apply exactly as they would otherwise.
        """
        return await skill.execute(request, self.context)

    async def _ask_knowledge(self, request: Request) -> Response:
        """Looks an unrecognised request up on Wikipedia.

        This is the offline route a question takes when no model is configured,
        which is what keeps the assistant useful without one.
        """
        skill = self.registry.get("knowledge")
        if skill is None:
            return Response(
                text="I do not know how to do that yet.",
                status=Status.FAILED,
                source=request.source,
            )

        # The skill records the list itself, with the action that fits it, so
        # this does not have to remember the choices a second time and risk
        # remembering them without their meaning.
        return await self._run_skill("knowledge", request)

    # ------------------------------------------------------------------
    async def confirm(self, confirmation_id: str, approved: bool) -> Response:
        """Answers a confirmation."""
        if self.confirmations.is_pending(confirmation_id):
            def refuse() -> None:
                self.speak("Okay, I will not do that.")

            ran, result = await self.confirmations.resolve(
                confirmation_id, approved, reject=refuse,
            )
            await bus_events.emit_confirmation_resolved(
                self.bus, confirmation_id, approved
            )

            if not ran:
                return Response(text=str(result), source=Source.WEB)

            if hasattr(result, "as_dict"):
                return result
            return Response(text="Done.", source=Source.WEB)

        await bus_events.emit_confirmation_resolved(
            self.bus, confirmation_id, approved
        )
        return Response(
            text="There is nothing waiting for your answer.",
            status=Status.FAILED,
        )

    # ------------------------------------------------------------------
    async def _remember_turn(self, request: Request,
                             response: Response) -> None:
        """Records the exchange, so the next one can be understood in context."""
        if not request.normalized:
            return

        if response.opened:
            self.conversation.state.last_opened = list(response.opened)
        if response.sources:
            self.conversation.state.last_source = response.sources[-1]

        self.conversation.record(
            request.normalized, response.text,
            skill=response.skill or "",
            opened=response.opened,
            sources=response.sources,
        )

    async def _apply_memory_change(self, result: SkillResult,
                                   request: Request) -> None:
        """Carries out a change the conversation skill asked for."""
        for action in result.actions:
            kind = action.get("action")
            if kind == "disable_memory" and self.settings is not None:
                self.settings = self.settings.with_overrides(
                    memory_enabled=False
                )
            elif kind == "clear_memory" and self.memory is not None:
                await self._run_blocking(self.memory.clear)
            elif kind == "clear" and self.conversation is not None:
                self.conversation.clear()
        if self.conversation.has_choices():
            pass

    # ------------------------------------------------------------------
    def status(self) -> dict:
        """What the dashboard shows about the assistant's own state."""
        return {
            "name": self.settings.assistant_name if self.settings else "Jarvis",
            "ready": True,
            "skills": len(self.registry),
            "skillNames": self.registry.names,
            "aiProvider": getattr(self.provider, "name", None) or "none",
            "aiConfigured": bool(self.provider is not None),
            "voiceEnabled": self.settings.voice_enabled if self.settings else False,
            "memoryEnabled": bool(self.memory),
            "memory": self.memory.describe() if self.memory else None,
            "conversation": self.conversation.snapshot(),
            "confirmations": {
                "pending": (
                    self.confirmations.pending.as_dict()
                    if self.confirmations.pending else None
                ),
            },
            "settings": self.settings.public_summary if self.settings else {},
            "recent": self.bus.recent(12),
        }

    async def close(self) -> None:
        """Nothing to shut down. Every resource this assistant uses is either
        shared, a daemon thread, or closed when its owner is."""


async def build(settings=None, speech=None) -> JarvisAssistant:
    """Builds an assistant with everything wired up, or as much as exists.

    Returns an assistant even when nothing optional is available. That is
    deliberate: a machine with no AI key, no microphone and no Flask still has a
    working assistant, and starting should not be the thing that fails.
    """
    from jarvis2.ai.providers import build_provider
    from jarvis2.knowledge.wiki import Wikipedia

    settings = settings or _default_settings()
    configure(settings.log_level, settings.log_file or None)

    provider = build_provider(settings)

    if speech is None and settings.voice_enabled:
        from jarvis2.voice.output import SpeechOutput

        speech = SpeechOutput(settings)

    assistant = JarvisAssistant(
        settings=settings, provider=provider, speech=speech,
        wikipedia=Wikipedia(timeout=settings.lookup_timeout),
    )
    assistant.attach_tool_runner(assistant.run_tool)
    return assistant


def _default_settings():
    from jarvis2.config.settings import load_settings

    return load_settings()

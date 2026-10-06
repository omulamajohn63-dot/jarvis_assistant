"""The event bus.

Everything interesting that happens is published here, and the things that want
to know subscribe. A log file, a dashboard and a future integration all watch
the same stream without any of them being wired into the assistant.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from jarvis2.core.models import Confirmation, Request, Response
from jarvis2.logging_utils import get_logger

_log = get_logger("events")


class EventType(StrEnum):
    """What can happen. Kept small on purpose: each one earns its place."""

    USER_INPUT = "user_input"
    ASSISTANT_RESPONSE = "assistant_response"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_RESOLVED = "confirmation_resolved"
    SKILL_SELECTED = "skill_selected"
    PLAN_STARTED = "plan_started"
    PLAN_STEP = "plan_step"
    PLAN_FINISHED = "plan_finished"
    VOICE_STARTED = "voice_started"
    VOICE_STOPPED = "voice_stopped"
    WAKE_WORD = "wake_word"
    MEMORY_SAVED = "memory_saved"
    ERROR = "error"


@dataclass
class Event:
    name: str
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        from jarvis2.logging_utils import redact_deep

        # Deep, because an event carries lists and dicts and a page reads them
        # rather than printing them.
        return {"event": self.name, **redact_deep(self.data)}


@dataclass
class Subscription:
    """One subscriber, which may be synchronous or a coroutine."""

    callback: Callable
    name: str = ""
    queue: deque | None = None

    def matches(self, name: str) -> bool:
        # A name of "*" sees everything, which is how a log or a dashboard is
        # written without having to be updated for each new event.
        return self.name in ("*", name)


def _enqueue(event: Event) -> None:
    """A callback that does nothing, for a subscription that only wants a queue."""
    return None


class EventBus:
    """Delivers events to whoever is listening.

    A subscriber that is a coroutine is scheduled rather than awaited, so a slow
    listener cannot hold up the command the user is waiting for. A subscriber
    given a queue gets events in order instead, which is what the dashboard
    uses to show activity in the order it happened.
    """

    def __init__(self, history: int = 200):
        self._subscriptions: list = []
        self._history: deque = deque(maxlen=history)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    def subscribe(
        self,
        name: str,
        callback: Callable | None = None,
        queue: bool = False,
    ) -> Subscription | Callable:
        """Listens for one event name, or for "*" to hear everything.

        With no callback this returns a decorator, so it reads either way::

            bus.subscribe("tool_failed", on_failure)

            @bus.subscribe("*")
            def watch(event): ...

        ``queue=True`` with no callback returns a Subscription straight away,
        because there is no function to wrap.
        """
        if callback is None:
            if queue:
                return self._subscribe(name, _enqueue, queue=True)

            def decorator(function):
                self._subscribe(name, function, queue=False)
                return function
            return decorator

        return self._subscribe(name, callback, queue=queue)

    def _subscribe(self, name: str, callback: Callable, queue: bool) -> Subscription:
        subscription = Subscription(
            callback=callback,
            name=name,
            queue=deque(maxlen=500) if queue else None,
        )
        self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    # ------------------------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Remembers the running loop, so events can be delivered into it."""
        self._loop = loop or _running_loop()

    async def publish(self, name: str, **data: Any) -> Event:
        """Delivers an event to every listener that wants it."""
        event = Event(name=name, data=data)
        self._history.append(event)

        for subscription in list(self._subscriptions):
            if not subscription.matches(name):
                continue
            try:
                if subscription.queue is not None:
                    subscription.queue.append(event)
                    continue
                result = subscription.callback(event)
                if inspect.isawaitable(result):
                    self._schedule(result)
            except Exception as error:
                # A listener that fails must not take the command down with it.
                _log.error(
                    "subscriber failed for %s", name,
                    exc_info=True, extra={"error": str(error)},
                )
        return event

    def publish_nowait(self, name: str, **data: Any) -> None:
        """Publishes without waiting, for callers that are not in a coroutine."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.publish_sync(name, **data)
            return
        asyncio.create_task(self.publish(name, **data))

    def publish_sync(self, name: str, **data: Any) -> Event:
        """Delivers only to queue subscribers, without needing a loop."""
        event = Event(name=name, data=data)
        self._history.append(event)
        for subscription in list(self._subscriptions):
            if subscription.queue is not None and subscription.matches(name):
                subscription.queue.append(event)
        return event

    def _schedule(self, awaitable) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            # Nobody is listening to a loop, so there is nowhere to send a
            # coroutine. The work is dropped rather than run unreliably.
            asyncio.run(_swallow(awaitable))
            return
        loop.create_task(awaitable)

    # ------------------------------------------------------------------
    @property
    def history(self) -> list:
        return list(self._history)

    def recent(self, limit: int = 20) -> list:
        return [event.as_dict() for event in list(self._history)[-limit:]]

    def drain(self, subscription: Subscription) -> list:
        """Takes everything queued for one subscriber, oldest first."""
        if subscription.queue is None:
            return []
        events = list(subscription.queue)
        subscription.queue.clear()
        return [event.as_dict() for event in events]


async def _swallow(awaitable) -> None:
    try:
        await awaitable
    except Exception:
        _log.debug("scheduled listener failed", exc_info=True)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The loop this code is running in, or None if there is not one.

    None is a normal answer: the assistant is also used from a plain script and
    from tests, where there is nothing to schedule onto.
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


# ----------------------------------------------------------------------
# The assistant publishes its own steps through these, so every call site
# names an event rather than a string.
# ----------------------------------------------------------------------

async def emit_request(bus: EventBus, request: Request) -> None:
    await bus.publish(
        EventType.USER_INPUT.value,
        text=request.text,
        source=request.source.value,
    )


async def emit_skill(bus: EventBus, skill: str, score: float) -> None:
    await bus.publish(EventType.SKILL_SELECTED.value, skill=skill, score=score)


async def emit_tool_started(bus: EventBus, tool: str, arguments: dict) -> None:
    await bus.publish(EventType.TOOL_STARTED.value, tool=tool, arguments=arguments)


async def emit_tool_completed(bus: EventBus, tool: str, result: Response,
                              took: float) -> None:
    await bus.publish(
        EventType.TOOL_COMPLETED.value,
        tool=tool,
        succeeded=result.ok,
        text=result.text,
        opened=result.opened,
        took=took,
    )


async def emit_tool_failed(bus: EventBus, tool: str, error: str) -> None:
    await bus.publish(EventType.TOOL_FAILED.value, tool=tool, error=error)


async def emit_confirmation_required(bus: EventBus,
                                     confirmation: Confirmation) -> None:
    await bus.publish(
        EventType.CONFIRMATION_REQUIRED.value,
        **confirmation.as_dict(),
    )


async def emit_confirmation_resolved(bus: EventBus, confirmation_id: str,
                                     approved: bool) -> None:
    await bus.publish(
        EventType.CONFIRMATION_RESOLVED.value,
        id=confirmation_id,
        approved=approved,
    )


async def emit_response(bus: EventBus, response: Response) -> None:
    await bus.publish(
        EventType.ASSISTANT_RESPONSE.value,
        text=response.text,
        status=response.status.value,
        skill=response.skill,
        took=response.took,
    )


async def emit_error(bus: EventBus, where: str, error: str) -> None:
    await bus.publish(EventType.ERROR.value, where=where, error=error)


async def emit_plan_started(bus: EventBus, goal: str) -> None:
    await bus.publish(EventType.PLAN_STARTED.value, goal=goal)


async def emit_plan_step(bus: EventBus, step: int, of: int, tool: str,
                         text: str) -> None:
    await bus.publish(
        EventType.PLAN_STEP.value, step=step, of=of, tool=tool, text=text
    )


async def emit_plan_finished(bus: EventBus, goal: str, steps: int,
                             done: int) -> None:
    await bus.publish(
        EventType.PLAN_FINISHED.value, goal=goal, steps=steps, done=done
    )


def event_names() -> Iterable[str]:
    return (member.value for member in EventType)

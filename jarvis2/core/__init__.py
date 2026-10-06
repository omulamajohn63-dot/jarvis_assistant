"""The core of Jarvis V2.

The assistant is imported lazily. A skill needs `core.models`, and importing
that pulls in this package; if this package then imported the assistant, and the
assistant imported the skills, the three would deadlock on each other's import.

Lazy access keeps the shapes importable from anywhere without that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jarvis2.core.conversation import Conversation, SessionState
from jarvis2.core.events import EventBus, EventType
from jarvis2.core.memory import LongTermMemory, MemoryStore, Preferences
from jarvis2.core.models import (
    Choice,
    Confirmation,
    Request,
    Response,
    SkillResult,
    Source,
    Status,
    Turn,
)
from jarvis2.core.router import Route, Router

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from jarvis2.core.assistant import JarvisAssistant, build

# Imported on first use rather than at import time. See the note above.
_LAZY = {
    "JarvisAssistant": "jarvis2.core.assistant",
    "build": "jarvis2.core.assistant",
    "Runtime": "jarvis2.core.runtime",
    "SyncFallback": "jarvis2.core.runtime",
    "run_in": "jarvis2.core.runtime",
}

__all__ = [
    "Choice",
    "Confirmation",
    "Conversation",
    "EventBus",
    "EventType",
    "JarvisAssistant",
    "LongTermMemory",
    "MemoryStore",
    "Preferences",
    "Request",
    "Response",
    "Route",
    "Router",
    "Runtime",
    "SessionState",
    "SkillResult",
    "Source",
    "Status",
    "SyncFallback",
    "Turn",
    "build",
    "run_in",
]


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    return getattr(importlib.import_module(module), name)


def __dir__() -> list:
    return sorted(__all__)

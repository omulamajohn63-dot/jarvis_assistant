"""The shapes that pass through the assistant.

Every layer speaks these and nothing else, so a skill never has to know whether
it was reached from a terminal, a browser or the microphone, and an interface
never has to know which skill ran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Source(StrEnum):
    """Where a request came from. Affects how the reply is delivered."""

    TERMINAL = "terminal"
    WEB = "web"
    VOICE = "voice"
    AUTOMATION = "automation"
    API = "api"


class Status(StrEnum):
    """How a request ended. A reply always says which of these it was."""

    OK = "ok"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NEEDS_CLARIFICATION = "needs_clarification"
    CANCELLED = "cancelled"
    STOP = "stop"


@dataclass(frozen=True)
class Request:
    """Something the user asked for, before anything has happened to it."""

    text: str
    source: Source = Source.TERMINAL
    # Set when this request is the answer to something the assistant asked.
    resolves: str | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.text, str):
            object.__setattr__(self, "text", str(self.text))

    @property
    def normalized(self) -> str:
        """The text in the form the helpers expect: lowercased and tidied."""
        return " ".join(self.text.lower().split())

    @property
    def words(self) -> set:
        return set(self.normalized.split())

    def with_arguments(self, arguments: dict) -> Request:
        """The same request with arguments a model supplied.

        Kept separate from the text so a skill can see what it was actually
        asked to do, rather than having to parse it back out of a sentence.
        """
        return Request(
            text=self.text,
            source=self.source,
            resolves=self.resolves,
            metadata={**self.metadata, "arguments": dict(arguments)},
        )

    def with_text(self, text: str, arguments: dict | None = None) -> Request:
        """The same request, but for one part of it.

        A plan step runs against its own clause. Leaving the whole sentence in
        place would have "open downloads and open documents" look for a folder
        with the whole sentence as its name.
        """
        return Request(
            text=text,
            source=self.source,
            resolves=self.resolves,
            metadata={**self.metadata,
                      **({"arguments": dict(arguments)} if arguments else {})},
        )

    @property
    def arguments(self) -> dict:
        """Arguments a model supplied, or an empty dict."""
        value = self.metadata.get("arguments")
        return dict(value) if isinstance(value, dict) else {}


@dataclass
class Confirmation:
    """A question the assistant must be answered before it does anything.

    The id is what ties an answer to the question that was asked. Without it, a
    dialog left open in a browser could approve whatever happens to be waiting.
    """

    id: str
    action: str
    risk: str
    prompt: str
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "risk": self.risk,
            "prompt": self.prompt,
            "details": dict(self.details),
        }


@dataclass
class Choice:
    """One numbered option in a list the user has to pick from."""

    number: int
    label: str
    detail: str = ""
    payload: Any = None

    def as_dict(self) -> dict:
        return {
            "n": self.number,
            "label": self.label,
            "detail": self.detail,
            "payload": self.payload,
        }


@dataclass
class Response:
    """Everything that comes back from handling one request."""

    text: str = ""
    status: Status = Status.OK
    source: Source = Source.TERMINAL
    skill: str | None = None
    # A numbered list to show, when the assistant needs the user to choose.
    choices: list = field(default_factory=list)
    # The question asking for the list, so an interface can put it in context.
    question: str = ""
    confirmation: Confirmation | None = None
    # Files, folders and applications that were really opened.
    opened: list = field(default_factory=list)
    # Sources for the answer, so current information can be told from general
    # knowledge.
    sources: list = field(default_factory=list)
    # What was actually done, for the activity panel. Never a guess.
    actions: list = field(default_factory=list)
    # Free-form extra for an interface, such as an article to display.
    metadata: dict = field(default_factory=dict)
    took: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {Status.OK, Status.STOP}

    @property
    def needs_input(self) -> bool:
        return self.status in {
            Status.NEEDS_CONFIRMATION,
            Status.NEEDS_CLARIFICATION,
        }

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "status": self.status.value,
            "source": self.source.value,
            "skill": self.skill,
            "choices": [choice.as_dict() for choice in self.choices],
            "question": self.question,
            "confirmation": (
                self.confirmation.as_dict() if self.confirmation else None
            ),
            "opened": list(self.opened),
            "sources": list(self.sources),
            "actions": list(self.actions),
            "metadata": dict(self.metadata),
            "took": round(self.took, 4),
            "error": self.error,
        }


@dataclass
class SkillResult:
    """What a skill gives back.

    ``succeeded`` is set by the skill itself from what really happened. Nothing
    downstream is allowed to infer success from the fact that a skill ran, which
    is what keeps the assistant from claiming it opened something it did not.
    """

    succeeded: bool
    text: str = ""
    data: dict = field(default_factory=dict)
    choices: list = field(default_factory=list)
    question: str = ""
    # What picking an entry from ``choices`` should do: "open", "read" or
    # "lookup". The skill declares it, because only the skill knows whether its
    # entries are paths or article titles.
    action: str = "open"
    # What the list was about, kept so the answer still knows the question that
    # produced it after the list is gone.
    topic: str = ""
    confirmation: Confirmation | None = None
    opened: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: str | None = None

    def to_response(
        self,
        request: Request | None = None,
        status: Status | None = None,
    ) -> Response:
        """Turns a skill's answer into the reply the caller sees."""
        if status is None:
            if self.confirmation is not None:
                status = Status.NEEDS_CONFIRMATION
            elif self.choices:
                status = Status.NEEDS_CLARIFICATION
            elif not self.succeeded:
                status = Status.FAILED
            else:
                status = Status.OK

        return Response(
            text=self.text,
            status=status,
            source=request.source if request else Source.TERMINAL,
            choices=list(self.choices),
            question=self.question,
            confirmation=self.confirmation,
            opened=list(self.opened),
            sources=list(self.sources),
            actions=list(self.actions),
            metadata=dict(self.data) | self.metadata,
            error=self.error,
        )


@dataclass
class Turn:
    """One exchange, kept so the next request can be understood in context."""

    request: str
    reply: str
    at: float = field(default_factory=time.time)
    skill: str | None = None
    # What was really opened, so "what was the file I just opened?" has an
    # answer that is checked against the filesystem rather than remembered.
    opened: list = field(default_factory=list)
    sources: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "request": self.request,
            "reply": self.reply,
            "at": self.at,
            "skill": self.skill,
            "opened": list(self.opened),
            "sources": list(self.sources),
        }

"""A provider that answers from a script.

Tests must never depend on a real model, and developing against one is slow and
unreliable. This one is configured with a list of answers, or a callable, and can
record what it was asked so a test can assert on the prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jarvis2.ai.provider import AIResponse


@dataclass
class RecordedCall:
    """What the provider was asked, so a test can check the prompt."""

    messages: list
    tools: list | None
    temperature: float


class MockAIProvider:
    """Answers with whatever it was told to.

    ``responses`` is either a list used in order, a callable taking the messages,
    or a single string. ``tool_calls`` are returned instead of text when given.
    """

    name = "mock"

    def __init__(
        self,
        responses: list | str | Callable = "",
        tool_calls: list | None = None,
        fail_with: Exception | None = None,
        tool_rounds: int | None = None,
    ):
        self.responses = responses
        self.tool_calls = tool_calls
        self.fail_with = fail_with
        #: How many rounds ask for a tool before answering in plain text. None
        #: means every round, which is how a test can check that a model is not
        #: left looping.
        self.tool_rounds = tool_rounds
        self.calls: list = []
        self._index = 0

    async def available(self) -> bool:
        return self.fail_with is None

    async def generate(self, messages: list, tools: list | None = None,
                       temperature: float = 0.2) -> AIResponse:
        self.calls.append(
            RecordedCall(messages=list(messages), tools=tools,
                         temperature=temperature)
        )

        if self.fail_with is not None:
            raise self.fail_with

        round_number = self._index
        text = self._next_text(messages)
        self._index += 1

        calls: list = []
        if self.tool_calls:
            within_limit = (
                self.tool_rounds is None or round_number < self.tool_rounds
            )
            if within_limit:
                calls = list(self.tool_calls)

        return AIResponse(
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            provider=self.name,
            model="mock",
        )

    def _next_text(self, messages: list) -> str:
        if callable(self.responses):
            return str(self.responses(messages) or "")

        if isinstance(self.responses, str):
            return self.responses

        if not self.responses:
            return ""

        if self._index < len(self.responses):
            answer = self.responses[self._index]
            self._index += 1
            return str(answer)

        # The last answer repeats, so a test that asks one more question than it
        # prepared does not get nothing.
        return str(self.responses[-1])

    # ------------------------------------------------------------------
    @property
    def last_messages(self) -> list:
        return self.calls[-1].messages if self.calls else []

    @property
    def last_tools(self) -> list | None:
        return self.calls[-1].tools if self.calls else None

    def reset(self) -> None:
        self.calls.clear()
        self._index = 0


def scripted(*pairs) -> MockAIProvider:
    """A provider that answers each expected phrase with a fixed reply.

    The simplest way to write a test about how a reply is phrased.
    """
    lookup = {phrase.lower(): reply for phrase, reply in pairs}

    def answer(messages: list) -> str:
        question = messages[-1].get("content", "") if messages else ""
        return lookup.get(str(question).strip().lower(), "")

    return MockAIProvider(responses=answer)


def failing(error: Exception | None = None) -> MockAIProvider:
    """A provider that is never reachable, for testing the degraded path."""
    from jarvis2.ai.provider import ProviderUnavailable

    return MockAIProvider(fail_with=error or ProviderUnavailable("no key set"))

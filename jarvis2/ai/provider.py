"""The seam between Jarvis and whichever model answers for it.

Every provider implements this. The rest of the assistant does not know or care
which one is in use, so swapping vendors is a configuration change rather than a
rewrite, and a test can use a provider that answers from a script.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    """A request from the model to use one skill.

    Treated as untrusted from the moment it arrives: the name is looked up in
    the registry and the arguments are validated before anything runs.
    """

    name: str
    arguments: dict = field(default_factory=dict)
    id: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "arguments": dict(self.arguments), "id": self.id}

    def __repr__(self) -> str:
        return f"<ToolCall {self.name} {sorted(self.arguments)}>"


@dataclass
class AIResponse:
    """What came back from a provider."""

    text: str = ""
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"
    provider: str = ""
    model: str = ""

    @property
    def wants_a_tool(self) -> bool:
        return bool(self.tool_calls)

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "tool_calls": [call.as_dict() for call in self.tool_calls],
            "finishReason": self.finish_reason,
            "provider": self.provider,
            "model": self.model,
        }


class ProviderUnavailable(Exception):
    """Raised when a provider cannot be reached or is not configured.

    The assistant catches this and carries on with the deterministic router, so
    losing the internet loses the chatty part and nothing else.
    """


class ProviderError(Exception):
    """Raised when a provider answered with something unusable."""


@runtime_checkable
class AIProvider(Protocol):
    """What the assistant needs from a model."""

    name: str

    async def available(self) -> bool:
        """True when this provider is configured well enough to try."""
        ...

    async def generate(
        self,
        messages: list,
        tools: list | None = None,
        temperature: float = 0.2,
    ) -> AIResponse:
        """Answers a conversation, optionally choosing tools to use."""
        ...


def message(role: str, content: str, name: str = "") -> dict:
    """One message, in the shape every provider accepts here."""
    entry = {"role": role, "content": content}
    if name:
        entry["name"] = name
    return entry


def user(text: str) -> dict:
    return message("user", text)


def assistant(text: str) -> dict:
    return message("assistant", text)


def system(text: str) -> dict:
    return message("system", text)


def user_with_tools(text: str, tools: list) -> dict:
    """A user turn that carries tool results, in the usual shape."""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            *tools,
        ],
    }


def parse_json(text: str) -> dict | None:
    """Reads a JSON object out of a model's reply.

    Models wrap JSON in prose and in code fences even when told not to, so this
    looks for the outermost braces rather than trusting the whole reply to be
    nothing but JSON. Anything unparseable returns None instead of raising, so a
    chatty model cannot break the caller.
    """
    if not text:
        return None

    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]

    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:index + 1])
                        return value if isinstance(value, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def coerce_arguments(raw: Any) -> dict:
    """Turns whatever a provider returned for arguments into a dict."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        parsed = parse_json(raw)
        return parsed if parsed is not None else {}
    return {}

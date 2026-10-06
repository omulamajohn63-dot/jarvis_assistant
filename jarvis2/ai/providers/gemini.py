"""Google Gemini.

Gemini's request and reply shapes are its own, so this translates rather than
sharing the OpenAI implementation. What comes out is the same AIResponse, so
nothing above this file has to know which provider it was talking to.

The key goes in the ``x-goog-api-key`` header rather than the query string,
because a URL is far more likely to end up in a log than a header is.
"""

from __future__ import annotations

from typing import Any

from jarvis2.ai.provider import (
    AIResponse,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    coerce_arguments,
)
from jarvis2.logging_utils import get_logger, redact

_log = get_logger("ai.gemini")

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODEL = "gemini-2.0-flash"

# Gemini names the roles differently and puts the system prompt outside the
# conversation entirely.
ROLE_MAP = {
    "system": "user",
    "user": "user",
    "assistant": "model",
    "tool": "user",
}


class GeminiProvider:
    """Talks to Google's generateContent endpoint."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        session: Any = None,
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session

    async def available(self) -> bool:
        return bool(self.api_key and self.model)

    # ------------------------------------------------------------------
    def _split(self, messages: list) -> tuple:
        """Separates the system instruction from the conversation.

        Gemini takes the instruction as its own field, and it must come first,
        so it is pulled out here rather than left in the list where a role
        translation would put it in the wrong place.
        """
        system_parts = [
            str(entry.get("content") or "")
            for entry in messages
            if entry.get("role") == "system"
        ]
        contents = [
            {
                "role": ROLE_MAP.get(entry.get("role", "user"), "user"),
                "parts": [{"text": str(entry.get("content") or "")}],
            }
            for entry in messages
            if entry.get("role") != "system"
        ]
        return "\n\n".join(part for part in system_parts if part), contents

    def _payload(self, messages: list, tools: list | None,
                 temperature: float) -> dict:
        instruction, contents = self._split(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 800,
            },
        }
        if instruction:
            payload["systemInstruction"] = {"parts": [{"text": instruction}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": _declarations(tools)}]
        return payload

    def _post(self, payload: dict) -> dict:
        import requests

        url = f"{self.base_url}/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            # As a header, so it does not turn up in a logged request line.
            "x-goog-api-key": self.api_key,
        }
        poster = self.session.post if self.session else requests.post

        try:
            response = poster(url, json=payload, headers=headers,
                              timeout=self.timeout)
        except Exception as error:
            raise ProviderUnavailable(
                f"could not reach Google: {redact(error)}"
            ) from error

        status = getattr(response, "status_code", 200)
        if status in (401, 403):
            raise ProviderError("the Google API key was rejected")
        if status == 429:
            raise ProviderUnavailable("Google is rate limiting")
        if status == 404:
            raise ProviderError(f"the model {self.model!r} does not exist")
        if status >= 400:
            raise ProviderError(f"Google answered {status}")

        try:
            return response.json()
        except ValueError as error:
            raise ProviderError("Google's reply was not JSON") from error

    # ------------------------------------------------------------------
    async def generate(self, messages: list, tools: list | None = None,
                       temperature: float = 0.2) -> AIResponse:
        import asyncio

        if not await self.available():
            raise ProviderUnavailable("no Google API key configured")

        payload = self._payload(messages, tools, temperature)
        data = await asyncio.to_thread(self._post, payload)
        return self.parse(data)

    def parse(self, data: dict) -> AIResponse:
        """Turns a generateContent reply into an AIResponse."""
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                raise ProviderError(
                    f"the request was refused: {feedback['blockReason']}"
                )
            raise ProviderError("Google returned no candidates")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        texts = [str(part.get("text") or "") for part in parts
                 if part.get("text")]
        calls = [
            ToolCall(
                name=(part.get("functionCall") or {}).get("name", ""),
                arguments=coerce_arguments(
                    (part.get("functionCall") or {}).get("args")
                ),
            )
            for part in parts
            if part.get("functionCall")
        ]

        finish = candidates[0].get("finishReason") or (
            "tool_calls" if calls else "stop"
        )

        return AIResponse(
            text="\n".join(texts).strip(),
            tool_calls=calls,
            finish_reason=finish,
            provider=self.name,
            model=self.model,
        )


def _declarations(tools: list) -> list:
    """Converts tool schemas into Gemini's functionDeclarations shape.

    Gemini takes a flat list of declarations, where OpenAI nests them under a
    "function" key. The names are lowerCased by Google, which is worth knowing
    about when reading a reply back.
    """
    declarations = []
    for tool in tools:
        function = tool.get("function", tool)
        declarations.append({
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "parameters": _clean_schema(function.get("parameters") or {}),
        })
    return declarations


# Gemini rejects several of the JSON schema keywords OpenAI accepts, so they are
# dropped rather than passed through to produce a confusing error.
UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "additionalProperties", "$schema", "exclusiveMinimum", "exclusiveMaximum",
    "$ref", "definitions", "default", "examples",
})


def _clean_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {
            key: _clean_schema(value)
            for key, value in schema.items()
            if key not in UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(schema, list):
        return [_clean_schema(entry) for entry in schema]
    return schema

"""Any service that speaks the OpenAI chat completions API.

That is OpenAI itself, and also Ollama, LM Studio, vLLM and the hosted open
weights services, because they all took the same shape. One implementation covers
them; only the base URL changes.

The `openai` package is deliberately not used. The wire format is small and
stable, `requests` is already a dependency of the project, and the SDK would add
an installation and a version to keep in step for a few hundred lines of HTTP.
"""

from __future__ import annotations

import json
from typing import Any

from jarvis2.ai.provider import (
    AIResponse,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    coerce_arguments,
)
from jarvis2.logging_utils import get_logger, redact

_log = get_logger("ai.openai")

# How long to wait before giving up on the provider. Short on purpose: the
# assistant is more useful answering slowly than not answering at all.
DEFAULT_TIMEOUT = 30.0


class OpenAICompatibleProvider:
    """Talks to a chat completions endpoint."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = DEFAULT_TIMEOUT,
        session: Any = None,
        # Set for services that do not want the Authorization header, which
        # includes some local servers.
        send_auth_header: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session
        self.send_auth_header = send_auth_header

    async def available(self) -> bool:
        return bool(self.api_key and self.model)

    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.send_auth_header and self.api_key:
            # Redacted in any log of this header.
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, messages: list, tools: list | None,
                 temperature: float) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _post(self, payload: dict) -> dict:
        import requests

        url = f"{self.base_url}/chat/completions"
        poster = self.session.post if self.session else requests.post

        try:
            response = poster(url, json=payload, headers=self._headers(),
                              timeout=self.timeout)
        except Exception as error:
            # A network problem, a bad host, a timeout: all of them mean the
            # same thing here, which is that this provider cannot be used.
            raise ProviderUnavailable(
                f"could not reach {self.base_url}: {redact(error)}"
            ) from error

        status = getattr(response, "status_code", 200)
        if status == 401 or status == 403:
            raise ProviderError("the API key was rejected")
        if status == 429:
            raise ProviderUnavailable("the provider is rate limiting")
        if status >= 400:
            raise ProviderError(f"the provider answered {status}")

        try:
            return response.json()
        except ValueError as error:
            raise ProviderError("the provider's reply was not JSON") from error

    # ------------------------------------------------------------------
    async def generate(self, messages: list, tools: list | None = None,
                       temperature: float = 0.2) -> AIResponse:
        import asyncio

        if not await self.available():
            raise ProviderUnavailable("no API key or model configured")

        payload = self._payload(messages, tools, temperature)
        data = await asyncio.to_thread(self._post, payload)
        return self.parse(data)

    def parse(self, data: dict) -> AIResponse:
        """Turns a chat completions reply into an AIResponse."""
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("the provider returned no choices")

        choice = choices[0]
        message = choice.get("message") or {}
        calls = []

        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            calls.append(ToolCall(
                name=function.get("name", ""),
                arguments=coerce_arguments(function.get("arguments")),
                id=raw.get("id", ""),
            ))

        return AIResponse(
            text=(message.get("content") or "").strip(),
            tool_calls=calls,
            finish_reason=(choice.get("finish_reason")
                           or ("tool_calls" if calls else "stop")),
            provider=self.name,
            model=data.get("model") or self.model,
        )


def build_from_settings(settings):
    """A provider built from configuration, or None when none is set up.

    ``AI_BASE_URL`` is what makes this one implementation cover a local model:
    point it at Ollama and the same code drives a model on this machine.

    None means "run without a model", which is a supported way to use Jarvis, so
    a provider is only returned when it would actually work. Building one that
    cannot authenticate would turn a clear "no key set" into a confusing 401.
    """
    from jarvis2.ai.providers.gemini import GeminiProvider

    provider = (settings.ai_provider or "").strip().lower()

    if provider in {"gemini", "google"}:
        # Gemini takes a Google key, not the OpenAI one, so the two are not
        # interchangeable here.
        if not (settings.google_api_key and settings.ai_model):
            return None
        return GeminiProvider(
            api_key=settings.google_api_key,
            model=settings.ai_model,
            timeout=settings.ai_timeout,
        )

    if provider in {"openai", "openai-compatible", "ollama", "llamacpp",
                    "lmstudio", "vllm", "local"}:
        local = ("localhost" in settings.ai_base_url
                 or "127.0.0.1" in settings.ai_base_url)
        # A local server usually has no key and may reject the header, so a key
        # is only required when there is somewhere for it to be sent.
        if not settings.ai_model:
            return None
        if not settings.ai_api_key and not local:
            return None

        return OpenAICompatibleProvider(
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            base_url=settings.ai_base_url,
            timeout=settings.ai_timeout,
            send_auth_header=not local,
        )

    return None


def describe(payload: dict) -> str:
    """A short, safe summary of a payload, for a log line."""
    model = payload.get("model", "?")
    count = len(payload.get("messages") or [])
    tools = len(payload.get("tools") or [])
    return json.dumps({"model": model, "messages": count, "tools": tools})

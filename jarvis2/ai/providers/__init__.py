"""The providers Jarvis can use."""

from jarvis2.ai.providers.gemini import GeminiProvider
from jarvis2.ai.providers.mock import MockAIProvider, failing, scripted
from jarvis2.ai.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "GeminiProvider",
    "MockAIProvider",
    "OpenAICompatibleProvider",
    "build_provider",
    "failing",
    "scripted",
]


def build_provider(settings, override=None):
    """Chooses a provider from configuration.

    ``override`` is for tests and for the dashboard's provider setting. Returns
    None when nothing is configured, which is the signal to run in offline mode
    rather than an error: everything V1 could do still works.
    """
    from jarvis2.ai.providers.openai_compatible import build_from_settings

    if override is not None:
        return override

    if not settings.ai_enabled:
        return None

    name = (settings.ai_provider or "").strip().lower()

    if name == "mock":
        return MockAIProvider(responses="")

    return build_from_settings(settings)

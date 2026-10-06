"""Speaking.

pyttsx3's SAPI5 backend on Windows only speaks the first utterance per engine:
every later ``say()`` returns at once with no audio. A fresh engine per call
avoids that, and stopping it releases the voice. That is the behaviour V1 has
and it is kept here rather than rediscovered.
"""

from __future__ import annotations

import asyncio
import threading

from jarvis2.logging_utils import get_logger

_log = get_logger("voice.output")

# SAPI5 reads and speaks from one thread at a time. Engines are built and torn
# down per utterance, so a lock keeps two of them from overlapping.
_engine_lock = threading.Lock()


class SpeechOutput:
    """Speaks replies out loud, and can be told to stop."""

    def __init__(self, settings, enabled: bool = None):
        self.settings = settings
        self.enabled = settings.voice_enabled if enabled is None else enabled
        self.volume = settings.voice_volume
        self.rate = settings.voice_rate
        self.voice_index = settings.voice_index
        self._stopped = False

    # ------------------------------------------------------------------
    def speak(self, text: str) -> bool:
        """Speaks one utterance. Returns whether anything was said.

        Silent and successful when muted, so a muted assistant does the same
        work as an unmuted one and only the sound is missing.
        """
        if not text or not self.enabled or self._stopped:
            return False

        return self._engine_say(text)

    def _engine_say(self, text: str) -> bool:
        try:
            from pyttsx3.engine import Engine
        except ImportError as error:
            _log.warning("text to speech is not installed: %s", error)
            return False

        with _engine_lock:
            engine = None
            try:
                engine = Engine()
                voices = engine.getProperty("voices")
                if voices and self.voice_index < len(voices):
                    engine.setProperty("voice", voices[self.voice_index].id)
                engine.setProperty("rate", self.rate)
                engine.setProperty("volume", self.volume)
                engine.say(text)
                engine.runAndWait()
                return True
            except Exception as error:
                # Speech is a nicety. Failing it must not fail the command.
                _log.warning("could not speak: %s", error)
                return False
            finally:
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        pass

    # ------------------------------------------------------------------
    async def say(self, text: str) -> bool:
        """Speaks without blocking the event loop.

        The engine is synchronous and can take as long as the sentence takes, so
        it runs in a worker thread rather than stopping everything else.
        """
        if not text or not self.enabled:
            return False
        return await asyncio.to_thread(self.speak, text)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Stops mid-sentence, for interrupting Jarvis."""
        self._stopped = True

    def resume(self) -> None:
        self._stopped = False

    def mute(self) -> None:
        self.enabled = False

    def unmute(self) -> None:
        self.enabled = True

    def set_volume(self, level: float) -> None:
        self.volume = max(0.0, min(1.0, float(level)))

    def set_rate(self, rate: int) -> None:
        self.rate = max(50, min(400, int(rate)))

    def voices(self) -> list:
        """The installed voices, for a settings page to choose from."""
        try:
            from pyttsx3.engine import Engine

            engine = Engine()
            try:
                return [
                    {"id": voice.id, "name": voice.name, "lang": voice.languages}
                    for voice in engine.getProperty("voices")
                ]
            finally:
                engine.stop()
        except Exception as error:
            _log.warning("could not list voices: %s", error)
            return []


class NullSpeech(SpeechOutput):
    """For the browser, where the page plays the audio itself.

    Speaking here as well would double every reply up.
    """

    def speak(self, text: str) -> bool:
        return False

    async def say(self, text: str) -> bool:
        return False

"""The wake word, if the machine can support one.

Deliberately optional. An always-listening microphone is a privacy cost and a
dependency, so it is off by default, and every failure to start it leaves push to
talk working rather than stopping the assistant. There is no fallback that
silently opens a microphone nobody asked for.
"""

from __future__ import annotations

import asyncio

from jarvis2.logging_utils import get_logger

_log = get_logger("voice.wakeword")

DEFAULT_WAKE_WORD = "jarvis"


class WakeWordListener:
    """Listens for a phrase and says when it heard it."""

    def __init__(self, settings, phrase: str = None):
        self.settings = settings
        self.phrase = (phrase or settings.wake_word or DEFAULT_WAKE_WORD).lower()
        self.enabled = settings.wake_word_enabled
        self._running = False
        self._recognizer = None

    # ------------------------------------------------------------------
    def available(self) -> bool:
        """True when a wake word could be run here.

        Checked rather than assumed, so the assistant can say plainly that it
        needs a microphone instead of failing on first use.
        """
        try:
            import speech_recognition as sr
        except ImportError:
            return False
        return hasattr(sr, "Microphone")

    def describe(self) -> dict:
        return {
            "enabled": self.enabled,
            "phrase": self.phrase,
            "available": self.available(),
        }

    # ------------------------------------------------------------------
    async def start(self, on_wake) -> None:
        """Waits for the phrase, then calls on_wake. Runs until stopped."""
        if not self.enabled:
            _log.info("wake word is switched off")
            return

        if not self.available():
            _log.warning(
                "the wake word needs a microphone; staying on push to talk"
            )
            return

        self._running = True
        _log.info("listening for %r", self.phrase)

        try:
            import speech_recognition as sr
        except ImportError:
            return

        recognizer = sr.Recognizer()
        self._recognizer = recognizer

        while self._running:
            result = await asyncio.to_thread(self._await_phrase, sr, recognizer)
            if not self._running:
                break
            if result is not None:
                _log.info("wake word heard")
                try:
                    await on_wake(result)
                except Exception as error:
                    _log.error("wake handler failed: %s", error)

    def _await_phrase(self, sr, recognizer):
        """Listens once and returns what was heard, or None.

        A long listen with a short silence threshold, so the assistant does not
        wake on a door closing. Timeouts and errors return quietly: this runs
        forever, and a microphone that unplugged should not end it.
        """
        try:
            with sr.Microphone() as source:
                recognizer.pause_threshold = 0.8
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=4)
                text = recognizer.recognize_google(audio, language="en-in")
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as error:
            _log.debug("wake word listen failed: %s", error)
            asyncio.run(asyncio.sleep(1))
            return None

        spoken = str(text).lower().strip()
        if self.phrase in spoken:
            return spoken
        return None

    def stop(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

"""Hearing.

Wraps speech_recognition so the rest of the assistant never imports it, and so a
machine with no microphone, no PyAudio or no network still starts. A failure
here is reported as a sentence, never as a traceback.
"""

from __future__ import annotations

import asyncio

from jarvis2.core.models import Source
from jarvis2.logging_utils import get_logger

_log = get_logger("voice.input")


class RecognitionResult:
    """What was heard, or why nothing was."""

    def __init__(self, text: str = "", reason: str = "", ok: bool = False):
        self.text = text
        self.reason = reason
        self.ok = ok or bool(text)

    def as_dict(self) -> dict:
        return {"text": self.text, "reason": self.reason, "ok": self.ok}


class VoiceInput:
    """Listens, and turns audio into text."""

    def __init__(self, settings, speech=None):
        self.settings = settings
        self.speech = speech

    # ------------------------------------------------------------------
    def _recognizer(self):
        try:
            import speech_recognition as sr

            return sr
        except ImportError as error:
            _log.warning("speech recognition is not installed: %s", error)
            return None

    def available(self) -> bool:
        """True when speech recognition can be used at all."""
        sr = self._recognizer()
        if sr is None:
            return False
        try:
            import speech_recognition  # noqa: F401

            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def transcribe_audio(self, frames: bytes, sample_rate: int = None,
                         sample_width: int = None) -> RecognitionResult:
        """Transcribes recorded audio that is already in memory.

        This is what the browser uses: the page records and posts raw PCM, so no
        microphone is ever opened on this side and no audio file is written.
        """
        sr = self._recognizer()
        if sr is None:
            return RecognitionResult(
                reason="Speech recognition is not installed on this computer."
            )

        rate = sample_rate or self.settings.sample_rate
        width = sample_width or self.settings.sample_width

        try:
            audio = sr.AudioData(frames, rate, width)
        except Exception as error:
            return RecognitionResult(reason=f"That recording was not usable: {error}")

        return self.transcribe(audio)

    def transcribe(self, audio) -> RecognitionResult:
        """Turns a captured recording into text."""
        sr = self._recognizer()
        if sr is None:
            return RecognitionResult(
                reason="Speech recognition is not installed on this computer."
            )

        import os

        recognizer = sr.Recognizer()
        try:
            text = recognizer.recognize_google(
                audio,
                language=self.settings.recognition_language,
                key=os.environ.get("GOOGLE_SPEECH_API_KEY")
                or self.settings.google_speech_api_key or None,
            )
            return RecognitionResult(text=str(text).lower().strip(), ok=True)
        except sr.UnknownValueError:
            # Silence, or noise that held no words. Nothing was misheard, so
            # there is nothing to correct.
            return RecognitionResult(reason="Sorry, I did not understand that.")
        except sr.RequestError as error:
            _log.warning("recognition service unavailable: %s", error)
            return RecognitionResult(
                reason="Speech recognition is unavailable. I can still take "
                       "typed commands."
            )
        except Exception as error:
            _log.warning("recognition failed: %s", error)
            return RecognitionResult(reason=f"Something went wrong hearing that: {error}")

    # ------------------------------------------------------------------
    async def listen(self) -> RecognitionResult:
        """Listens to the microphone once.

        Runs in a worker thread: opening the microphone and waiting for a voice
        are both blocking, and the assistant has to stay responsive while it
        does them.
        """
        return await asyncio.to_thread(self._listen_sync)

    def _listen_sync(self) -> RecognitionResult:
        sr = self._recognizer()
        if sr is None:
            return RecognitionResult(
                reason="Speech recognition is not installed on this computer."
            )

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = self.settings.ambience_timeout or 1

        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(
                    source, timeout=self.settings.listen_timeout
                )
        except sr.WaitTimeoutError:
            return RecognitionResult(reason="I did not hear anything.")
        except Exception as error:
            _log.warning("could not open the microphone: %s", error)
            return RecognitionResult(
                reason="I could not reach the microphone. Check that it is "
                       "plugged in and allowed."
            )

        return self.transcribe(audio)

    def source_for(self) -> Source:
        return Source.VOICE

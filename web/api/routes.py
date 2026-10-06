"""The endpoints the dashboard page calls.

One module, so every route is in one place and the page's expectations can be
checked against them. Nothing here holds state: the assistant's session is the
only state, and these handlers read from it and write to it through the core.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import uuid

from flask import Response, jsonify, request, send_from_directory

from jarvis2.core.models import Source, Status
from jarvis2.logging_utils import get_logger
from jarvis2.safety import policy

_log = get_logger("web.api")
# How much a recorded reply may be, and for how long. A forgotten microphone
# must not fill memory with silence.
MAX_AUDIO_BYTES = 4 * 1024 * 1024


def _call(awaitable, timeout=None):
    """Runs one coroutine on the assistant's own loop.

    Resolved when it is used rather than bound when the routes are registered,
    because ``web.app`` imports this module. Binding it here would make the
    helper invisible from outside, and a handler that has stopped answering is
    then the one thing that cannot be tested.
    """
    from web.app import call

    return call(awaitable, timeout)


def register(app) -> None:
    """Adds every route to an app.

    ``call`` rather than ``asyncio.run`` is used throughout, because a WSGI
    server can call a handler from inside a running event loop. That is not
    hypothetical: ``python -m jarvis2 --browser`` starts Flask from inside one.
    """
    from web.app import LOCAL_ADDRESSES, get_assistant

    # ------------------------------------------------------------------
    @app.before_request
    def _only_this_machine():
        """Refuses anything that did not come from this computer."""
        address = request.remote_addr or ""
        if address not in LOCAL_ADDRESSES:
            return ("This interface only answers this computer.", 403)

    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(app.template_folder, "index.html")

    # The template refers to its assets as siblings, which is what makes it
    # work when the folder is opened as a plain file. Served from here those
    # paths would be /styles.css and /app.js, so they are answered from the
    # static folder. Without this the page still loads, by way of its own
    # fallback, but only after two 404s.
    @app.get("/styles.css")
    def styles():
        return send_from_directory(app.static_folder, "styles.css")

    @app.get("/app.js")
    def script():
        return send_from_directory(app.static_folder, "app.js")

    @app.get("/api/status")
    def status():
        """What the assistant is and what it can do."""
        assistant = get_assistant()
        state = assistant.status()
        state["risk"] = policy.risk_counts()
        return jsonify(state)

    @app.get("/api/state")
    def state():
        """The smaller answer the page asks for as often as it likes."""
        assistant = get_assistant()
        settings = assistant.settings
        return jsonify({
            "name": settings.assistant_name,
            "muted": True,
            "inputMode": "web",
            "sampleRate": settings.sample_rate,
            "maxSeconds": settings.max_recording_seconds,
            "pending": (
                {"count": len(assistant.conversation.state.pending_choices)}
                if assistant.conversation.has_choices() else None
            ),
            "confirmation": (
                assistant.confirmations.pending.as_dict()
                if assistant.confirmations.pending else None
            ),
        })

    # ------------------------------------------------------------------
    @app.post("/api/chat")
    def chat():
        """Runs one typed command and returns the reply as data."""
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"error": "Say something first."}), 400

        assistant = get_assistant()

        # The assistant asks for its own name when renaming, rather than the
        # server blocking on a line of input that will never come.
        if _is_rename(text):
            return jsonify({"prompt": "What would you like to name me?"})

        # Bounded so a wedged handler comes back as a failure the page can show,
        # rather than leaving somebody looking at a spinner.
        try:
            response = _call(assistant.handle_input(text, Source.WEB))
        except Exception as error:
            _log.exception("chat failed")
            return jsonify({
                **empty_reply(),
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
                "text": "That took too long, so I gave up. Try again, or ask "
                        "for something simpler.",
            }), 504
        return jsonify(_reply(response))

    @app.post("/api/confirm")
    def confirm():
        """Answers a confirmation the assistant asked before doing anything.

        The id must be the one it asked with, so a card left over from an earlier
        question cannot approve whatever is waiting now.
        """
        payload = request.get_json(silent=True) or {}
        confirmation_id = payload.get("id")
        if confirmation_id is None:
            return jsonify({"error": "That confirmation is missing its id."}), 400

        assistant = get_assistant()
        approved = bool(payload.get("approved"))
        response = _call(assistant.confirm(confirmation_id, approved))
        return jsonify(_reply(response))

    @app.post("/api/name")
    def rename():
        """Stores a new name for the assistant."""
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name", "")).strip()
        if not name:
            return jsonify({"error": "Please give me a name."}), 400
        if len(name) > 40:
            return jsonify({"error": "That name is too long."}), 400

        assistant = get_assistant()
        assistant.settings = assistant.settings.with_overrides(assistant_name=name)

        text = f"Alright, I will be called {name} from now on."
        return jsonify({
            "text": text, "parts": [text], "lines": [], "choices": [],
            "opened": [], "sources": [], "actions": [], "metadata": {},
            "status": Status.OK.value, "confirmation": None, "question": "",
            "skill": None, "error": None, "took": 0.0,
        })

    # ------------------------------------------------------------------
    @app.post("/api/voice")
    def voice():
        """Turns recorded microphone audio into a command.

        The page records 16 kHz mono 16 bit audio and posts it as the raw body,
        which is exactly what speech recognition wants. No audio file is written
        and no microphone is opened on this side.
        """
        frames = request.get_data(cache=False, as_text=False)
        if not frames:
            return jsonify({"error": "Nothing was recorded."}), 400
        if len(frames) > MAX_AUDIO_BYTES:
            return jsonify({"error": "That recording is too long."}), 400

        assistant = get_assistant()

        settings = assistant.settings
        seconds = len(frames) / float(settings.sample_rate * settings.sample_width)
        if seconds > settings.max_recording_seconds:
            frames = frames[: settings.max_recording_seconds
                            * settings.sample_rate * settings.sample_width]

        heard = _call(_transcribe(assistant, frames))

        if not heard.ok:
            return jsonify({"error": heard.reason}), 200

        response = _call(assistant.handle_input(heard.text, Source.VOICE))
        return jsonify(_reply(response))

    @app.post("/api/tts")
    def tts():
        """Renders a reply to a WAV for the page to play."""
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"error": "Nothing to say."}), 400
        if len(text) > 2000:
            return jsonify({"error": "That is too long to read out."}), 400

        assistant = get_assistant()
        audio, error = _call(_speak_to_file(assistant, text))
        if error:
            return jsonify({"error": error}), 500
        return Response(audio, mimetype="audio/wav")

    # ------------------------------------------------------------------
    @app.get("/api/history")
    def history():
        """The conversation so far."""
        assistant = get_assistant()
        limit = int(request.args.get("limit", 50))
        turns = assistant.conversation.history(limit)
        return jsonify({
            "turns": [turn.as_dict() for turn in turns],
            "conversation": assistant.conversation.snapshot(),
        })

    @app.post("/api/history/clear")
    def clear_history():
        assistant = get_assistant()
        assistant.conversation.clear()
        return jsonify({"cleared": True})

    @app.get("/api/skills")
    def skills():
        """What this Jarvis can do, for the page to list."""
        assistant = get_assistant()
        return jsonify({
            "skills": assistant.registry.describe(),
            "risk": policy.risk_counts(),
            "automation": _automation(assistant),
        })

    @app.get("/api/settings")
    def get_settings():
        """The settings the page may see and change. Never a secret."""
        return jsonify(get_assistant().settings.public_summary)

    @app.post("/api/settings")
    def update_settings():
        """Changes a setting. Only the ones listed here can be changed."""
        payload = request.get_json(silent=True) or {}
        assistant = get_assistant()

        # The one setting the page may turn on and off, and what it allows.
        allowed = {
            "voiceEnabled": "voice_enabled",
            "wakeWordEnabled": "wake_word_enabled",
            "memoryEnabled": "memory_enabled",
            "confirmDangerousActions": "confirm_dangerous_actions",
            "automationEnabled": "automation_enabled",
            "aiEnabled": "ai_enabled",
            "inputMode": "input_mode",
        }

        changes = {}
        for key, value in payload.items():
            field = allowed.get(key)
            if field is None:
                # Refused rather than ignored, so a typo in the page is visible.
                return jsonify({"error": f"{key} is not a setting."}), 400
            changes[field] = value

        try:
            assistant.settings = assistant.settings.with_overrides(**changes)
        except (ValueError, TypeError) as error:
            return jsonify({"error": str(error)}), 400

        assistant.confirmations.confirm_dangerous = (
            assistant.settings.confirm_dangerous_actions
        )
        if "memory_enabled" in changes and not changes["memory_enabled"]:
            assistant.memory = None

        return jsonify(assistant.settings.public_summary)

    @app.get("/api/memory")
    def memory():
        assistant = get_assistant()
        if assistant.memory is None:
            return jsonify({"enabled": False, "facts": []})
        return jsonify({
            "enabled": True,
            "facts": [fact.as_dict() for fact in assistant.memory.store.all_facts()],
        })

    @app.post("/api/memory")
    def add_memory():
        payload = request.get_json(silent=True) or {}
        assistant = get_assistant()
        if assistant.memory is None:
            return jsonify({"error": "Memory is switched off."}), 400

        fact = str(payload.get("fact", "")).strip()
        if not fact:
            return jsonify({"error": "Nothing to remember."}), 400

        stored = _call(_blocking(assistant, assistant.memory.remember,
                                       fact))
        if stored is None:
            # Said plainly rather than a false agreement, because the store
            # refused it on purpose.
            return jsonify({
                "error": "I will not remember that one, because it looks like "
                         "a password or something private.",
            }), 400
        return jsonify({"remembered": stored.as_dict()})

    @app.delete("/api/memory")
    def clear_memory():
        assistant = get_assistant()
        if assistant.memory is None:
            return jsonify({"error": "Memory is switched off."}), 400
        _call(_blocking(assistant, assistant.memory.clear))
        return jsonify({"cleared": True})

    # ------------------------------------------------------------------
    @app.get("/api/activity")
    def activity():
        """What has been happening, for the activity panel."""
        assistant = get_assistant()
        return jsonify({
            "recent": assistant.bus.recent(40),
            "conversation": assistant.conversation.snapshot(),
        })

    @app.get("/api/events")
    def events():
        """A stream of events for a page that wants to follow along."""
        assistant = get_assistant()
        return jsonify({"recent": assistant.bus.recent(100)})

    @app.post("/api/shutdown")
    def shutdown():
        """Stops the dashboard, leaving Windows alone."""
        assistant = get_assistant()
        threading.Timer(0.4, lambda: os._exit(0)).start()
        return jsonify({"stopped": True,
                        "name": assistant.settings.assistant_name})


# ----------------------------------------------------------------------
def _is_rename(text: str) -> bool:
    lowered = text.lower()
    return ("change your name" in lowered
            or "rename yourself" in lowered
            or "what should i call you" in lowered)


def _reply(response) -> dict:
    """The shape the page reads.

    Two keys are always present rather than only sometimes. The page reads both
    unconditionally, and a key that appears and disappears depending on how the
    command went is how a page ends up asking why something is undefined.
    """
    payload = response.as_dict()
    payload["lines"] = response.metadata.get("lines", []) or []
    # Set only by the rename branch above, which answers before the core runs.
    payload.setdefault("prompt", None)
    return payload


def empty_reply() -> dict:
    """Every key the page reads, with nothing in it.

    Used when the assistant could not be reached at all, so the page gets the
    shape it expects rather than a bare error it has to guess at.
    """
    return {
        "text": "",
        "status": "failed",
        "skill": None,
        "choices": [],
        "opened": [],
        "sources": [],
        "actions": [],
        "lines": [],
        "metadata": {},
        "confirmation": None,
        "prompt": None,
        "took": 0.0,
        "error": None,
    }


def _automation(assistant) -> dict:
    from jarvis2.automation.actions import describe

    return {
        "enabled": bool(assistant.settings.automation_enabled),
        "steps": describe(),
    }


async def _transcribe(assistant, frames: bytes):
    from jarvis2.voice.input import VoiceInput

    def work():
        return VoiceInput(assistant.settings).transcribe_audio(frames)

    return await asyncio.to_thread(work)


async def _blocking(assistant, function, *args, **kwargs):
    """Runs blocking work off the loop.

    Used for the memory file, which is disk I/O. Going through the assistant's
    own runner rather than a fresh executor keeps every bit of blocking work on
    the same path, so there is one place that knows about it.
    """
    return await assistant._run_blocking(function, *args, **kwargs)


async def _speak_to_file(assistant, text: str):
    """Renders a reply to a WAV, then removes it straight away."""
    path = os.path.join(tempfile.gettempdir(), f"jarvis2_{uuid.uuid4().hex}.wav")
    settings = assistant.settings

    def render():
        from pyttsx3.engine import Engine

        engine = Engine()
        try:
            voices = engine.getProperty("voices")
            if voices and settings.voice_index < len(voices):
                engine.setProperty("voice", voices[settings.voice_index].id)
            engine.setProperty("rate", settings.voice_rate)
            engine.setProperty("volume", 1.0)
            engine.save_to_file(text, path)
            engine.runAndWait()
        finally:
            engine.stop()
        return path

    try:
        await asyncio.to_thread(render)
    except Exception as error:
        _log.warning("could not render speech: %s", error)
        return b"", f"Could not speak that: {error}"

    try:
        with open(path, "rb") as handle:
            audio = handle.read()
    except OSError as error:
        return b"", f"No audio came back: {error}"
    finally:
        # Read and removed together, so repeated replies do not leave a trail.
        try:
            os.remove(path)
        except OSError:
            pass

    if not audio:
        return b"", "No audio came back."
    return audio, ""

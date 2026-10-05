"""A browser interface for Jarvis, served on this computer only.

The assistant itself is unchanged: every command runs through the same
handle_command the terminal uses, so the two front ends cannot drift apart.

Start it with:

    python webapp.py

It binds to the loopback address, so nothing on the network can reach it, and
it opens your default browser at http://127.0.0.1:8765.
"""

import contextlib
import io
import os
import sys
import tempfile
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import webbrowser as wb
import speech_recognition as sr
from pyttsx3.engine import Engine

import jarvis
from flask import Flask, Response, jsonify, request, send_from_directory

HOST = "127.0.0.1"
PORT = 8765

# The rate the browser microphone records at. Google Speech wants 16 kHz.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # bytes, signed 16 bit little endian

# A recording longer than this is cut off, so a forgotten microphone cannot
# fill memory with silence.
MAX_SECONDS = 12

app = Flask(__name__, static_folder="static", static_url_path="/static")


def _client_ip() -> str:
    return request.remote_addr or ""


@app.before_request
def _only_this_machine() -> None:
    """Refuses anything that did not come from this computer.

    The server binds to the loopback address already, so this only guards
    against a proxy on the machine forwarding requests in from elsewhere.
    """
    if _client_ip() not in ("127.0.0.1", "::1"):
        return ("This interface only answers this computer.", 403)


@app.get("/")
def index() -> str:
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def state():
    """Tells the page what the assistant is currently doing."""
    return jsonify(
        {
            "name": jarvis.load_name(),
            "muted": jarvis.MUTED,
            "inputMode": jarvis.INPUT_MODE,
            "sampleRate": SAMPLE_RATE,
            "maxSeconds": MAX_SECONDS,
            "pending": (
                None if jarvis._pending is None else {
                    "count": len(jarvis._pending),
                    "action": jarvis._pending_action,
                }
            ),
        }
    )


@app.post("/api/command")
def command():
    """Runs one typed or spoken command and returns what happened."""
    text = (request.get_json(silent=True) or {}).get("text", "")
    text = str(text).strip().lower()
    if not text:
        return jsonify({"error": "Say something first."}), 400

    # Renaming asks a follow up question, which the page collects itself
    # rather than the server waiting on a line of input that will never come.
    if "change your name" in text or "rename yourself" in text:
        return jsonify({"prompt": "What would you like to name me?"})

    return jsonify(jarvis.handle_command(text))


@app.post("/api/name")
def rename():
    """Stores the new name the page collected for the rename question."""
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    if not name:
        return jsonify({"error": "Please give me a name."}), 400

    jarvis.set_name_to(name)
    jarvis._said.clear()
    jarvis._opened.clear()
    return jsonify(
        {
            "text": f"Alright, I will be called {name} from now on.",
            "parts": [f"Alright, I will be called {name} from now on."],
            "lines": [],
            "results": None,
            "opened": [],
            "pending": None,
            "stop": False,
        }
    )


@app.post("/api/listen")
def listen():
    """Turns recorded microphone audio into a command.

    The page records 16 kHz mono 16 bit audio and posts it as the raw body,
    which is exactly what speech_recognition wants, so no audio file is
    written and no microphone is opened on the server.
    """
    frames = request.get_data(cache=False)
    if not frames:
        return jsonify({"error": "Nothing was recorded."}), 400

    seconds = len(frames) / float(SAMPLE_RATE * SAMPLE_WIDTH)
    if seconds > MAX_SECONDS:
        frames = frames[: MAX_SECONDS * SAMPLE_RATE * SAMPLE_WIDTH]

    audio = sr.AudioData(frames, SAMPLE_RATE, SAMPLE_WIDTH)

    jarvis._said.clear()
    jarvis._opened.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        text = jarvis._recognize(audio)
    # Recognition announces its own failure, so pass on the reason it gave.
    reason = " ".join(jarvis._said)
    jarvis._said.clear()

    if not text:
        return jsonify({"error": reason or "Sorry, I did not understand that."})
    return jsonify({"text": text})


@app.post("/api/tts")
def tts():
    """Renders a reply to a WAV file for the page to play."""
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
    if not text:
        return jsonify({"error": "Nothing to say."}), 400

    path = os.path.join(tempfile.gettempdir(), f"jarvis_tts_{uuid.uuid4().hex}.wav")
    engine = Engine()
    try:
        engine.setProperty("voice", engine.getProperty("voices")[jarvis.VOICE_INDEX].id)
        engine.setProperty("rate", jarvis.RATE)
        engine.setProperty("volume", 1.0)
        engine.save_to_file(text, path)
        engine.runAndWait()
    except Exception as error:
        return jsonify({"error": f"Could not speak that: {error}"}), 500
    finally:
        engine.stop()

    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return jsonify({"error": "No audio came back."}), 500

    # The audio is read and the file removed straight away, so repeated
    # replies do not leave a trail of wav files behind.
    with open(path, "rb") as handle:
        audio = handle.read()
    try:
        os.remove(path)
    except OSError:
        pass

    return Response(audio, mimetype="audio/wav")


@app.post("/api/shutdown")
def shutdown():
    """Stops the web interface, leaving Windows alone."""
    jarvis.speak("Going offline. Have a good day!")
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return jsonify({"stopped": True})


def serve(open_browser: bool = True) -> None:
    """Starts the interface, with the PC speakers off.

    Replies are rendered to audio for the browser to play, so speaking them
    here as well would double up.
    """
    jarvis.MUTED = True

    url = f"http://{HOST}:{PORT}"
    print(f"Jarvis is listening on {url}")
    print("Press Ctrl+C to close it.")

    if open_browser:
        threading.Timer(0.8, lambda: wb.open(url)).start()

    # Single threaded, because the numbered results list and the command
    # itself live in module state rather than in a session.
    app.run(host=HOST, port=PORT, debug=False, threaded=False, use_reloader=False)


if __name__ == "__main__":
    try:
        serve()
    except OSError as error:
        print(f"Could not start on port {PORT}: {error}")
        print("Close whatever is using that port, or edit PORT in webapp.py.")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print()
        print("Jarvis is offline. Have a good day!")
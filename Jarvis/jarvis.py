import contextlib
import ctypes
import difflib
import datetime
import io
import re
import speech_recognition as sr
import string
import sys
import warnings
import wikipedia
import webbrowser as wb
import os
import pyautogui
import pyjokes
import requests
from pyttsx3.engine import Engine

# Media filenames contain emoji and non-Latin characters that a default
# Windows console cannot encode; printing them would raise UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

VOICE_INDEX = 1
RATE = 150
VOLUME = 1

INPUT_MODE = "voice"
MUTED = False

# Spoken phrases for apps that have no Start Menu shortcut, mapped to an
# executable Windows can find on PATH.
APP_COMMANDS = {
    "notepad": "notepad.exe",
    "notes": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
}

# Spoken phrases mapped to the exact shortcut name of an installed app.
APP_ALIASES = {
    "browser": "Google Chrome",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "editor": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
}

# Names the website branches handle, so "open google" still opens the site.
SITE_KEYWORDS = ("youtube", "google")

# Folders searched for songs and videos.
MEDIA_FOLDERS = ("Downloads", "Music", "Videos", "Desktop", "Pictures")
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".wma", ".ogg", ".opus",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v",
}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# Folders searched for documents: the same ones as media, plus Documents.
DOCUMENT_FOLDERS = MEDIA_FOLDERS + ("Documents",)
DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".csv", ".log",
    ".xlsx", ".xls", ".xlsm", ".pptx", ".ppt",
}

# Folders that name a group in the results list. Documents are included so a
# file there is reported as "Documents" and not as the top folder of its path.
RESULT_FOLDERS = MEDIA_FOLDERS + ("Documents",)

# Directories that never hold the user's media but are expensive to walk.
JUNK_FOLDERS = {
    ".venv", "venv", "node_modules", "site-packages", ".git", "__pycache__",
    "$recycle.bin", "system volume information",
}

# Word and Excel leave a small "~$" owner file beside the real one while a
# document is open, and it is never what the user meant to open.
LOCK_FILE_PREFIX = "~$"

# Spoken phrases mapped to a user folder.
FOLDER_ALIASES = {
    "downloads": "Downloads",
    "download": "Downloads",
    "music": "Music",
    "videos": "Videos",
    "video": "Videos",
    "pictures": "Pictures",
    "images": "Pictures",
    "desktop": "Desktop",
    "documents": "Documents",
    "docs": "Documents",
}

# A spoken name must match at least this share of a file name's words. Single
# word queries either hit or miss, so this only filters multi word queries.
MEDIA_MATCH_FLOOR = 0.6

# How many results to print before asking the user to say 'more'.
MEDIA_PAGE_SIZE = 200

# About this much of a document is read out loud. A whole document can run to
# hundreds of pages, which would take longer to say than to read.
READ_CHAR_LIMIT = 1200

# How many pages of a PDF to pull text from, since text is read in order.
READ_PAGES = 3

OPEN_VERBS = ("open ", "launch ", "start ", "run ")
MEDIA_VERBS = ("play ", "watch ", "listen to ", "listen ", "start playing ")
# The longer forms come first, or "read aloud x" would leave "aloud x" behind.
READ_VERBS = ("read aloud ", "read out loud ", "read out ", "read ")

# Words that mean "look this up", for anyone who prefers to be explicit.
LOOKUP_WORDS = ("wikipedia", "wiki")

# Wording wrapped around a topic, stripped before looking it up, so
# "who is einstein" looks up "einstein". Longest first.
QUESTION_PREFIXES = (
    "tell me about", "search for", "look up", "search", "define", "explain",
    "what is", "what are", "what was", "who is", "who was", "who are",
    "where is", "where are", "when did", "when was", "when is",
)

# How many alternative articles to offer when a topic means several things.
LOOKUP_CHOICES = 5

# How many sentences of an article to read out.
LOOKUP_SENTENCES = 2

# Seconds to wait on Wikipedia before giving up. The library sets no timeout
# of its own, so one slow reply would otherwise hang Jarvis indefinitely.
LOOKUP_TIMEOUT = 10

# A question about the clock or the date mentions one of these words and
# nothing else worth looking up. That is what keeps "what is the time
# machine" from being answered with the time.
CLOCK_WORDS = ("time", "clock", "o'clock")
DATE_WORDS = ("date", "day", "today", "calendar")
QUESTION_FILLER = {
    "what", "whats", "is", "are", "was", "the", "current", "now", "tell",
    "me", "please", "it", "of", "day", "today", "date", "time", "clock",
    "o'clock", "right", "exactly",
}

# Answers to something Jarvis asked. These are not questions, so they must not
# be sent off to be looked up when no list is waiting for one.
REPLY_WORDS = {
    "yes", "yeah", "yep", "no", "nope", "ok", "okay", "sure", "thanks",
    "thank", "you", "never", "mind", "cancel", "goodbye", "bye",
    "more", "next", "again", "all", "everything", "page", "show",
}

# Where a screenshot is saved, best first. Some Windows profiles have a
# Pictures folder that refuses to be written to, so there is a fallback.
SCREENSHOT_FOLDERS = ("Pictures", "Desktop", "Downloads")
ARTICLES = ("the ", "my ", "a ", "an ")
GENERIC_MEDIA_WORDS = {
    "music", "song", "songs", "video", "videos", "track", "movie", "movies",
    "album", "file", "something", "anything", "it", "that",
}
GENERIC_DOCUMENT_WORDS = {
    "document", "documents", "doc", "docs", "file", "files", "pdf",
    "text file", "note", "notes", "something", "anything", "it", "that",
}
POLITE_PREFIXES = ("please ", "can you ", "could you ", "would you ", "hey jarvis ")

_apps_cache = None
_media_cache = None
_external_cache = None
_external_roots = None
_doc_cache = None
_external_doc_cache = None
_external_doc_roots = None
_pending = None
_pending_query = ""
_pending_shown = 0
_pending_action = None

# Everything Jarvis says and every file it hands to Windows during one
# command. Recording them here is what lets the web interface show the
# replies instead of only printing them to a terminal.
_said = []
_opened = []

# The numbered listing produced by the command being run, kept so an
# interface can draw it. None when a command lists nothing.
_last_results = None

# The article a lookup just read, kept for the same reason.
_last_lookup = None


def _strip_articles(text: str) -> str:
    """Removes a leading article, so "the music folder" becomes "music folder"."""
    lowered = text.lower()
    for article in ARTICLES:
        if lowered.startswith(article):
            return text[len(article):].strip()
    return text


def _words(text: str) -> set:
    """The whole words in a phrase, lowercased.

    A trailing "'s" is dropped, so "today's date" and "today" are the same
    word to the question helpers.
    """
    found = re.findall(r"[a-z0-9']+", text.lower())
    return {word[:-2] if word.endswith("'s") else word for word in found}


def _asks_about(query: str, subject_words) -> bool:
    """True when a question is only about the clock or the date.

    The subject word has to be there, and nothing outside the filler words
    may be mentioned alongside it. That is what tells "what is the time"
    apart from "what is the time machine".
    """
    words = _words(query)
    return bool(words & set(subject_words)) and words <= QUESTION_FILLER


def _asks_for_time(query: str) -> bool:
    """True for "what is the time" and the other ways of asking for a clock."""
    return _asks_about(query, CLOCK_WORDS)


def _asks_for_date(query: str) -> bool:
    """True for "what is the date" and the other ways of asking for a date."""
    return _asks_about(query, DATE_WORDS)


def _mentions_lookup(query: str) -> bool:
    """True when the user named Wikipedia outright."""
    words = _words(query)
    return bool(words & set(LOOKUP_WORDS))


def _is_a_reply(query: str) -> bool:
    """True when a phrase answers Jarvis rather than asking it anything.

    A number or a "yes" on its own is an answer to a list that is not there,
    and looking "1" up on Wikipedia would be nonsense.
    """
    text = query.strip()
    if text.isdigit():
        return True
    words = _words(text)
    return bool(words) and words <= REPLY_WORDS


def _question_prefixes() -> tuple:
    """The question words, longest first so "wikipedia" beats "wiki"."""
    return tuple(sorted(
        tuple(QUESTION_PREFIXES) + tuple(LOOKUP_WORDS),
        key=len,
        reverse=True,
    ))


def _scaffolding() -> set:
    """Every word that only frames a question rather than naming a topic."""
    words = set(QUESTION_FILLER)
    for phrase in tuple(QUESTION_PREFIXES) + tuple(LOOKUP_WORDS):
        words |= _words(phrase)
    return words


def _strip_one_prefix(text: str) -> str:
    """Removes a leading question word, if there is one to remove.

    Prefixes are tried longest first, or "wiki" would be chopped off the front
    of "wikipedia" and leave "pedia" behind.
    """
    lowered = text.lower()
    for prefix in _question_prefixes():
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text.strip()


def _lookup_topic(query: str) -> str:
    """Strips the question wording, so "who is X" looks up X.

    Prefixes stack, so "wikipedia what is the time" is unwrapped one layer at
    a time. Stopping as soon as something worth looking up is left means a
    topic that happens to start with a question word survives intact.
    """
    text = query.strip()
    for _ in range(4):
        remainder = _strip_one_prefix(text)
        if not remainder or not _words(remainder) - QUESTION_FILLER:
            break
        text = remainder

    for word in LOOKUP_WORDS:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip(" ?.!,;:")

# Wikimedia rejects the library's default User-Agent with HTTP 429
wikipedia.set_user_agent(
    "JarvisDesktopAssistant/1.0 "
    "(https://github.com/kishanrajput23/Jarvis-Desktop-Voice-Assistant)"
)

# Looking things up is now the fallback for anything Jarvis does not
# understand, so it leans on the API more than it used to. Rate limiting
# keeps a burst of lookups from being refused and answered with a parse
# error instead of an article.
wikipedia.set_rate_limiting(True)


@contextlib.contextmanager
def _wikipedia_timeout(seconds: int = LOOKUP_TIMEOUT):
    """Gives the Wikipedia library's HTTP call a timeout while inside.

    The library calls requests.get with no timeout at all, so a reply that
    never arrives would leave Jarvis waiting forever. The change is undone
    on the way out, so nothing else on the machine inherits it.
    """
    original = requests.get

    def guarded(url, **kwargs):
        kwargs.setdefault("timeout", seconds)
        return original(url, **kwargs)

    requests.get = guarded
    try:
        yield
    finally:
        requests.get = original


def _wikipedia_offline() -> None:
    """Reports that Wikipedia could not be reached.

    A dropped connection or a reply that never came is the common failure
    here, and it is worth saying so plainly rather than letting it surface as
    something went wrong.
    """
    speak("I could not reach Wikipedia. Check your internet connection.")
    print("  Wikipedia could not be reached.")


def speak(audio) -> None:
    """Speaks the given text out loud, unless Jarvis is muted.

    Every reply is recorded first, so an interface that plays its own audio
    still knows what was said. pyttsx3's SAPI5 backend only speaks the first
    utterance per engine on Windows: every later ``say()`` returns immediately
    with no audio. A fresh engine per call avoids that, and ``stop()`` releases
    the SAPI voice.
    """
    _said.append(audio)

    if MUTED:
        return

    engine = Engine()
    try:
        engine.setProperty('voice', engine.getProperty('voices')[VOICE_INDEX].id)
        engine.setProperty('rate', RATE)
        engine.setProperty('volume', VOLUME)
        engine.say(audio)
        engine.runAndWait()
    finally:
        engine.stop()


def open_with_system(path: str) -> None:
    """Hands a file or folder to Windows to open with its usual program."""
    _opened.append(path)
    os.startfile(path)


def time() -> None:
    """Tells the current time."""
    current_time = datetime.datetime.now().strftime("%I:%M:%S %p")
    speak("The current time is")
    speak(current_time)
    print("The current time is", current_time)


def date() -> None:
    """Tells the current date."""
    now = datetime.datetime.now()
    speak("The current date is")
    speak(f"{now.day} {now.strftime('%B')} {now.year}")
    print(f"The current date is {now.day}/{now.month}/{now.year}")


def wishme() -> None:
    """Greets the user based on the time of day."""
    speak("Welcome back, sir!")
    print("Welcome back, sir!")

    hour = datetime.datetime.now().hour
    if 4 <= hour < 12:
        speak("Good morning!")
        print("Good morning!")
    elif 12 <= hour < 16:
        speak("Good afternoon!")
        print("Good afternoon!")
    elif 16 <= hour < 24:
        speak("Good evening!")
        print("Good evening!")
    else:
        speak("Good night, see you tomorrow.")

    assistant_name = load_name()
    speak(f"{assistant_name} at your service. Please tell me how may I assist you.")
    print(f"{assistant_name} at your service. Please tell me how may I assist you.")


def screenshot() -> None:
    """Takes a screenshot and saves it to the first folder that will take it.

    Not every profile has a writable Pictures folder, and a screenshot is not
    worth failing over, so the desktop and Downloads are tried in turn.
    """
    img = pyautogui.screenshot()
    home = os.path.expanduser("~")

    for name in SCREENSHOT_FOLDERS:
        folder = os.path.join(home, name)
        img_path = os.path.join(folder, "screenshot.png")
        try:
            os.makedirs(folder, exist_ok=True)
            img.save(img_path)
        except OSError as error:
            print(f"  Could not save to {folder}: {error}")
            continue

        speak(f"Screenshot saved as {img_path}.")
        print(f"Screenshot saved as {img_path}.")
        return

    speak("I took the screenshot but could not save it anywhere.")
    print("  Screenshot could not be saved.")

def _recognize(audio) -> str | None:
    """Turns recorded audio into lowercased text, reporting any failure.

    Shared by the microphone and the browser, so both spell a name the same
    way and report a bad recording the same way.
    """
    recognizer = sr.Recognizer()
    try:
        print("Recognizing...")
        return recognizer.recognize_google(
            audio,
            language="en-in",
            key=os.environ.get("GOOGLE_SPEECH_API_KEY"),
        ).lower()
    except sr.UnknownValueError:
        speak("Sorry, I did not understand that.")
    except sr.RequestError:
        speak("Speech recognition service is unavailable.")
    except Exception as e:
        speak(f"An error occurred: {e}")
        print(f"Error: {e}")
    return None


def takecommand() -> str | None:
    """Takes microphone input from the user and returns it as text."""
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening...")
        r.pause_threshold = 1

        try:
            audio = r.listen(source, timeout=5)  # Listen with a timeout
        except sr.WaitTimeoutError:
            speak("Timeout occurred. Please try again.")
            return None

    query = _recognize(audio)
    if query:
        print(query)
    return query

def set_name_to(name: str) -> None:
    """Stores a new name for the assistant and confirms it.

    Split out from the question asking below, so a front end that collects
    the answer itself can hand the name straight over.
    """
    with open("assistant_name.txt", "w") as file:
        file.write(name)
    speak(f"Alright, I will be called {name} from now on.")

def set_name() -> None:
    """Sets a new name for the assistant."""
    speak("What would you like to name me?")
    name = get_command()
    if name:
        set_name_to(name)
    else:
        speak("Sorry, I couldn't catch that.")

def load_name() -> str:
    """Loads the assistant's name from a file, or uses a default name."""
    try:
        with open("assistant_name.txt", "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        return "Jarvis"  # Default name


def _shortcut_folders() -> list:
    """Returns the folders that hold shortcuts to installed apps."""
    folders = [
        os.path.join(
            os.environ.get("ProgramData", ""),
            "Microsoft", "Windows", "Start Menu", "Programs",
        ),
        os.path.join(
            os.environ.get("AppData", ""),
            "Microsoft", "Windows", "Start Menu", "Programs",
        ),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.environ.get("Public", ""), "Desktop"),
    ]
    return [folder for folder in folders if folder and os.path.isdir(folder)]


def installed_apps() -> dict:
    """Maps each installed app's shortcut name to its shortcut path.

    The scan is cached, so the cost is paid once per run.
    """
    global _apps_cache
    if _apps_cache is None:
        _apps_cache = {}
        for folder in _shortcut_folders():
            for dirpath, _subfolders, files in os.walk(folder):
                for filename in files:
                    if filename.lower().endswith(".lnk"):
                        label = os.path.splitext(filename)[0]
                        _apps_cache.setdefault(
                            label, os.path.join(dirpath, filename)
                        )
    return _apps_cache


def find_app(name: str):
    """Finds the best match for an app name. Returns (label, target) or None."""
    query = name.strip().lower()
    if not query:
        return None

    command = APP_COMMANDS.get(query)
    if command:
        label = " ".join(word.capitalize() for word in query.split())
        return label, command

    apps = installed_apps()

    alias = APP_ALIASES.get(query)
    if alias:
        for label in apps:
            if label.lower() == alias.lower():
                return label, apps[label]

    for label in apps:
        if label.lower() == query:
            return label, apps[label]

    # Shortest name wins, so "firefox" picks "Firefox" over
    # "Firefox Private Browsing".
    partial = sorted(
        (label for label in apps if query in label.lower()), key=len
    )
    if partial:
        return partial[0], apps[partial[0]]

    close = difflib.get_close_matches(query, list(apps), n=1, cutoff=0.6)
    if close:
        return close[0], apps[close[0]]
    return None


def open_app(query: str) -> bool:
    """Opens the app named in query.

    Returns True when query was an app request, so the caller can skip the
    remaining commands.
    """
    request = query
    for prefix in POLITE_PREFIXES:
        if request.startswith(prefix):
            request = request[len(prefix):]

    for verb in OPEN_VERBS:
        if request.lower().startswith(verb):
            request = _strip_articles(request[len(verb):].strip())
            break
    else:
        return False

    if request.lower() in SITE_KEYWORDS:
        return False

    match = find_app(request)
    if match is None:
        speak(f"I could not find an app called {request}.")
        print(f"No app found for: {request}")
        return True

    label, target = match
    try:
        open_with_system(target)
    except OSError as error:
        speak(f"Sorry, I could not open {label}.")
        print(f"Error: {error}")
        return True

    speak(f"Opening {label}.")
    print(f"Opening {label} -> {target}")
    return True


def _scan_media_roots(roots, extensions=MEDIA_EXTENSIONS) -> dict:
    """Maps each media or document name to every file found with that name.

    Walks each root all the way down while skipping dependency directories,
    so files are found wherever they sit on the drive. A name can map to
    several files, for example song.mp3 and song.m4a.
    """
    library = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, subfolders, files in os.walk(root, onerror=_ignore_walk_error):
            subfolders[:] = [
                name
                for name in subfolders
                if name.lower() not in JUNK_FOLDERS
            ]
            for filename in files:
                if filename.startswith(LOCK_FILE_PREFIX):
                    continue
                extension = os.path.splitext(filename)[1].lower()
                if extension in extensions:
                    label = os.path.splitext(filename)[0]
                    library.setdefault(label, []).append(
                        os.path.join(dirpath, filename)
                    )
    for paths in library.values():
        paths.sort()
    return library


def _ignore_walk_error(error) -> None:
    """Swallows access-denied errors from folders such as System Volume Information."""
    return None


def media_library() -> dict:
    """Indexes the user's normal folders. The scan is cached."""
    global _media_cache
    if _media_cache is None:
        home = os.path.expanduser("~")
        _media_cache = _scan_media_roots(
            [os.path.join(home, folder) for folder in MEDIA_FOLDERS]
        )
    return _media_cache


def document_library() -> dict:
    """Indexes the user's normal folders for documents. The scan is cached."""
    global _doc_cache
    if _doc_cache is None:
        home = os.path.expanduser("~")
        _doc_cache = _scan_media_roots(
            [os.path.join(home, folder) for folder in DOCUMENT_FOLDERS],
            DOCUMENT_EXTENSIONS,
        )
    return _doc_cache


def _volume_size_gb(root: str) -> float:
    """Returns a volume's total size in gigabytes, or 0 if it cannot be read."""
    free_to_caller = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    free_total = ctypes.c_ulonglong(0)
    read = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(root),
        ctypes.byref(free_to_caller),
        ctypes.byref(total),
        ctypes.byref(free_total),
    )
    return total.value / (1024 ** 3) if read else 0.0


def _extra_drives() -> list:
    """Returns every drive except the system drive and tiny system volumes.

    USB drives normally report themselves as fixed disks rather than
    removable ones, so both kinds of volume are kept.
    """
    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    system_drive = os.environ.get("SystemDrive", "C:")[0].upper()

    roots = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not (mask >> index) & 1 or letter == system_drive:
            continue

        root = f"{letter}:{os.sep}"
        # 2 is removable and 3 is fixed; skip network, optical and unknown.
        if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) not in (2, 3):
            continue
        if _volume_size_gb(root) < 1:  # skips "System Reserved" partitions
            continue

        roots.append(root)
    return roots


def external_media_library() -> dict:
    """Indexes every drive other than the system drive.

    Scanning these can take a couple of seconds, so it only happens once the
    normal folders have failed to match. The drive list is re-checked on every
    call, which means a drive plugged in mid-session gets indexed and one
    unplugged is dropped.
    """
    global _external_cache, _external_roots

    roots = _extra_drives()
    if _external_cache is None or _external_roots != roots:
        _external_cache = _scan_media_roots(roots)
        _external_roots = roots
    return _external_cache


def external_document_library() -> dict:
    """Indexes every drive other than the system drive, for documents."""
    global _external_doc_cache, _external_doc_roots

    roots = _extra_drives()
    if _external_doc_cache is None or _external_doc_roots != roots:
        _external_doc_cache = _scan_media_roots(roots, DOCUMENT_EXTENSIONS)
        _external_doc_roots = roots
    return _external_doc_cache


def _clean_name(text: str) -> str:
    """Reduces a file or spoken name to comparable lowercase words."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _match_score(query: str, label: str) -> float:
    """Scores how much of a spoken name appears in a file name, from 0 to 1.

    Tokens are matched loosely, so "collo blue top shotta" still matches
    "COLLOBLUE - TOP SHOTTA FT KBC".
    """
    tokens = _clean_name(os.path.splitext(query)[0]).split()
    words = _clean_name(label).split()
    if not tokens or not words:
        return 0.0

    hits = 0
    for token in tokens:
        for word in words:
            if token in word or (
                len(word) > 2 and (word.startswith(token) or token.startswith(word))
            ):
                hits += 1
                break
    return hits / len(tokens)


def _rank_matches(library: dict, query: str, limit: int | None = None) -> list:
    """Ranks a name to paths library against query, best match first.

    Each entry is (name, path, score). One name appears once per file, so a
    song saved as both .mp3 and .m4a is listed twice. Pass limit to keep only
    the best few.
    """
    if not library:
        return []

    ranked = []
    for label in library:
        if label.lower() == query:
            score = 1.0
        else:
            score = _match_score(query, label)
            if score < MEDIA_MATCH_FLOOR:
                continue
        ranked.append((score, label))
    ranked.sort(key=lambda item: item[0], reverse=True)

    candidates = []
    for score, label in ranked[:limit]:
        for path in library[label]:
            candidates.append((label, path, score))
    return candidates


def find_media(name: str, search_drives: bool = False, limit: int | None = None) -> list:
    """Returns every media file matching name, best match first."""
    query = name.strip().lower()
    if not query:
        return []

    library = {label: list(paths) for label, paths in media_library().items()}
    if search_drives:
        for label, paths in external_media_library().items():
            library.setdefault(label, []).extend(paths)
    return _rank_matches(library, query, limit)


def find_document(name: str, search_drives: bool = False, limit: int | None = None) -> list:
    """Returns every document matching name, best match first."""
    query = name.strip().lower()
    if not query:
        return []

    library = {label: list(paths) for label, paths in document_library().items()}
    if search_drives:
        for label, paths in external_document_library().items():
            library.setdefault(label, []).extend(paths)
    return _rank_matches(library, query, limit)


def _launch_media(label: str, path: str, verb: str = "Playing") -> None:
    """Opens a file with the system's default program.

    verb names the action in the reply, so a document is announced as being
    opened and a song as being played.
    """
    if not os.path.isfile(path):
        speak(f"{label} is no longer available.")
        print(f"Missing: {path}")
        return

    try:
        open_with_system(path)
    except OSError as error:
        speak(f"Sorry, I could not open {label}.")
        print(f"Error: {error}")
        return

    speak(f"{verb} {label}.")
    print(f"{verb} {label} -> {path}")


def _media_location(path: str) -> tuple:
    """Names the place a media file or document lives, as (drive, folder)."""
    drive = os.path.splitdrive(path)[0].upper()
    lowered = path.lower()
    home = os.path.expanduser("~").lower()

    for folder in RESULT_FOLDERS:
        if os.path.join(home, folder).lower() + os.sep in lowered:
            return drive, folder

    remainder = os.path.dirname(os.path.splitdrive(path)[1]).lstrip("\\/")
    top = remainder.split(os.sep)[0] if remainder else "drive root"
    return drive, top


def _location_sort_key(location: tuple) -> tuple:
    """Sorts the system drive's folders first, then the other drives."""
    drive, folder = location
    system = os.path.splitdrive(os.path.expanduser("~"))[0].upper()
    return (drive != system, drive, folder)


def _file_size(path: str) -> str:
    """Formats a file size for the results list."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "size unknown"
    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.1f} GB"
    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"
    return f"{size // 1024} KB"


def order_media_results(candidates: list) -> list:
    """Sorts candidates into display order: by drive and folder, then by name.

    The numbering shown to the user is taken from this order, so the list and
    the numbers Jarvis accepts must not be sorted separately.
    """
    groups = {}
    for label, path in candidates:
        groups.setdefault(_media_location(path), []).append((label, path))

    ordered = []
    for location in sorted(groups, key=_location_sort_key):
        ordered.extend(sorted(groups[location], key=lambda item: item[0].lower()))
    return ordered


def build_results_view(entries: list, start: int, query: str, all_entries: list) -> dict:
    """Describes one page of results as data, ready to show or print.

    The numbering carried here is the numbering the user is shown, so an
    interface can render clickable rows that mean exactly what they say.
    """
    counts = {}
    for _label, path in all_entries:
        location = _media_location(path)
        counts[location] = counts.get(location, 0) + 1

    system_drive = os.path.splitdrive(os.path.expanduser("~"))[0].upper()
    searched = sorted(
        {_media_location(item[1])[0] for item in all_entries},
        key=lambda drive: (drive != system_drive, drive),
    )

    rows = []
    locations = []
    current = None
    for label, path in entries:
        location = _media_location(path)
        if location != current:
            current = location
            locations.append(
                {
                    "drive": location[0],
                    "folder": location[1],
                    "count": counts.get(location, 0),
                }
            )
        rows.append(
            {
                "n": start + len(rows),
                "label": label,
                "ext": os.path.splitext(path)[1].lstrip(".").upper(),
                "size": _file_size(path),
                "path": path,
                "drive": location[0],
                "folder": location[1],
            }
        )

    remaining = len(all_entries) - (start - 1 + len(entries))
    return {
        "query": query,
        "start": start,
        "total": len(all_entries),
        "drives": searched,
        "locations": locations,
        "rows": rows,
        "remaining": max(remaining, 0),
    }


def _single_result_view(query: str, label: str, path: str) -> dict:
    """Describes a lone match, which needs no choosing between numbers."""
    return build_results_view([(label, path)], 1, query, [(label, path)])


def print_media_results(entries: list, start: int, query: str, all_entries: list) -> None:
    """Prints the results in the given order, grouped and numbered."""
    view = build_results_view(entries, start, query, all_entries)
    counts = {
        (item["drive"], item["folder"]): item["count"] for item in view["locations"]
    }

    print()
    print(f"  {view['total']} match(es) for {query!r} on {', '.join(view['drives'])}")

    current = None
    for row in view["rows"]:
        location = (row["drive"], row["folder"])
        if location != current:
            current = location
            print(f"\n  {row['drive']}  {row['folder']} - {counts[location]} file(s)")
        print(f"    {row['n']:>4}. {row['label']}  ({row['ext']}, {row['size']})")

    if view["remaining"] > 0:
        print(f"    ... {view['remaining']} more not shown. Say 'more' for the next page.")


def build_lookup_view(titles: list, start: int, query: str, total: int) -> dict:
    """Describes a list of alternative articles as data, ready to show.

    Shaped like a file listing so an interface can draw it with the same
    code, with the fields that only mean something for files left blank.
    """
    rows = [
        {
            "n": start + index,
            "label": title,
            "ext": "",
            "size": "",
            "path": "",
            "drive": "",
            "folder": "",
        }
        for index, title in enumerate(titles)
    ]
    return {
        "query": query,
        "start": start,
        "total": total,
        "drives": ["Wikipedia"],
        "locations": [],
        "rows": rows,
        "remaining": max(total - (start - 1 + len(titles)), 0),
    }


def print_lookup_choices(titles: list, start: int) -> None:
    """Prints the articles a topic could have meant, numbered."""
    print()
    print(f"  {len(titles)} articles could match. Which one?")
    for offset, title in enumerate(titles):
        print(f"    {start + offset:>4}. {title}")


def _record_results(view: dict) -> dict:
    """Keeps the listing a command produced, and hands it back."""
    global _last_results
    _last_results = view
    return view


def _show_media_page() -> dict | None:
    """Prints the next page of pending results and describes it."""
    global _pending_shown
    if not _pending:
        return None

    start = _pending_shown + 1
    entries = _pending[start - 1: start - 1 + MEDIA_PAGE_SIZE]
    if not entries:
        print("  That is everything.")
        return None

    if _pending_action == "lookup":
        # Articles keep the order Wikipedia ranked them in, so the listing is
        # not grouped or re-sorted the way files are.
        titles = [label for label, _path in entries]
        print_lookup_choices(titles, start)
        view = build_lookup_view(titles, start, _pending_query, len(_pending))
    else:
        print_media_results(
            entries, start=start, query=_pending_query, all_entries=_pending
        )
        view = build_results_view(entries, start, _pending_query, _pending)

    _pending_shown = start - 1 + len(entries)
    return _record_results(view)


def _speak_media_summary(candidates: list) -> None:
    """Announces the result count without reading the whole list aloud."""
    places = {}
    for _label, path, _score in candidates:
        location = _media_location(path)
        places[location] = places.get(location, 0) + 1
    drive, folder = max(places, key=lambda key: places[key])
    where = f"the root of {drive}" if folder == "drive root" else f"{folder} on {drive}"

    speak(
        f"I found {len(candidates)} files. "
        f"Most of them are in {where}. "
        f"They are listed on screen with numbers. Which number?"
    )


def _run_pending_action(label: str, path: str, action: str) -> None:
    """Carries out the action the pending results were listed for.

    A numbered list can belong to a song, a document, a read request or an
    ambiguous topic, so the action that produced it is remembered rather
    than guessed at here.
    """
    if action == "read":
        read_document(label, path)
        return
    if action == "lookup":
        search_wikipedia(label, from_choice=True)
        return
    _launch_media(label, path, "Opening" if action == "open" else "Playing")


def confirm_pending(query: str) -> bool:
    """Handles the answer to a results question: a number, or 'more'."""
    global _pending, _pending_shown, _pending_action

    if _pending is None:
        return False

    answer = query.strip().lower()

    if answer in ("more", "show more", "next", "next page"):
        _show_media_page()
        return True

    candidates = _pending
    action = _pending_action
    _pending = None
    _pending_shown = 0
    _pending_action = None

    if answer in ("yes", "yeah", "yep", "ok", "okay", "sure"):
        if len(candidates) == 1:
            _run_pending_action(*candidates[0], action)
            return True
        speak(f"Please choose a number, 1 to {len(candidates)}.")
        print(f"      Say a number from 1 to {len(candidates)}, or no to cancel.")
        return True

    if answer.isdigit() and 1 <= int(answer) <= len(candidates):
        _run_pending_action(*candidates[int(answer) - 1], action)
        return True

    speak("Okay.")
    return True


def play_media(query: str) -> bool:
    """Plays the song or video named in query.

    Returns True when query was a media request, so the caller can skip the
    remaining commands.
    """
    global _pending, _pending_query, _pending_shown, _pending_action

    request = query
    for prefix in POLITE_PREFIXES:
        if request.startswith(prefix):
            request = request[len(prefix):]

    lowered = request.lower()
    for verb in MEDIA_VERBS:
        if lowered.startswith(verb):
            request = _strip_articles(request[len(verb):].strip())
            break
    else:
        return False

    request = request.strip(" .")
    if not request or request in GENERIC_MEDIA_WORDS:
        speak("Tell me which one, for example play oh jah.")
        print("Tell me which one, for example play oh jah.")
        return True

    if _external_cache is None:
        print("  Searching your other drives...")

    candidates = find_media(request, search_drives=True)

    if not candidates:
        speak(f"I could not find a song or video called {request}.")
        print(f"  No matches for {request!r}.")
        return True

    if len(candidates) == 1:
        label, path, _score = candidates[0]
        extension = os.path.splitext(path)[1].lstrip(".").upper()
        print()
        print(f"  1 match for {request!r}:")
        print(f"    {label}  ({extension}, {_file_size(path)}) -> {path}")
        _record_results(_single_result_view(request, label, path))
        _launch_media(label, path)
        return True

    # The printed order and the numbering Jarvis accepts must be the same
    # list, otherwise "say 3" plays a different file than line 3 shows.
    _pending = order_media_results(
        [(label, path) for label, path, _score in candidates]
    )
    _pending_query = request
    _pending_shown = 0
    _pending_action = "play"
    _show_media_page()
    _speak_media_summary(candidates)
    return True


def _plain_text(path: str) -> str:
    """Reads a text file, replacing any characters it cannot decode."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _rtf_text(path: str) -> str:
    """Reads an RTF file, dropping the formatting codes it is full of.

    Spoken as it stands, the codes come out as noise, so they are stripped
    before anything is said.
    """
    text = re.sub(r"\\[a-z]+-?\d* ?", " ", _plain_text(path))
    return re.sub(r"[{}]", " ", text)


def _pdf_text(path: str) -> str:
    """Reads the opening pages of a PDF."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages[:READ_PAGES])


def _docx_text(path: str) -> str:
    """Reads a Word document's paragraphs and table cells."""
    import docx

    document = docx.Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _pptx_text(path: str) -> str:
    """Reads the text on each slide of a PowerPoint deck."""
    from pptx import Presentation

    parts = []
    for slide in Presentation(path).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


def _xlsx_text(path: str) -> str:
    """Reads a spreadsheet's cells, sheet by sheet."""
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        parts = []
        for sheet in workbook.worksheets:
            parts.append(sheet.title)
            for row in sheet.iter_rows(values_only=True):
                cells = [str(value) for value in row if value is not None]
                if cells:
                    parts.append(" ".join(cells))
        return "\n".join(parts)
    finally:
        workbook.close()


# The readers are imported inside each function, so a missing package only
# stops that one format from being read instead of stopping Jarvis starting.
DOCUMENT_READERS = {
    ".txt": _plain_text,
    ".md": _plain_text,
    ".csv": _plain_text,
    ".log": _plain_text,
    ".rtf": _rtf_text,
    ".pdf": _pdf_text,
    ".docx": _docx_text,
    ".pptx": _pptx_text,
    ".xlsx": _xlsx_text,
    ".xlsm": _xlsx_text,
}


def _document_text(path: str) -> str:
    """Returns a document's text, or an empty string when it cannot be read."""
    extension = os.path.splitext(path)[1].lower()
    reader = DOCUMENT_READERS.get(extension)
    if reader is None:
        return ""

    try:
        return reader(path)
    except Exception as error:
        print(f"  Could not read {path}: {error}")
        return ""


def read_document(label: str, path: str) -> None:
    """Reads the opening of a document out loud.

    Only the first READ_CHAR_LIMIT characters are said, since a document can
    run to hundreds of pages and reading all of it would take longer than it
    would take to read it.
    """
    if not os.path.isfile(path):
        speak(f"{label} is no longer available.")
        print(f"Missing: {path}")
        return

    extension = os.path.splitext(path)[1].lower()
    if extension not in DOCUMENT_READERS:
        kind = extension.lstrip(".").upper()
        speak(f"I cannot read {kind} files, so I will open it instead.")
        print(f"  No reader for {kind}; opening {label} instead.")
        _launch_media(label, path, "Opening")
        return

    # Documents are full of line breaks and runs of spaces, which read aloud
    # as pauses, so the whitespace is squashed before anything is spoken.
    text = " ".join(_document_text(path).split())
    if not text:
        speak(f"I could not find any text in {label}.")
        print(f"  No readable text in {path}")
        return

    spoken = text[:READ_CHAR_LIMIT].strip()
    speak(spoken)
    print(spoken)

    if len(text) > len(spoken):
        speak("That is the opening part only.")
        print("  ... the rest was not read.")


def open_document(query: str) -> bool:
    """Opens or reads the document named in query.

    Returns True when query was a document request, so the caller can skip the
    remaining commands. An "open" request that matches no document returns
    False, so an app name is still looked up afterwards.
    """
    global _pending, _pending_query, _pending_shown, _pending_action

    request = query
    for prefix in POLITE_PREFIXES:
        if request.startswith(prefix):
            request = request[len(prefix):]

    lowered = request.lower()
    action = None
    for name, verbs in (("open", OPEN_VERBS), ("read", READ_VERBS)):
        for verb in verbs:
            if lowered.startswith(verb):
                request = _strip_articles(request[len(verb):].strip())
                action = name
                break
        if action:
            break
    else:
        return False

    request = request.strip(" .")
    if not request or request in GENERIC_DOCUMENT_WORDS:
        speak("Tell me which one, for example open my cv.")
        print("Tell me which one, for example open my cv.")
        return True

    if _doc_cache is None:
        print("  Searching your documents...")

    # The other drives are only worth walking when the normal folders have
    # nothing, so "open chrome" does not pay for a full scan of every drive.
    candidates = find_document(request)
    if not candidates:
        if _external_doc_cache is None:
            print("  Searching your other drives...")
        candidates = find_document(request, search_drives=True)

    if not candidates:
        if action == "open":
            return False
        speak(f"I could not find a document called {request}.")
        print(f"  No matches for {request!r}.")
        return True

    if len(candidates) == 1:
        label, path, _score = candidates[0]
        extension = os.path.splitext(path)[1].lstrip(".").upper()
        print()
        print(f"  1 match for {request!r}:")
        print(f"    {label}  ({extension}, {_file_size(path)}) -> {path}")
        _record_results(_single_result_view(request, label, path))
        if action == "read":
            read_document(label, path)
        else:
            _launch_media(label, path, "Opening")
        return True

    # The printed order and the numbering Jarvis accepts must be the same
    # list, otherwise "say 3" opens a different file than line 3 shows.
    _pending = order_media_results(
        [(label, path) for label, path, _score in candidates]
    )
    _pending_query = request
    _pending_shown = 0
    _pending_action = action
    _show_media_page()
    _speak_media_summary(candidates)
    return True


def open_folder(query: str) -> bool:
    """Opens a known user folder, for example 'open downloads'.

    Returns True when query named a folder, so the caller can skip the
    remaining commands.
    """
    request = query
    for prefix in POLITE_PREFIXES:
        if request.startswith(prefix):
            request = request[len(prefix):]

    lowered = request.lower()
    for verb in OPEN_VERBS:
        if lowered.startswith(verb):
            request = _strip_articles(request[len(verb):].strip())
            break
    else:
        return False

    for suffix in (" folder", " directory", " dir", " drive"):
        if request.lower().endswith(suffix):
            request = request[: -len(suffix)].strip()
            break

    request = request.rstrip(" .:")
    if not request:
        return False

    home = os.path.expanduser("~")
    available = {}
    for name in dict.fromkeys(FOLDER_ALIASES.values()):
        path = os.path.join(home, name)
        if os.path.isdir(path):
            available[name] = path

    label = None
    target = None

    # A bare drive letter, so "open i:" or "open d drive" opens that drive.
    if len(request) == 1 and request.isalpha():
        root = f"{request.upper()}:{os.sep}"
        if os.path.isdir(root):
            label, target = f"drive {request.upper()}", root

    elif request:
        label = FOLDER_ALIASES.get(request.lower())
        if label is None:
            close = difflib.get_close_matches(
                request.lower(), list(available), n=1, cutoff=0.6
            )
            label = close[0] if close else None
        if label in available:
            target = available[label]
        else:
            label = None

    if target is None:
        return False

    try:
        open_with_system(target)
    except OSError as error:
        speak(f"Sorry, I could not open {label}.")
        print(f"Error: {error}")
        return True

    speak(f"Opening {label}.")
    print(f"Opening {label} -> {target}")
    return True


def keyboard_command() -> str | None:
    """Reads a command from the keyboard, exiting when input closes."""
    try:
        query = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return query.lower() or None


def get_command() -> str | None:
    """Gets a command from whichever input mode is active."""
    if INPUT_MODE == "keyboard":
        return keyboard_command()
    return takecommand()


def set_input_mode(mode: str, announce: bool = True) -> None:
    """Switches between voice and keyboard input."""
    global INPUT_MODE
    INPUT_MODE = mode
    if announce:
        if mode == "keyboard":
            speak("Keyboard mode. Type your commands.")
            print("Keyboard mode. Type your commands.")
        else:
            speak("Voice mode.")
            print("Voice mode.")


def choose_input_mode() -> None:
    """Asks which input mode to use, unless a flag already decided it."""
    if "--keyboard" in sys.argv:
        set_input_mode("keyboard", announce=False)
        return
    if "--voice" in sys.argv:
        set_input_mode("voice", announce=False)
        return

    try:
        answer = input("Voice or keyboard? (v/k): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    set_input_mode("keyboard" if answer.startswith("k") else "voice", announce=False)


@contextlib.contextmanager
def _wikipedia_call():
    """Runs one library call with a timeout and without its warnings."""
    with warnings.catch_warnings():
        # The library parses disambiguation lists with BeautifulSoup and warns
        # about the parser it guessed. That is its business, not ours.
        warnings.simplefilter("ignore")
        with _wikipedia_timeout():
            yield


def _wikipedia_choices(topic: str) -> list | None:
    """The articles a topic could mean, best first.

    Wikipedia's own ranking is trusted here rather than the library's
    automatic suggestion, which answers "einstein" with the wrong person.
    An empty list means nothing matched, and None means the site could not be
    reached, so the two can be reported differently.
    """
    try:
        with _wikipedia_call():
            hits = wikipedia.search(topic, results=LOOKUP_CHOICES * 2)
    except requests.exceptions.RequestException as error:
        print(f"  Wikipedia could not be reached: {error}")
        return None
    return [title for title in hits if "disambiguation" not in title.lower()][
        :LOOKUP_CHOICES
    ]


def _title_matches(topic: str, title: str) -> bool:
    """True when an article title really is about the topic asked for.

    The library's suggestion is checked rather than trusted, because it
    answers "einstein" with Epstein and would otherwise be read out as though
    it were right.
    """
    wanted = _words(topic) - QUESTION_FILLER
    if not wanted:
        return True
    return any(
        word in other or other in word
        for word in wanted
        for other in _words(title)
    )


def _first_sentences(text: str, count: int) -> str:
    """Keeps only the opening sentences of an article."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(part for part in parts[:count] if part).strip()


def _wikipedia_extract(title: str) -> str:
    """Reads the opening of an article, given its exact title.

    The suggestion is turned off deliberately. Left on, the library mangles
    the title it was handed, turning "Mount Everest" into "mount everes" and
    then reporting that no such page exists. By this point the title has
    already been found and checked, so there is nothing left to suggest.
    """
    with _wikipedia_call():
        page = wikipedia.page(title, auto_suggest=False)
        return page.summary or ""


def _offer_choices(topic: str, choices: list) -> None:
    """Lists the articles a topic could mean and waits for a number.

    The alternatives go into the same pending list the files use, so saying
    a number picks one without any extra handling anywhere.
    """
    global _pending, _pending_query, _pending_shown, _pending_action

    _pending = [(title, "") for title in choices]
    _pending_query = topic
    _pending_shown = 0
    _pending_action = "lookup"
    _show_media_page()
    speak(
        f"{topic} could mean several things. "
        f"They are listed on screen with numbers. Which one?"
    )


def _resolve_article(topic: str) -> str | None:
    """Finds the article for a topic, offering a choice when it is ambiguous.

    Returns the article's title, or None when alternatives were listed or the
    topic could not be found at all.
    """
    try:
        with _wikipedia_call():
            title = wikipedia.page(topic).title
    except requests.exceptions.RequestException as error:
        print(f"  Wikipedia could not be reached: {error}")
        _wikipedia_offline()
        return None
    except wikipedia.exceptions.DisambiguationError as error:
        choices = [
            name for name in error.options
            if "disambiguation" not in name.lower()
        ][:LOOKUP_CHOICES]
        if len(choices) < 2:
            choices = _wikipedia_choices(topic)
            if choices is None:
                _wikipedia_offline()
                return None
        if len(choices) < 2:
            speak(f"I could not tell which {topic} you meant.")
            print(f"  No clear article for {topic!r}.")
            return None
        _offer_choices(topic, choices)
        return None

    except wikipedia.exceptions.PageError:
        # The name will not load as written, so let the search find it. That
        # is what rescues "mt everest", which the library cannot resolve.
        choices = _wikipedia_choices(topic)
        if choices is None:
            _wikipedia_offline()
            return None
        if not choices:
            speak(f"I could not find {topic} on Wikipedia.")
            print(f"  No article for {topic!r}.")
            return None
        # One clear winner is simply read, rather than making the user choose
        # between "Mount Everest" and a list of people who died climbing it.
        if _title_matches(topic, choices[0]):
            return choices[0]
        _offer_choices(topic, choices)
        return None

    if _title_matches(topic, title):
        return title

    # The suggestion drifted onto a different article, so search instead.
    choices = _wikipedia_choices(topic)
    if choices is None:
        _wikipedia_offline()
        return None
    if choices and _title_matches(topic, choices[0]):
        return choices[0]
    if len(choices) > 1:
        _offer_choices(topic, choices)
        return None

    speak(f"I could not find {topic} on Wikipedia.")
    print(f"  No article for {topic!r}.")
    return None


def search_wikipedia(query: str, from_choice: bool = False) -> bool:
    """Looks a topic up on Wikipedia and reads the article out.

    Anything Jarvis does not otherwise understand ends up here, so this also
    has to cope with a topic that means several things. When it does, the
    alternatives are listed and numbered, and saying a number reads that one.
    Returns True when it read an article.
    """
    global _last_lookup

    topic = query.strip() if from_choice else _lookup_topic(query)

    if from_choice:
        # The title came from the list of alternatives, so it is already an
        # exact article name and is read without looking it up again.
        resolved = topic
    else:
        if not topic:
            speak("Tell me what to look up, for example what is python.")
            print("Tell me what to look up, for example what is python.")
            return False
        speak("Searching Wikipedia...")
        resolved = _resolve_article(topic)
        if resolved is None:
            return False

    try:
        text = _wikipedia_extract(resolved)
    except requests.exceptions.RequestException as error:
        print(f"  Wikipedia could not be reached: {error}")
        _wikipedia_offline()
        return False
    except wikipedia.exceptions.DisambiguationError:
        others = _wikipedia_choices(topic)
        if others is None:
            _wikipedia_offline()
            return False
        others = [name for name in others if name.lower() != resolved.lower()]
        if len(others) < 2:
            speak(f"I could not read the article on {resolved}.")
            print(f"  Could not summarise {resolved!r}.")
            return False
        _offer_choices(topic, others)
        return False
    except wikipedia.exceptions.PageError:
        # A title from a search can still turn out to be a redirect that will
        # not read, so the other candidates are tried before giving up.
        alternatives = _wikipedia_choices(topic)
        if alternatives is None:
            _wikipedia_offline()
            return False

        for alternative in alternatives:
            if alternative.lower() == resolved.lower():
                continue
            try:
                text = _wikipedia_extract(alternative)
            except (wikipedia.exceptions.PageError,
                    requests.exceptions.RequestException):
                continue
            resolved = alternative
            break
        else:
            speak(f"I could not find {topic} on Wikipedia.")
            print(f"  No article for {topic!r}.")
            return False

    summary = " ".join(_first_sentences(text, LOOKUP_SENTENCES).split())
    if not summary:
        speak(f"The article on {resolved} has no text to read.")
        print(f"  {resolved!r} has no summary.")
        return False

    # The title is read out before the text, so it is always clear which
    # article the words came from.
    url = f"https://en.wikipedia.org/wiki/{resolved.replace(' ', '_')}"
    spoken = f"{resolved}. {summary}"
    speak(spoken)
    print(spoken)
    print(f"\n  Source: {url}")

    _last_lookup = {
        "topic": topic,
        "title": resolved,
        "summary": summary,
        "url": url,
    }
    return True


def _dispatch(query: str) -> bool:
    """Offers a command to each handler in turn.

    Returns True when the session should end.
    """
    global MUTED

    if confirm_pending(query):
        return False

    if open_folder(query):
        return False

    if play_media(query):
        return False

    if open_document(query):
        return False

    if open_app(query):
        return False

    # Naming Wikipedia outright outranks the clock, so "wikipedia what is the
    # time" reads about time rather than announcing it.
    if _mentions_lookup(query):
        search_wikipedia(query)
        return False

    if "switch to keyboard" in query or "keyboard mode" in query:
        set_input_mode("keyboard")

    elif "switch to voice" in query or "voice mode" in query:
        set_input_mode("voice")

    elif "be quiet" in query or "stop talking" in query:
        MUTED = True
        print("Okay, I will print my replies instead of speaking them.")

    elif "speak up" in query:
        MUTED = False
        print("I will speak again.")

    elif _asks_for_time(query):
        time()

    elif _asks_for_date(query):
        date()

    elif "open youtube" in query:
        wb.open("youtube.com")

    elif "open google" in query:
        wb.open("google.com")

    elif "change your name" in query:
        set_name()

    elif "screenshot" in query:
        screenshot()
        speak("I've taken screenshot, please check it")

    elif "tell me a joke" in query:
        joke = pyjokes.get_joke()
        speak(joke)
        print(joke)

    elif "shutdown" in query:
        speak("Shutting down the system, goodbye!")
        os.system("shutdown /s /f /t 1")
        return True

    elif "restart" in query:
        speak("Restarting the system, please wait!")
        os.system("shutdown /r /f /t 1")
        return True

    elif "offline" in query or "exit" in query:
        speak("Going offline. Have a good day!")
        return True

    else:
        # Nothing here claimed it, so it was a question all along. Being
        # asked about something Jarvis does not know is far more likely than
        # being an instruction it misheard.
        if _is_a_reply(query):
            speak("Tell me what to look up, or give me a command.")
            print("  Ask me something, or give me a command.")
        else:
            search_wikipedia(query)

    return False


def handle_command(query: str) -> dict:
    """Runs one command and reports what happened, for any front end.

    Nothing is printed here: the reply text, the printed lines, the numbered
    results and any file handed to Windows are all returned, so the terminal
    and a browser can present the same command the same way.

    The returned keys are text, parts, lines, results, lookup, opened,
    pending and stop. ``stop`` means the session should end.
    """
    global _last_results, _last_lookup

    _said.clear()
    _opened.clear()
    _last_results = None
    _last_lookup = None

    buffer = io.StringIO()
    stop = False
    with contextlib.redirect_stdout(buffer):
        try:
            stop = _dispatch(query)
        except Exception as error:
            speak(f"Sorry, something went wrong: {error}")
            print(f"Error: {error}")

    return {
        "text": " ".join(_said),
        "parts": list(_said),
        "lines": buffer.getvalue().splitlines(),
        "results": _last_results,
        "lookup": _last_lookup,
        "opened": list(_opened),
        "pending": None if _pending is None else {
            "count": len(_pending),
            "action": _pending_action,
        },
        "stop": stop,
    }


def cli() -> None:
    """Runs the assistant in the terminal until the user leaves."""
    choose_input_mode()
    wishme()

    while True:
        query = get_command()
        if not query:
            continue

        result = handle_command(query)
        for line in result["lines"]:
            print(line)

        if result["stop"]:
            break


if __name__ == "__main__":
    cli()

"""The values Jarvis uses when nothing has been configured.

Kept apart from the code that reads configuration so that a default is a plain
value anyone can read, rather than something produced by a parser.
"""

from __future__ import annotations

# ---------------------------------------------------------------- identity
ASSISTANT_NAME = "Jarvis"
USER_NAME = ""

# -------------------------------------------------------------------- voice
VOICE_ENABLED = True
VOICE_INDEX = 1
VOICE_RATE = 150
VOICE_VOLUME = 1.0
# "en-in" hears Indian English best, which is who this project was written for.
RECOGNITION_LANGUAGE = "en-in"
LISTEN_TIMEOUT = 5
AMBIENCE_TIMEOUT = 1.0
INPUT_MODE = "voice"
WAKE_WORD_ENABLED = False
WAKE_WORD = "jarvis"

# ---------------------------------------------------------------------- ai
AI_PROVIDER = ""
AI_MODEL = ""
AI_API_KEY = ""
AI_BASE_URL = "https://api.openai.com/v1"
GOOGLE_API_KEY = ""
AI_TIMEOUT = 30.0
AI_MAX_TOKENS = 800
# How much of the conversation is sent to a provider. Bounded on purpose: an
# unbounded history is both slow and expensive, and the assistant only needs
# enough to resolve "it" and "when was he born".
AI_HISTORY_TURNS = 12
AI_HISTORY_CHARS = 4000
AI_ENABLED = True

# ------------------------------------------------------------------- memory
MEMORY_ENABLED = True
MEMORY_DIR = "data"
MEMORY_MAX_FACTS = 500

# ------------------------------------------------------------------- safety
CONFIRM_DANGEROUS_ACTIONS = True
# Always on. Turning this off would let the assistant delete files or shut down
# Windows on its own, so it is not a setting.
REQUIRE_CONFIRMATION_FOR_MEDIUM_RISK = False
PROTECTED_DIRECTORIES = (
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "System Volume Information",
    "$Recycle.Bin",
    "Recovery",
)

# ----------------------------------------------------------------- browser
HOST = "127.0.0.1"
PORT = 8765
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
MAX_RECORDING_SECONDS = 12

# --------------------------------------------------------------------- web
LOOKUP_TIMEOUT = 10
WEB_USER_AGENT = "JarvisDesktopAssistant/2.0"
READ_CHAR_LIMIT = 1200
RESULTS_PAGE_SIZE = 200

# ------------------------------------------------------------------ logging
LOG_LEVEL = "INFO"
LOG_FILE = ""

# --------------------------------------------------------------- automation
AUTOMATION_ENABLED = False

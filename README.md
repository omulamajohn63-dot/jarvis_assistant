# Jarvis

**An intelligent personal desktop assistant for Windows.**

Jarvis searches and opens your files, controls your applications, reads your
documents, answers questions, plays media, takes screenshots, remembers what you
ask it to, and can be given a reasoning model so it understands what you actually
meant rather than matching a phrase.

Everything it does goes through a safety layer. Anything that changes Windows —
shutting it down, restarting it, deleting a file — asks first, and the answer must
match the question that was asked.

---

## Table of contents

- [What it does](#what-it-does)
- [Install](#install)
- [Run it](#run-it)
- [Configuration](#configuration)
- [Using an AI provider](#using-an-ai-provider)
- [Voice](#voice)
- [The dashboard](#the-dashboard)
- [Memory](#memory)
- [Safety](#safety)
- [Architecture](#architecture)
- [Adding a skill](#adding-a-skill)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Licence](#licence)

---

## What it does

| Say | Jarvis does |
| --- | --- |
| `what is the time` / `what is the date` | tells you, in a sentence |
| `open chrome`, `launch notepad`, `start calculator` | starts an installed app |
| `open downloads`, `open the music folder`, `open i:` | opens a folder or a drive |
| `open youtube`, `open github`, `search google for python` | opens a website |
| `open my cv`, `launch the syllabus` | finds a document and opens it |
| `read my cv`, `read aloud the syllabus` | reads the opening of it out loud |
| `play oh jah`, `watch blues brothers` | plays a song or a video |
| `screenshot`, `save it as invoice.png` | takes a screenshot |
| `tell me a joke`, `hello`, `what can you do` | chats |
| `open downloads and open documents` | does both, in order |
| `who is einstein`, `why is the sky blue` | looks the question up, or asks a model |
| `who is einstein on wikipedia`, `wikipedia for mercury` | goes straight to Wikipedia |
| `tell me about mercury` | offers a numbered list when the name means several things |
| `remember my browser is Chrome` | remembers it between sessions |
| `what do you remember about me` | tells you, without judgement |
| `forget that`, `clear my memory` | forgets |
| `switch to keyboard mode` / `switch to voice mode` | changes how you talk to it |
| `be quiet` / `speak up` | stops or resumes speaking |
| `shutdown` / `restart` | **asks first** |
| `exit`, `quit`, `goodbye` | ends the session, leaves Windows alone |

**Matching is forgiving.** `please open chrome`, `hey jarvis open chrome`,
`open the chrome` and `play collo blue top shotta` all work. So does
`open my cv` when the file is called `CV Final.pdf`.

**Choosing from a list works by number or by word.** After `open my cv` you can
say `2`, `the second one`, `the last one` or `the 2nd one`. When nothing is
obviously what you meant, Jarvis asks rather than opening the wrong file — and a
number that is not on the list, or a word that names no position, opens nothing
at all.

**It also searches every other drive.** Your normal folders first, then every
other drive all the way down, so a flash disk or external hard drive works without
being told about it. Those folders are indexed once and kept, so only the first
question is slow.

---

## Install

Python 3.13 or newer.

```bash
git clone https://github.com/omulamajohn63-dot/jarvis_assistant.git
cd jarvis_assistant

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

Then run it:

```bash
python -m jarvis2
```

Speech recognition needs the `aifc` and `audioop` modules, which were removed
from the standard library in Python 3.13. Installing `SpeechRecognition>=3.12`
pulls in the maintained `standard-aifc` and `audioop-lts` backports for you.

Reading documents aloud uses `pypdf`, `python-docx`, `openpyxl` and
`python-pptx`. All installed with everything else. Jarvis starts fine without
them: it just says it cannot read that format.

The `.doc`, `.xls` and `.ppt` formats are the ones it cannot read, because they
predate the formats those libraries understand. It says so and opens the file
instead, which is more use than silence.

---

## Run it

```bash
python -m jarvis2                      # asks voice or keyboard
python -m jarvis2 --keyboard           # straight to keyboard
python -m jarvis2 --voice              # straight to voice
python -m jarvis2 "what is the time"   # ask one thing, then leave
python -m jarvis2 --browser            # the dashboard
```

| Flag | Effect |
| --- | --- |
| `--keyboard` | start in keyboard mode |
| `--voice` | start in voice mode |
| `--browser` | start the dashboard instead of the terminal |
| `--host`, `--port` | change where the dashboard listens |
| `--ai` | override the provider: `mock`, `openai`, `gemini` |

With no flag, Jarvis takes input from the keyboard and keeps listening for its own
name if you turn the wake word on. Either `--keyboard` or `--voice` pins the mode
for the whole session; with neither, saying `switch to voice mode` takes effect on
your next command.

---

## Configuration

Copy the example file and edit it. Nothing in it is required.

```bash
copy .env.example .env
```

`.env` is already in `.gitignore`, so nothing in it will ever be committed.

| Variable | What it does |
| --- | --- |
| `AI_PROVIDER` | `openai`, `gemini`, or empty to run offline |
| `AI_MODEL` | the model name |
| `AI_API_KEY` | your key, for OpenAI and compatible services |
| `GOOGLE_API_KEY` | your key, for Gemini |
| `AI_BASE_URL` | change this to point at Ollama or LM Studio |
| `GOOGLE_SPEECH_API_KEY` | optional, for better speech recognition |
| `JARVIS_NAME` | what to call it |
| `VOICE_ENABLED` | `false` to print replies instead of speaking them |
| `VOICE_INDEX`, `VOICE_RATE`, `VOICE_VOLUME` | which voice, how fast, how loud |
| `WAKE_WORD_ENABLED` | `true` to listen for its name |
| `WAKE_WORD` | what it answers to |
| `INPUT_MODE` | `voice` or `keyboard` |
| `MEMORY_ENABLED` | `false` to remember nothing |
| `MEMORY_MAX_FACTS` | how many facts to keep |
| `CONFIRM_DANGEROUS_ACTIONS` | leave this on |
| `AUTOMATION_ENABLED` | allow the fixed step list |
| `HOST`, `PORT` | where the dashboard listens |
| `MAX_RECORDING_SECONDS` | the microphone's cap |
| `LOOKUP_TIMEOUT` | how long a Wikipedia lookup may take |
| `LOG_LEVEL`, `LOG_FILE` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

A shell variable beats the file for one run:

```bash
set PORT=9000
python -m jarvis2 --browser
```

---

## Using an AI provider

With no provider set, Jarvis is a command assistant: every command above works,
and a question is looked up on Wikipedia. That is offline mode, and it is a
supported way to use it.

With a provider set, Jarvis also reasons about what you meant.

**OpenAI, or anything that speaks the same API** — OpenAI, Ollama, LM Studio,
vLLM, Together, Groq:

```env
AI_PROVIDER=openai
AI_MODEL=gpt-4o-mini
AI_API_KEY=sk-...
```

**Google Gemini:**

```env
AI_PROVIDER=gemini
AI_MODEL=gemini-2.0-flash
GOOGLE_API_KEY=AIza...
```

**A model on this machine, with Ollama:**

```env
AI_PROVIDER=openai
AI_MODEL=llama3.1
AI_BASE_URL=http://localhost:11434/v1
```

No key is needed for a local server, and none is sent.

### What the model is allowed to do

The model can choose between skills and answer questions. That is all. For
everything else:

- It never runs code. There is no tool for it, and asking for one is refused.
- Every tool call is checked against the skill registry before it runs. A tool
  that is not registered is refused by name, not matched to the nearest thing.
- Arguments are validated against the skill's own schema.
- A tool that needs confirmation gets one, exactly as the same action would if you
  typed it.
- If the provider is unreachable, Jarvis says so and carries on with the commands.
  Nothing is lost but the chat.

### Adding another provider

Write a class with `available()` and `generate()`:

```python
from jarvis2.ai.provider import AIResponse, ProviderUnavailable

class MyProvider:
    name = "mine"

    async def available(self) -> bool:
        return bool(self.key)

    async def generate(self, messages, tools=None, temperature=0.2):
        if not await self.available():
            raise ProviderUnavailable("no key")
        return AIResponse(text="...", provider=self.name)
```

Then add it to `build_from_settings` in
`jarvis2/ai/providers/openai_compatible.py`. Nothing else in the codebase needs to
know. The `openai` and `google-genai` SDKs are deliberately not used, so what
Jarvis sends is visible in the source.

---

## Voice

Voice is the original way to talk to Jarvis, and it is not the only way.

- **Push to talk** in the dashboard, or speak normally in the terminal.
- **Wake word.** Set `WAKE_WORD_ENABLED=true`. Off by default: an always-listening
  microphone is a privacy cost and a dependency. If it cannot start, push to talk
  still works and Jarvis says why.
- **Keyboard** is always available and is never a fallback failure.

Recognised intents are whole phrases, not words found anywhere in a sentence.
`how do I restart Windows safely` is a question and is looked up; `restart` is a
command and asks first. The same rule protects the search: `how do i restart
windows safely` never becomes a Wikipedia article about restarting.

---

## The dashboard

```bash
python -m jarvis2 --browser
```

Prints a local address and opens your browser. It has:

- **A transcript** with a typing indicator, and a click-to-finish on any reply.
- **Hold to talk**, with a live level meter and a cap you can set.
- **Clickable results**, numbered and grouped by drive and folder.
- **Five views** switched from the sidebar: Assistant, Activity, Memory, Skills and
  Settings. All one page, so a confirmation never costs a page transition.
- **Activity**: every event, with its tool, timing and whether it worked.
- **Skills**: every registered capability with its risk, plus the automation steps.
- **Memory**: read, add to and erase.
- **Settings**: voice, wake word, memory and confirmation toggles.

A numbered list is drawn inside the message that asked the question, not in a
panel of its own, so a list of articles and a list of files both appear where you
expected them.

It binds to `127.0.0.1` and refuses any request that did not come from this
machine, so your Wi-Fi and the internet cannot reach it.

Replies are rendered to audio and played by the page, so your PC speakers stay
quiet.

---

## Memory

Nothing is stored unless you ask for it.

```
You: remember my browser is Chrome
You: what do you remember about me?
Jarvis: I remember: Chrome.
You: forget that
```

Some things are refused outright, and Jarvis says why:

- passwords, API keys, tokens, private keys
- credit card numbers, national ids, dates of birth
- email addresses and phone numbers

```
You: remember my password is hunter2
Jarvis: I will not remember that one, because it looks like a password.
```

Also available: `clear my memory`, `disable memory`, and a memory panel in the
dashboard. The file is `data/memory.json`, plain JSON you can read or delete.

---

## Safety

The rule the whole project rests on:

> A language model may suggest an action. Nothing else may.

```
AI suggestion → validation → safety policy → permission → confirmation → execution → real result
```

### Three levels of risk

Every action is in a table, and the table is not the only thing protecting you:
an action nobody declared is treated as **high**, because guessing low would mean
trusting a new skill by default.

| Level | Examples | What happens |
| --- | --- | --- |
| **Low** | tell the time, open a website, search files, read a document, open an app, take a screenshot | runs straight away |
| **Medium** | move a file, rename a file, copy a file, close an app, play media, change a setting | runs, and can be made to ask |
| **High** | delete a file or folder, empty the Recycle Bin, shut down, restart, log off, erase a drive, edit the registry, change a security setting | **always asks** |

Confirming a high risk action is not a setting. Turning it off would be a setting
that let one mistaken answer shut down a computer, so `needs_confirmation` returns
True for HIGH whatever the configuration says.

### What is refused outright

- **Running shell commands.** There is no tool for it and no route to one. A
  command runner a model can reach is the hole everything else exists to close.
- **System directories.** `C:\Windows`, `Program Files`, `System32`,
  `ProgramData`, the Recycle Bin.
- **Programs disguised as documents.** A `.exe`, `.bat`, `.ps1` or `.lnk` is
  never a "document", whether or not it exists yet.
- **Directories as delete targets.** Deleting `Documents\cv.pdf` is ordinary.
  Deleting `Documents` is not.
- **Invented skills.** A tool call for something not registered is refused by
  name.

### Confirmation is real

```
You: shutdown
Jarvis: Shut down Windows now? Anything you have not saved will be lost.
        Type yes to go ahead:
You: no
Jarvis: Okay, I will not do that.
```

In the browser it is a card with **yes** and **no**. Three things make it
reliable:

- **The word alone is not enough.** Only a whole recognised phrasing triggers it.
  Asking how to restart safely never restarts anything.
- **The answer must match the question.** Each confirmation carries an id, and only
  that id approves it, so an old dialog cannot approve whatever is waiting now, and
  one click cannot do it twice.
- **No shell is involved.** Windows is asked with a fixed argument list, so no part
  of your sentence can become a second command.

### The dashboard is local

Loopback only, and non-loopback requests are refused before they are looked at. A
request that stops being answered comes back as a failure with a real message
rather than a page that spins for ever. Keys go in headers, never in a URL, and
are redacted out of every log line.

---

## Architecture

```
                   ┌──────────────────────┐
                   │       USER           │
                   └──────────┬───────────┘
                              │
                Voice / Text / Browser
                              │
                              ▼
                   ┌──────────────────────┐
                   │    JARVIS CORE       │
                   │ context · state      │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  ROUTER → AI → PLAN  │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │    SAFETY / POLICY   │
                   └──────────┬───────────┘
                              │
                              ▼
             ┌────────────────────────────────┐
             │        SKILL REGISTRY         │
             └───────┬────┬────┬────┬────────┘
                     │    │    │    │
              Apps  Files  Docs  Web  System
                     │    │    │    │
                     └────┴────┴────┘
                              │
                              ▼
                     REAL WORLD RESULT
                              │
                              ▼
                       JARVIS RESPONSE
```

### The layout

```
jarvis2/
├── core/
│   ├── assistant.py      the one entry point every interface uses
│   ├── models.py         Request, Response, SkillResult, Choice
│   ├── router.py         what should handle this
│   ├── conversation.py   bounded history, references, ordinals
│   ├── memory.py         what is worth keeping between sessions
│   ├── events.py         the event bus
│   └── runtime.py        the loop that owns the assistant
├── skills/
│   ├── base.py           the Skill interface
│   ├── registry.py       choosing between skills
│   ├── files.py          files, folders, documents, media
│   ├── apps.py           applications, websites, screenshots
│   ├── system.py         clock, power, session, speaker, mode
│   ├── conversation.py   greetings, memory, recall
│   ├── knowledge.py      Wikipedia
│   └── ...               16 skills in all
├── files/                finding and reading files
│   ├── search.py         spoken name → every file it could mean
│   ├── documents.py      text out of pdf, docx, xlsx, pptx, rtf
│   ├── drives.py         which other drives exist
│   └── text.py           speech → something comparable
├── knowledge/
│   └── wiki.py           looking a name up, and asking when it means several
├── ai/
│   ├── provider.py       the provider seam
│   ├── prompts.py        what the model is told
│   ├── planner.py        multi-step tasks
│   ├── response.py       running what the model asked for
│   └── providers/        mock, OpenAI-compatible, Gemini
├── safety/
│   ├── policy.py         how risky is this
│   ├── paths.py          is this a real path somewhere sensible
│   ├── permissions.py    is this installation allowed
│   └── confirmations.py  has the user answered
├── voice/                input, output, wake word
├── automation/           allowlisted steps, no shell
└── config/               settings and defaults

web/                      the dashboard
├── app.py                the app, and the loop that answers it
├── api/routes.py         every endpoint
├── templates/index.html
└── static/{app.js, styles.css}

data/                     the memory file, plain JSON you can read
tests/v2/                 the test suite
```

### The pipeline

```
handle_input
  → normalise            lower case, tidy whitespace
  → context              what is being talked about
  → route                a waiting answer, a skill, the model, or a lookup
  → plan                 several actions, checked before any of them run
  → safety               classify, validate, confirm
  → skill                execute
  → result               real result, or an honest failure
  → response             text, status, what was opened, where it came from
```

Each step falls back to the one before it failed. That is what makes the assistant
still useful with no model, and what keeps every command working whether or not
anything was rewritten.

A lookup is the last resort, not the default. A request with no subject to look up
is turned away before the network is touched, which is why `clear my memory` gets
an honest answer rather than an article about clearing memory.

### Concurrency

Every skill is `async`. Everything slow — scanning a drive, reading a document,
rendering speech, calling a provider, handing a path to Windows — runs off the
event loop, so the dashboard never waits on any of it.

The assistant owns one event loop on one thread. Flask is started outside it, and
every handler reaches the assistant through that loop, which is what lets
`python -m jarvis2 --browser` work even though a WSGI server may call a handler
from inside a loop of its own.

The file indexes are shared and kept, because a scan of a real home folder costs
seconds. They resolve their folders when they are first used rather than at import
time, so pointing Jarvis at a different home actually changes what it searches.

### Events

Everything interesting is published on one bus, so logging, the dashboard and any
future integration all watch the same stream without being wired in:

`user_input`, `skill_selected`, `tool_started`, `tool_completed`, `tool_failed`,
`confirmation_required`, `confirmation_resolved`, `plan_started`, `plan_step`,
`plan_finished`, `assistant_response`, `error`.

---

## Adding a skill

One class and one line. Nothing else changes.

```python
# jarvis2/skills/weather.py
from jarvis2.core.models import Request, SkillResult
from jarvis2.skills.base import Skill, SkillContext


class WeatherSkill(Skill):
    name = "weather"
    description = "Tell the weather for a named place."
    actions = ()                      # safety actions it performs
    keywords = ("weather", "forecast", "temperature", "rain")

    async def can_handle(self, request: Request) -> float:
        """0.0 to 1.0. A number, so a router can choose between two that fit."""
        for word in self.keywords:
            if word in request.normalized:
                return 0.8
        return 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        place = request.normalized.replace("what is the weather in", "").strip()
        if not place:
            return SkillResult(succeeded=True, text="Where should I look?")

        # Blocking work goes through here so the loop stays free.
        report = await context.run_blocking(self._fetch, place)

        return SkillResult(
            succeeded=True,
            text=f"It is {report} in {place}.",
            sources=[{"title": f"Weather for {place}", "kind": "web"}],
        )
```

Register it:

```python
# jarvis2/skills/__init__.py
from jarvis2.skills.weather import WeatherSkill

def build_default_registry(permissions=None, wikipedia=None):
    return SkillRegistry(
        [..., WeatherSkill()],
        permissions=permissions,
    )
```

That is the whole change. The dashboard gains the skill in **what it can do**, the
model is told about it automatically, and it appears in `GET /api/skills`, because
all three are generated from the class rather than written out.

If your skill offers a numbered list, say what picking an entry should do:

```python
return SkillResult(
    succeeded=True,
    text="Which one?",
    choices=choices,
    action="open",     # "open", "read" or "lookup"
)
```

That one field is what stops `1` after a list of articles being sent looking for
a file called `Mercury (planet)`.

Three rules:

- `succeeded` must come from what actually happened. Nothing downstream is allowed to
  infer it from the fact that the skill ran.
- Anything in `actions` is checked against the permission set when the skill is
  registered, so a skill for a refused action fails to start rather than failing
  later. An action you invent without adding it to the policy table counts as high
  risk.
- Do not add a comment saying a path is safe. Check it with
  `jarvis2.safety.paths`.

Then test it:

```python
async def test_the_weather(context):
    skill = build_default_registry().get("weather")
    result = await skill.execute(
        Request(text="what is the weather in paris"), context
    )
    assert result.succeeded
```

---

## Development

```bash
pip install -r requirements-dev.txt
pytest                                       # the whole suite
pytest tests/v2/test_safety_layer.py -v      # the one that matters most
pytest tests/v2/test_choices.py -v           # and refusing to guess
pytest tests/v2/test_live_server.py          # slow: starts a real server
```

| File | What it covers |
| --- | --- |
| `tests/v2/test_safety_layer.py` | risk, paths, permissions, confirmations |
| `tests/v2/test_choices.py` | picking from a numbered list, and refusing to guess |
| `tests/v2/test_search.py` | matching a spoken name to a file |
| `tests/v2/test_results_view.py` | what a result list says and in what order |
| `tests/v2/test_documents_read.py` | getting text out of a document, honestly |
| `tests/v2/test_words.py` | turning speech into something comparable |
| `tests/v2/test_asking_for_things.py` | asking for a file, folder, app or site |
| `tests/v2/test_skills.py` | skills and the registry |
| `tests/v2/test_ai.py` | providers, prompts, tool validation |
| `tests/v2/test_memory.py` | what is stored and what is refused |
| `tests/v2/test_planner.py` | multi-step tasks |
| `tests/v2/test_end_to_end.py` | the whole pipeline |
| `tests/v2/test_web.py` | the dashboard's endpoints |
| `tests/v2/test_payloads.py` | the exact shape a page is written against |
| `tests/v2/test_settings.py` | configuration and secret handling |
| `tests/v2/test_runtime.py` | the assistant's loop |
| `tests/v2/test_live_server.py` | the real entry point, over a real socket |

### What the tests will not do

No test touches the network, launches anything, opens a window, takes a screenshot,
scans a real drive, plays audio, renames the real assistant, writes to your real
memory file, or **restarts or shuts down this machine**.

That last one matters: a test that approves a confirmation would run
`shutdown /s /f /t 1` for real, because that is what approving means. So
`tests/v2/conftest.py` replaces `subprocess.run` with a recorder for every test. If
you add a test that runs a power command, it is recorded rather than executed.

The shared file indexes are emptied between tests by the same file, so a test never
searches the temporary folder of whichever test ran before it.

### Before a pull request

```bash
pytest
python -m jarvis2 "what is the time"
python -m jarvis2 --keyboard        # by hand
python -m jarvis2 --browser         # and open the page
```

### Known flaky

`tests/v2/test_live_server.py` starts a real server and talks to it over a real
socket, and on some Windows machines it intermittently times out on a request the
server's own log shows it answered. It reuses one pooled connection and restarts
the server if a run fails, which makes it rare rather than impossible. A failure
there prints the server's log, which is the first thing to read.

---

## Troubleshooting

**It will not start.**
`pip install -r requirements.txt` inside your virtual environment. Check with
`.venv\Scripts\python.exe -m pip list`.

**It speaks but I hear nothing.**
`VOICE_ENABLED` must not be `false`. In the dashboard the page plays the audio
itself, so use the page's sound button rather than the PC's.

**It did not understand me.**
Use `--keyboard` and check the transcript. If the microphone is the problem,
`speech_recognition` needs `GOOGLE_SPEECH_API_KEY` for reliable results, and the
public key it ships with is revoked by Google from time to time.

**"I could not find an application called X."**
The name has to match something installed. Try the name as it appears in the Start
menu, or the name of the executable: `calculator` is `calc.exe`.

**"I could not find a document called X."**
Documents are searched in Downloads, Music, Videos, Desktop, Pictures and
Documents, then every other drive. The first search of a session is slow while the
folders are indexed.

**"I could not find a folder called X."**
The folder has to exist. Jarvis will not invent one, and it will not open a drive
letter that is not there.

**"I do not know how to do that yet."**
Either no skill claimed it, or it was a question with no subject to look up. Ask
it as a question — `who is X`, `what is X`, `tell me about X` — or name Wikipedia
directly.

**A website did not open.**
The dashboard is bound to `127.0.0.1`. Changing `HOST` puts it on your network, so
only do that if you understand that.

**"I could not reach the AI service."**
Expected, and not a failure. Jarvis carries on with the commands. Check
`AI_PROVIDER`, the model name and the key. For Gemini the key goes in
`GOOGLE_API_KEY`, not `AI_API_KEY`.

**It will not remember something.**
Some things are refused on purpose. Ask `what do you remember about me` to see what
it has.

**The dashboard will not start on that port.**
Something else has it. Set `PORT` in `.env`.

**A command did nothing.**
Something may be waiting for an answer. Say `no` or `cancel` to clear it.

---

## Project layout and history

The assistant is `jarvis2/`, its dashboard is `web/`, and its tests are
`tests/v2/`. The first version's file searching, document reading and Wikipedia
code were rewritten as native modules under `jarvis2/files/` and
`jarvis2/knowledge/`, and the older assistant was removed. The behaviour it had is
still pinned by tests, written against the new code.

## Licence

MIT. See [LICENSE](LICENSE).

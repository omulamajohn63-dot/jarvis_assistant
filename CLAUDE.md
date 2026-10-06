# Jarvis

An intelligent personal desktop assistant for Windows. Voice, text and a browser
dashboard all go through one core; every action passes a safety layer that
refuses rather than guesses.

## The one thing that matters

```
AI suggestion → validation → safety policy → permission → confirmation → execution → real result
```

A language model may suggest an action. Nothing else may. If you are changing
anything in `jarvis2/safety/`, `jarvis2/ai/response.py`, or anything that
executes a command, that chain is the thing you are changing.

## Running it

```bash
pip install -r requirements-dev.txt
pytest                            # ~900 tests, ~3 minutes
python -m jarvis2                 # terminal
python -m jarvis2 --browser       # dashboard
```

## Rules that are not negotiable

- **No shell.** There is no tool for running a command and no route to one. A
  command runner a model can reach is the hole everything else exists to close.
- **Confirming high risk actions is not a setting.** `policy.needs_confirmation`
  returns True for HIGH whatever the configuration says. Do not add a flag for
  it.
- **A tool call goes through the same path as a typed command**, so it gets the
  same confirmation. `JarvisAssistant.run_tool` is the only path a model has.
- **`succeeded` comes from what happened**, never from the fact that a skill
  ran. Saying a file was opened when it was not is the worst thing this
  assistant can do.
- **A file path from a model is a suggestion.** Resolve it with
  `jarvis2.safety.paths` before touching anything.
- **No secrets in a log.** `logging_utils.redact` handles this at the boundary
  so no call site has to remember.

## Where things are

| Working on | Look in |
| --- | --- |
| a new capability | `jarvis2/skills/` — one class, one registration line |
| what the model is told | `jarvis2/ai/prompts.py` |
| which provider is used | `jarvis2/ai/providers/` |
| how risky something is | `jarvis2/safety/policy.py` |
| whether a path is allowed | `jarvis2/safety/paths.py` |
| finding a file by name | `jarvis2/files/search.py` |
| reading a document | `jarvis2/files/documents.py` |
| answering a question | `jarvis2/knowledge/wiki.py` |
| the dashboard's endpoints | `web/api/routes.py` |
| the browser side | `web/static/app.js` |

## Things that will bite you

- **`jarvis2/core/__init__.py` imports the assistant lazily.** A skill imports
  `core.models`, which pulls in that package, which would then import the
  assistant, which imports the skills. The lazy `__getattr__` is what stops the
  three deadlocking on each other.
- **A skill that offers a numbered list says what its entries are for.**
  `SkillResult.action` is "open", "read" or "lookup", and `_run_choice` reads it
  before touching the filesystem. Guessing there sends "1" after a list of
  articles looking for a file called "Mercury (planet)".
- **The file indexes in `jarvis2/files/search.py` are shared and kept**, because
  a scan of a real home folder costs seconds. They resolve their roots through a
  callable, not at import time, so `clear_caches()` is what a test needs.
- **`Settings` is frozen and validates in `__post_init__`.** A nonsense value
  is an error at the point it is set, not a strange behaviour later.
- **`tests/v2/conftest.py` replaces `subprocess.run` with a recorder for every
  test**, because approving a shutdown confirmation would otherwise reboot the
  machine the tests are running on.
- **`tests/v2/test_safety_layer.py` is the file that matters most.** It is what
  stops a clever change from making Jarvis do something nobody asked for. Read
  it before changing the safety layer.
- **`tests/v2/test_choices.py` is the other one.** Refusing to guess which file
  was meant is most of what this assistant is for.
- **A knowledge lookup must never be the default route.** A request with no
  subject to look up is turned away before the network is touched, or "how do i
  restart windows safely" is answered with an article about restarting.

## Style

- Type hints, dataclasses, small functions, no global mutable state.
- Comments explain *why*, not *what*. The existing code is the reference: if a
  comment could be deleted without anyone noticing, delete it.
- No comments unless they earn their place. Do not write "loop over the skills".
- Prefer raising a clear error to returning a confusing `None`.
- No new dependencies without a reason written in the pull request. `requests`
  is already there; the `openai` and `google-genai` SDKs are deliberately not
  used.
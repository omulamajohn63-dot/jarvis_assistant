"""Running Jarvis in a terminal.

    python -m jarvis2                ask about the input mode
    python -m jarvis2 --keyboard     start straight in keyboard mode
    python -m jarvis2 --voice        start straight in voice mode
    python -m jarvis2 "what is the time"     ask one thing and leave
    python -m jarvis2 --browser      start the dashboard instead
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from jarvis2.core.assistant import build
from jarvis2.core.models import Response, Source, Status
from jarvis2.logging_utils import configure, get_logger

_log = get_logger("cli")


def arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jarvis2",
        description="An intelligent personal desktop assistant.",
    )
    parser.add_argument("--keyboard", action="store_true",
                        help="start in keyboard mode")
    parser.add_argument("--voice", action="store_true",
                        help="start in voice mode")
    parser.add_argument("--browser", action="store_true",
                        help="start the dashboard instead of the terminal")
    parser.add_argument("--host", default=None,
                        help="address for the dashboard")
    parser.add_argument("--port", type=int, default=None,
                        help="port for the dashboard")
    parser.add_argument("--ai", default=None,
                        help="override the AI provider (mock, openai, gemini)")
    parser.add_argument("question", nargs="*",
                        help="ask one thing, then exit")
    return parser.parse_args(argv)


async def say(assistant, response: Response, speak: bool = True) -> None:
    """Shows a reply, and says it when the terminal owns the audio."""
    for choice in response.choices:
        detail = f"  ({choice.detail})" if choice.detail else ""
        print(f"    {choice.number}. {choice.label}{detail}")
        if choice.payload and response.metadata.get("lines"):
            pass

    for line in response.metadata.get("lines") or []:
        if line:
            print(line)

    if response.confirmation is not None:
        print(f"\n  {response.confirmation.prompt}")

    if response.text:
        print(response.text)

    if response.sources:
        for source in response.sources:
            if source.get("url"):
                print(f"  Source: {source['url']}")

    if speak and response.text and assistant.settings.voice_enabled:
        output = getattr(assistant, "speech", None)
        if output is not None:
            await output.say(response.text)


async def confirm_interactively(assistant, question: str) -> bool:
    """Asks a high risk question in the terminal.

    Only here. The dashboard asks in the page, so the question is never asked in
    two places at once, and nothing is ever approved without being shown first.
    """
    try:
        answer = input("  Type yes to go ahead: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    approved = answer in {"yes", "yeah", "yep", "ok", "okay", "sure",
                          "do it", "go ahead"}
    if not approved:
        print("  Canceled. Nothing was changed.")
    return approved


async def run_once(assistant, question: str, speak: bool = True) -> int:
    """Handles one request, following through any confirmation it raises."""
    response = await assistant.handle_input(question, Source.TERMINAL)
    await say(assistant, response, speak)

    if response.confirmation is not None:
        approved = await confirm_interactively(assistant, question)
        response = await assistant.confirm(response.confirmation.id, approved)
        await say(assistant, response, False)

    return 0 if response.ok else 1


async def loop(assistant, mode: str) -> int:
    """Runs until the user leaves."""
    from jarvis2.voice.input import VoiceInput
    from jarvis2.voice.output import SpeechOutput

    assistant.speech = SpeechOutput(assistant.settings)
    assistant.voice_input = VoiceInput(assistant.settings)

    # A flag pins the mode for the whole session. Without one, the mode is read
    # from the settings every turn, so "switch to voice mode" takes effect on
    # the next command rather than at the next restart.
    pinned = mode is not None

    if mode == "voice":
        await _greet(assistant)

    print(f"\n{assistant.settings.assistant_name} is ready. "
          "Type a command, or say 'exit' to leave.\n")

    while True:
        if not pinned:
            mode = assistant.settings.input_mode

        if mode == "voice":
            heard = await assistant.voice_input.listen()
            if not heard.ok:
                print(f"  {heard.reason}")
                if heard.text:
                    pass
                continue
            question = heard.text
            print(f"You: {question}")
        else:
            try:
                question = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question:
                continue

        response = await assistant.handle_input(question, Source.TERMINAL)
        await say(assistant, response)

        if response.confirmation is not None:
            approved = await confirm_interactively(assistant, question)
            response = await assistant.confirm(response.confirmation.id, approved)
            await say(assistant, response, False)

        if response.status is Status.STOP:
            break

    await assistant.close()
    return 0


async def _greet(assistant) -> None:
    from jarvis2.voice.output import SpeechOutput

    output = SpeechOutput(assistant.settings)
    assistant.speech = output

    import datetime

    hour = datetime.datetime.now().hour
    part = (
        "Good morning" if hour < 12
        else "Good afternoon" if hour < 16
        else "Good evening"
    )
    name = assistant.settings.assistant_name
    spoken = f"{part}! {name} at your service. How can I help?"
    await output.say(spoken)
    print(spoken)


def browser_main(argv=None) -> int:
    """Starts the dashboard. Never called from inside an event loop.

    Flask's server owns the thread it runs on. Starting it from inside
    asyncio.run leaves a loop running there, and every request handler then
    fails trying to make one of its own.
    """
    import asyncio

    from web.app import serve

    options = arguments(argv)
    configure("INFO")

    assistant = asyncio.run(build())
    return serve(
        host=options.host, port=options.port, assistant=assistant,
    )


async def main(argv=None) -> int:
    options = arguments(argv)
    configure("INFO")

    assistant = await build()

    if options.ai:
        from jarvis2.ai.providers import MockAIProvider

        assistant.provider = MockAIProvider(responses="")

    mode = "keyboard" if options.keyboard else "voice" if options.voice else None

    if options.question:
        return await run_once(assistant, " ".join(options.question))

    if mode is None:
        mode = await _ask_mode()

    if mode == "voice" and not assistant.settings.voice_enabled:
        print("Voice is switched off, so we will use the keyboard.")
        mode = "keyboard"

    return await loop(assistant, mode)


def _ask_mode() -> str:
    try:
        answer = input("Voice or keyboard? (v/k): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "keyboard"
    return "keyboard" if answer.startswith("k") else "voice"


def cli() -> int:
    """Starts whichever way was asked for.

    The dashboard is started outside asyncio entirely. See browser_main.
    """
    options = arguments()
    try:
        if options.browser:
            return browser_main()

        return asyncio.run(main())
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(cli())

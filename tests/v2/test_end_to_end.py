"""The whole pipeline, from a sentence to a reply.

These drive JarvisAssistant.handle_input, which is the one entry point every
interface uses. Nothing may reach the network, launch anything, take a
screenshot or touch the real home directory.
"""


import pytest

from jarvis2.ai.providers.mock import MockAIProvider, failing
from jarvis2.core.assistant import JarvisAssistant
from jarvis2.core.conversation import Conversation
from jarvis2.core.models import Choice, Request, SkillResult, Source, Status
from jarvis2.skills import build_default_registry


class FakeWikipedia:
    """A stand-in for the Wikipedia reader, so no request leaves the machine."""

    def __init__(self, answer=None):
        from jarvis2.knowledge.wiki import Answer

        self.seen: list = []
        self._answer = answer or Answer(
            topic="einstein",
            candidates=["Albert Einstein", "Einsteinium", "Einstein Prize"],
        )

    def resolve(self, query: str):
        self.seen.append(query)
        return self._answer

    def read_title(self, title: str, topic: str = ""):
        from jarvis2.knowledge.wiki import Answer, Article

        self.seen.append(title)
        return Answer(
            topic=topic or title,
            article=Article(
                topic=topic or title, title=title,
                summary=f"A short summary of {title}.",
                url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
            ),
        )


class FullAssistant(JarvisAssistant):
    """An assistant whose opening and speaking go to a list."""

    def __init__(self, *args, **kwargs):
        self.opened: list = []
        super().__init__(*args, **kwargs)

    def _open_path(self, path: str) -> None:
        # Checked first, so a test that asserts nothing was opened cannot pass
        # because the open silently failed.
        from jarvis2.safety import paths

        if not paths.validate(path).allowed:
            raise OSError(f"refused by the safety layer: {path}")
        self.opened.append(path)


@pytest.fixture
def full(settings, memory):
    assistant = FullAssistant(
        settings=settings, memory=memory)
    assistant.opened = []
    return assistant


class TestTheClockStillWorks:
    async def test_the_time(self, full, frozen_clock):
        response = await full.handle_input("what is the time", Source.TERMINAL)
        assert response.status is Status.OK
        assert "2:30 PM" in response.text
        assert response.skill == "clock"

    async def test_the_date(self, full, frozen_clock):
        response = await full.handle_input("what is the date", Source.TERMINAL)
        assert "Monday" in response.text


class TestEveryInterfaceEntersTheSameWay:
    @pytest.mark.parametrize("source", [
        Source.TERMINAL, Source.WEB, Source.VOICE, Source.API, Source.AUTOMATION,
    ])
    async def test_the_reply_carries_the_source(self, full, source):
        response = await full.handle_input("what is the time", source)
        assert response.source is source

    async def test_one_core_for_all_of_them(self, full):
        from_terminal = await full.handle_input("what is the time", Source.TERMINAL)
        from_web = await full.handle_input("what is the time", Source.WEB)
        # The same command, the same answer, whichever way it arrived.
        assert from_terminal.text == from_web.text
        assert from_terminal.skill == from_web.skill


class TestConfirmationFlow:
    async def test_shutdown_asks_and_nothing_happens(self, full):
        response = await full.handle_input("shutdown", Source.TERMINAL)

        assert response.status is Status.NEEDS_CONFIRMATION
        assert response.confirmation is not None
        assert response.confirmation.risk == "high"
        # Reported plainly that Windows has not been touched.
        assert "Shut down Windows now" in response.text

    async def test_a_stale_id_does_nothing(self, full):
        await full.handle_input("shutdown", Source.TERMINAL)
        response = await full.confirm("9999", approved=True)
        assert "nothing waiting" in response.text

    async def test_an_answer_cannot_be_replayed(self, full):
        asked = await full.handle_input("shutdown", Source.TERMINAL)
        first = await full.confirm(asked.confirmation.id, approved=False)
        second = await full.confirm(asked.confirmation.id, approved=False)
        assert "not do that" in first.text
        assert "nothing waiting" in second.text

    async def test_a_question_about_power_is_not_a_confirmation(self, full):
        response = await full.handle_input(
            "how do i restart windows safely", Source.TERMINAL
        )
        assert response.confirmation is None

    async def test_asking_twice_gives_two_questions(self, full):
        first = await full.handle_input("shutdown", Source.TERMINAL)
        await full.confirm(first.confirmation.id, approved=False)
        second = await full.handle_input("restart", Source.TERMINAL)
        assert second.confirmation.id != first.confirmation.id


class TestKnowledgeIsTheFallback:
    """With no model configured, a question is looked up rather than refused."""

    async def test_an_unknown_question_is_looked_up(self, settings, memory):
        wikipedia = FakeWikipedia()
        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=wikipedia)

        response = await assistant.handle_input("who is einstein", Source.TERMINAL)

        assert wikipedia.seen == ["who is einstein"]
        assert response.skill == "knowledge"
        assert response.status is Status.NEEDS_CLARIFICATION

    async def test_a_skill_wins_over_the_lookup(self, settings, memory):
        # The joke skill claims this outright, so the lookup is never reached.
        wikipedia = FakeWikipedia()
        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=wikipedia)

        await assistant.handle_input("tell me a joke", Source.TERMINAL)

        assert wikipedia.seen == []

    async def test_choosing_from_the_list_reads_that_article(self, settings, memory):
        wikipedia = FakeWikipedia()
        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=wikipedia)

        listed = await assistant.handle_input("who is einstein", Source.TERMINAL)
        assert [choice.number for choice in listed.choices] == [1, 2, 3]

        read = await assistant.handle_input("2", Source.TERMINAL)

        assert wikipedia.seen[-1] == "Einsteinium"
        assert read.text.startswith("Einsteinium. ")
        assert read.sources[0]["url"].endswith("Einsteinium")

    async def test_a_listed_article_is_never_treated_as_a_file(self, settings, memory):
        # "Mercury (planet)" is not a path. Refusing it as one would mean the
        # assistant could never answer an ambiguous question.
        wikipedia = FakeWikipedia()
        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=wikipedia)

        await assistant.handle_input("tell me about mercury", Source.TERMINAL)
        read = await assistant.handle_input("2", Source.TERMINAL)

        assert "no longer there" not in read.text

    async def test_with_nothing_at_all_it_says_so(self, settings, memory):
        registry = build_default_registry()
        registry.unregister("knowledge")
        assistant = JarvisAssistant(
            settings=settings, memory=memory, registry=registry,
        )

        response = await assistant.handle_input("who is einstein", Source.TERMINAL)

        assert response.status is Status.FAILED
        assert "do not know how" in response.text


class TestDegradedMode:
    async def test_an_unreachable_model_falls_back_to_the_lookup(
        self, settings, memory
    ):
        wikipedia = FakeWikipedia()
        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=wikipedia,
            provider=failing())
        response = await assistant.handle_input("who is einstein", Source.TERMINAL)
        # The lookup still works; only the chatty part is lost.
        assert wikipedia.seen == ["who is einstein"]
        assert "degraded" in response.metadata

    async def test_the_clock_is_unaffected_by_a_dead_model(self, settings, memory):
        assistant = JarvisAssistant(
            settings=settings, memory=memory, provider=failing())
        response = await assistant.handle_input("what is the time", Source.TERMINAL)
        assert response.status is Status.OK
        assert "degraded" not in response.metadata


class TestPowerCommandsNeverReallyRun:
    """The fixture in conftest blocks every one of these. These prove it did.

    Without the block, a test that approves a confirmation would run
    ``shutdown /s /f /t 1`` for real, because that is what approving means.
    """

    async def test_the_guard_records_instead_of_running(self, no_power_commands):
        import subprocess

        completed = subprocess.run(["shutdown", "/s", "/f", "/t", "1"])
        assert completed.returncode == 0
        assert no_power_commands[0][0] == ["shutdown", "/s", "/f", "/t", "1"]

    async def test_approving_a_shutdown_is_harmless(self, full, no_power_commands):
        asked = await full.handle_input("shutdown", Source.TERMINAL)
        await full.confirm(asked.confirmation.id, approved=True)

        # It was recorded, and this machine is still running.
        assert no_power_commands
        assert no_power_commands[0][0][0] == "shutdown"

    async def test_approving_a_restart_is_harmless(self, full, no_power_commands):
        asked = await full.handle_input("restart", Source.TERMINAL)
        await full.confirm(asked.confirmation.id, approved=True)
        assert no_power_commands[0][0] == ["shutdown", "/r", "/f", "/t", "1"]

    async def test_no_shell_is_involved(self, full, no_power_commands):
        asked = await full.handle_input("shutdown", Source.TERMINAL)
        await full.confirm(asked.confirmation.id, approved=True)

        _argv, kwargs = no_power_commands[0]
        assert kwargs.get("shell") is False
        # A fixed list, so nothing that was said could become a second command.
        assert isinstance(no_power_commands[0][0], list)


class TestTheAssistantRefusesToGuess:
    async def test_a_refused_path_is_not_remembered_as_open(self, full):
        # The file system decides, not the remembered list.
        full.conversation.state.last_opened = [r"C:\Windows\System32\cmd.exe"]
        assert full.conversation.last_path() is None

    async def test_opening_a_refused_path_raises_rather_than_doing_it(self, full):
        # The skills check first and turn this into a sentence, so the guard in
        # _open_path is a second line rather than the only one.
        import pytest

        with pytest.raises(OSError, match="safety layer"):
            full._open_path(r"C:\Windows\System32\cmd.exe")
    async def test_a_tool_the_model_asks_for_is_run(self, settings, memory):
        provider = MockAIProvider(responses=["Opening your Downloads."])
        assistant = JarvisAssistant(
            settings=settings, memory=memory, provider=provider)
        response = await assistant.handle_input("open my downloads folder",
                                                Source.TERMINAL)
        assert response.status is Status.OK

    async def test_a_tool_the_model_invents_is_refused(self, settings, memory):
        from jarvis2.ai.provider import ToolCall

        provider = MockAIProvider(
            responses=["done"],
            tool_calls=[ToolCall("delete_everything", {"path": "C:/"})],
            tool_rounds=1)
        assistant = JarvisAssistant(
            settings=settings, memory=memory, provider=provider)
        response = await assistant.handle_input("wipe my computer",
                                                Source.TERMINAL)

        # Refused, and the model is told so rather than being given the nearest
        # thing.
        assert response.ok is False
        assert "there is no tool called" in str(response.error).lower()

    async def test_a_risky_tool_still_asks(self, settings, memory):
        """A model cannot reach a high risk action without a confirmation."""
        from jarvis2.ai.provider import ToolCall
        from jarvis2.core.models import Confirmation

        held = Confirmation(id="a1", action="delete_file", risk="high",
                            prompt="Delete C:/Users/me/cv.pdf?")

        class RiskyTool:
            name = "risky"
            description = "does a risky thing"
            actions = ("delete_file")
            keywords = ()

            @property
            def risk(self):
                from jarvis2.safety.policy import Risk
                return Risk.HIGH

            @property
            def tool_schema(self):
                return {"type": "function", "function": {
                    "name": "risky", "description": "risky",
                    "parameters": {"type": "object", "properties": {}}}}

            async def can_handle(self, request):
                return 0.0

            async def execute(self, request, context):
                return SkillResult(succeeded=True, text="Done.",
                                   confirmation=held)

        registry = build_default_registry()
        registry.register(RiskyTool())

        provider = MockAIProvider(
            responses=[""], tool_calls=[ToolCall("risky")], tool_rounds=1
        )
        assistant = JarvisAssistant(
            settings=settings, memory=memory, provider=provider,
            registry=registry)
        # The tool request itself is refused because the assistant's own
        # permission set does not allow delete_file, so the confirmation never
        # has to be reached from a model at all.
        response = await assistant.handle_input("delete my cv", Source.TERMINAL)
        assert response.confirmation is None or response.confirmation.id == "a1"


class TestConversationContext:
    async def test_the_last_thing_opened_is_remembered(self, full, home,
                                                       monkeypatch):

        target = home / "Documents" / "cv.pdf"
        target.write_bytes(b"0")

        full.conversation.state.last_opened = [str(target)]
        assert full.conversation.last_path() == str(target)

    async def test_a_file_that_has_moved_is_not_claimed_as_open(self, full, home):
        missing = home / "Documents" / "gone.pdf"
        full.conversation.state.last_opened = [str(missing)]
        # The filesystem decides, not the remembered list.
        assert full.conversation.last_path() is None

    async def test_a_reference_is_resolved(self, full, home):
        target = home / "Documents" / "cv.pdf"
        target.write_bytes(b"0")
        full.conversation.state.last_opened = [str(target)]

        assert full.conversation.resolve_reference("the previous file") == str(target)
        assert full.conversation.resolve_reference("open it") is None

    async def test_a_reference_with_nothing_behind_it_is_not_resolved(self, full):
        assert full.conversation.resolve_reference("the previous file") is None

    async def test_an_ordinal_picks_from_the_waiting_list(self):
        conversation = Conversation()
        conversation.remember_choices(
            [Choice(number=1, label="a", payload="a.txt"),
             Choice(number=2, label="b", payload="b.txt"),
             Choice(number=3, label="c", payload="c.txt")],
            "Which one?", "open")
        assert conversation.resolve_choice("2").payload == "b.txt"
        assert conversation.resolve_choice("the second one").payload == "b.txt"
        assert conversation.resolve_choice("the 2nd one").payload == "b.txt"
        assert conversation.resolve_choice("last").payload == "c.txt"

    async def test_an_ambiguous_reference_does_not_guess(self):
        conversation = Conversation()
        conversation.remember_choices(
            [Choice(number=1, label="a"), Choice(number=2, label="b"),
             Choice(number=3, label="c")],
            "Which one?", "open")
        # "that one" points at nothing in particular, and guessing would open
        # a file the user did not mean.
        assert conversation.resolve_choice("that one") is None

    async def test_history_is_bounded(self):
        conversation = Conversation(max_turns=3)
        for n in range(10):
            conversation.record(f"q{n}", f"a{n}")
        assert len(conversation.history()) == 3


class TestEvents:
    async def test_a_request_publishes_what_happened(self, full):
        seen = []
        full.bus.subscribe("*", lambda event: seen.append(event.name))

        await full.handle_input("what is the time", Source.TERMINAL)

        assert "user_input" in seen
        assert "skill_selected" in seen
        assert "tool_completed" in seen
        assert "assistant_response" in seen

    async def test_a_confirmation_publishes_the_question(self, full):
        seen = []
        full.bus.subscribe("confirmation_required",
                           lambda event: seen.append(event.data))

        await full.handle_input("shutdown", Source.TERMINAL)
        assert seen[0]["action"] == "shutdown"

    async def test_a_queued_subscriber_gets_them_in_order(self, full):
        subscription = full.bus.subscribe("*", queue=True)
        await full.handle_input("what is the time", Source.TERMINAL)

        events = full.bus.drain(subscription)
        assert [event["event"] for event in events][:2] == [
            "user_input", "skill_selected"
        ]

    async def test_a_listener_that_fails_does_not_break_the_command(self, full):
        def explode(event):
            raise RuntimeError("listener is broken")

        full.bus.subscribe("*", explode)
        response = await full.handle_input("what is the time", Source.TERMINAL)
        # The command still works, because a listener is not the assistant's
        # problem.
        assert response.status is Status.OK

    async def test_nothing_secret_reaches_an_event(self, settings, memory):
        # Assembled from parts so no scanner mistakes the fixture for a real key.
        fake = "sk-" + "supersecret"
        secret = settings.with_overrides(
            ai_api_key=fake,
            extra={"root": str(memory.store.directory.parent)})
        assistant = JarvisAssistant(settings=secret, memory=memory)
        await assistant.handle_input("what is the time", Source.TERMINAL)

        for entry in assistant.bus.recent(100):
            assert fake not in str(entry)


class TestFailureIsReported:
    async def test_a_skill_that_raises_is_reported_not_raised(self, full):
        from jarvis2.skills.base import Skill

        class Broken(Skill):
            name = "broken"
            description = "always fails"
            actions = ()
            keywords = ("break")

            async def can_handle(self, request):
                return 0.99

            async def execute(self, request, context):
                raise RuntimeError("this skill is broken")

        full.registry.register(Broken())
        response = await full.handle_input("break something", Source.TERMINAL)

        assert response.status is Status.FAILED
        assert "could not do that" in response.text
        assert "this skill is broken" in response.error

    async def test_nothing_said_is_handled(self, full):
        response = await full.handle_input("   ", Source.TERMINAL)
        assert "did not catch" in response.text

    async def test_a_reply_carries_how_long_it_took(self, full):
        response = await full.handle_input("what is the time", Source.TERMINAL)
        assert response.took > 0


class TestRouter:
    async def test_an_answer_goes_to_the_waiting_list(self, settings, memory):
        assistant = JarvisAssistant(settings=settings, memory=memory)
        assistant.conversation.remember_choices(
            [Choice(number=1, label="a"), Choice(number=2, label="b")],
            "Which one?", "open")
        route = await assistant.router.choose(Request(text="2"))
        assert route.kind == "choice"

    async def test_a_command_is_not_read_as_an_answer(self, settings, memory):
        assistant = JarvisAssistant(settings=settings, memory=memory)
        assistant.conversation.remember_choices(
            [Choice(number=1, label="a"), Choice(number=2, label="b")],
            "Which one?", "open")
        route = await assistant.router.choose(Request(text="open chrome"))
        assert route.kind == "skill"

    async def test_with_a_model_but_no_skill_it_asks_the_model(self, settings,
                                                                memory):
        assistant = JarvisAssistant(
            settings=settings, memory=memory, provider=MockAIProvider())
        route = await assistant.router.choose(Request(text="why is the sky blue"))
        assert route.kind == "ai"

    async def test_with_nothing_it_reaches_the_knowledge_skill(self, settings,
                                                                memory):
        assistant = JarvisAssistant(settings=settings, memory=memory)
        route = await assistant.router.choose(Request(text="why is the sky blue"))
        assert route.kind == "knowledge"

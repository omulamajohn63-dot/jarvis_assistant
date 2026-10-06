"""Skills: how they are chosen, what they are allowed, and what they return."""

import pytest
from conftest import RecordingContext

from jarvis2.core.models import Request, Source
from jarvis2.safety.policy import Risk
from jarvis2.skills import build_default_registry
from jarvis2.skills.applications import find_application
from jarvis2.skills.base import Skill
from jarvis2.skills.files import strip_verb
from jarvis2.skills.registry import SkillRegistry
from jarvis2.skills.system import ends_session, normalize_command, power_intent


def request_for(text: str) -> Request:
    return Request(text=text, source=Source.TERMINAL)


class TestRegistry:
    def test_the_default_registry_builds(self):
        registry = build_default_registry()
        assert len(registry) > 0

    @pytest.mark.parametrize("name", [
        "power", "exit", "clock", "jokes", "screenshot", "browser", "apps",
        "documents", "media", "files", "speaker", "conversation", "status",
    ])
    def test_every_named_skill_is_there(self, name):
        assert build_default_registry().get(name) is not None

    def test_names_are_unique(self):
        registry = build_default_registry()
        assert len(registry.names) == len(set(registry.names))

    def test_a_duplicate_name_is_refused(self):
        registry = SkillRegistry()
        registry.register(build_default_registry().get("clock"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(build_default_registry().get("clock"))

    def test_a_skill_with_no_name_is_refused(self):
        class Nameless(Skill):
            pass

        with pytest.raises(ValueError, match="no name"):
            SkillRegistry().register(Nameless())

    def test_a_skill_declaring_a_refused_action_is_refused(self):
        # Failing to start is better than failing mid-conversation.
        class Unsafe(Skill):
            name = "unsafe"
            actions = ("execute_command")

        with pytest.raises(ValueError, match="may not perform"):
            SkillRegistry().register(Unsafe())

    def test_the_registry_can_be_described(self):
        described = build_default_registry().describe()
        assert all("name" in entry and "description" in entry
                   for entry in described)

    def test_tool_schemas_come_from_the_skills(self):
        schemas = build_default_registry().tool_schemas()
        assert schemas
        for schema in schemas:
            assert schema["function"]["name"]
            assert schema["function"]["description"]


class TestPowerIntent:
    @pytest.mark.parametrize("text,expected", [
        ("shutdown", "shutdown"),
        ("shut down", "shutdown"),
        ("please shut down my computer now", "shutdown"),
        ("hey jarvis power off the pc", "shutdown"),
        ("restart", "restart"),
        ("reboot windows", "restart"),
        ("please restart windows", "restart"),
    ])
    def test_recognised(self, text, expected):
        assert power_intent(text) == expected

    @pytest.mark.parametrize("text", [
        "how do i restart windows safely",
        "what is a shutdown",
        "tell me about restart sequences",
        "why does the shutdown happen on my laptop",
    ])
    def test_a_question_never_counts(self, text):
        # Matching is on the whole message, so the word appearing in a sentence
        # is not enough. This is the defect that rebooted a computer.
        assert power_intent(text) is None

    def test_normalising_takes_wording_off_both_ends(self):
        assert normalize_command("shutdown") == "shutdown"
        assert normalize_command("Please shut down my computer now.") == "shut down"

    def test_normalising_is_idempotent(self):
        once = normalize_command("hey jarvis shut down the pc now")
        assert normalize_command(once) == once

    @pytest.mark.parametrize("text", ["exit", "quit", "goodbye", "go offline"])
    def test_the_usual_goodbyes(self, text):
        assert ends_session(text) is True

    @pytest.mark.parametrize("text", [
        "what does offline mean", "what is the exit code of main",
    ])
    def test_a_question_about_a_goodbye_is_not_one(self, text):
        assert ends_session(text) is False


class TestVerbParsing:
    @pytest.mark.parametrize("text,action,subject", [
        ("open chrome", "open", "chrome"),
        ("launch the cv", "open", "cv"),
        ("read my cv", "read", "cv"),
        ("read aloud the syllabus", "read", "syllabus"),
        ("play oh jah", "play", "oh jah"),
        ("watch blues brothers", "play", "blues brothers"),
        ("listen to gospel", "play", "gospel"),
    ])
    def test_taken_apart(self, text, action, subject):
        assert strip_verb(text) == (action, subject)

    @pytest.mark.parametrize("text", ["what is the time", "hello", "cv"])
    def test_a_request_with_no_verb_is_left_alone(self, text):
        assert strip_verb(text)[0] is None


class TestApplications:
    def test_a_program_on_the_path_is_found(self):
        found = find_application("notepad")
        assert found is not None
        assert "notepad" in found.target.lower()

    def test_an_alias_is_resolved(self):
        # PATH is consulted before the Start Menu, so a program Windows ships
        # with beats a third party app of a similar name.
        assert find_application("calculator") is not None

    def test_nothing_gives_nothing(self):
        assert find_application("definitelynotanapplication") is None

    def test_an_empty_name_gives_nothing(self):
        assert find_application("") is None


class TestPowerSkill:
    async def test_shutdown_asks_and_does_nothing(self, settings, memory,
                                                   monkeypatch):
        ran = []
        monkeypatch.setattr(
            "jarvis2.skills.system.subprocess", type(
                "S", (), {"run": staticmethod(
                    lambda argv, **kw: ran.append(argv))}
            ), raising=False)

        registry = build_default_registry()
        skill = registry.get("power")
        context = RecordingContext(settings, memory=memory)
        result = await skill.execute(request_for("shutdown"), context)

        assert result.confirmation is not None
        assert result.confirmation.action == "shutdown"
        assert ran == []

    async def test_a_question_is_not_a_power_action(self, settings, memory):
        skill = build_default_registry().get("power")
        result = await skill.execute(
            request_for("how do i restart windows safely"),
            RecordingContext(settings, memory=memory))
        assert result.confirmation is None
        assert result.succeeded is False


class TestClockSkill:
    async def test_the_time(self, settings, memory, frozen_clock):
        skill = build_default_registry().get("clock")
        result = await skill.execute(
            request_for("what is the time"),
            RecordingContext(settings, memory=memory))
        assert result.succeeded is True
        assert "2:30 PM" in result.text

    async def test_the_date(self, settings, memory, frozen_clock):
        skill = build_default_registry().get("clock")
        result = await skill.execute(
            request_for("what is the date"),
            RecordingContext(settings, memory=memory))
        assert "Monday" in result.text
        assert "October" in result.text
        assert "2026" in result.text

    @pytest.mark.parametrize("text", [
        "what is the time machine",
        "tell me about time zones",
        "what is the date of the moon landing",
    ])
    async def test_a_topic_is_not_the_clock(self, settings, memory, text):
        # The clock is not fooled by a subject that happens to share a word.
        skill = build_default_registry().get("clock")
        assert await skill.can_handle(request_for(text)) == 0.0

    @pytest.mark.parametrize("text", [
        "what is the time", "what is the date", "what is today's date",
        "tell me the time",
    ])
    async def test_the_clock_is_recognised(self, settings, memory, text):
        skill = build_default_registry().get("clock")
        assert await skill.can_handle(request_for(text)) > 0


class TestJokeSkill:
    async def test_a_joke(self, settings, memory):
        skill = build_default_registry().get("jokes")
        result = await skill.execute(
            request_for("tell me a joke"), RecordingContext(settings, memory=memory)
        )
        assert result.succeeded is True
        assert len(result.text) > 10

    async def test_a_missing_library_is_a_sentence_not_a_traceback(
        self, settings, memory, monkeypatch
    ):
        import builtins

        real_import = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "pyjokes":
                raise ImportError("no pyjokes")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)

        skill = build_default_registry().get("jokes")
        result = await skill.execute(
            request_for("joke"), RecordingContext(settings, memory=memory)
        )
        assert result.succeeded is False
        assert "not installed" in result.text


class TestBrowserSkill:
    async def test_a_known_site(self, settings, memory):
        opened = []
        skill = build_default_registry().get("browser")
        context = RecordingContext(settings, memory=memory, opened=opened)
        context.run_blocking = _recorder(opened)

        result = await skill.execute(request_for("open youtube"), context)
        assert result.succeeded is True
        assert "youtube.com" in result.opened[0]

    async def test_a_search(self, settings, memory):
        opened = []
        skill = build_default_registry().get("browser")
        context = RecordingContext(settings, memory=memory, opened=opened)
        context.run_blocking = _recorder(opened)

        result = await skill.execute(
            request_for("search google for python tutorials"), context
        )
        assert "google.com/search" in result.opened[0]
        assert "python" in result.opened[0]

    async def test_a_bare_url(self, settings, memory):
        opened = []
        skill = build_default_registry().get("browser")
        context = RecordingContext(settings, memory=memory, opened=opened)
        context.run_blocking = _recorder(opened)

        result = await skill.execute(request_for("open example.com"), context)
        assert "example.com" in result.opened[0]

    async def test_the_reply_names_a_source(self, settings, memory):
        opened = []
        skill = build_default_registry().get("browser")
        context = RecordingContext(settings, memory=memory, opened=opened)
        context.run_blocking = _recorder(opened)

        result = await skill.execute(request_for("open github"), context)
        # Current information is marked as such, rather than passed off as
        # general knowledge.
        assert result.sources
        assert result.sources[0]["kind"] == "web"


class TestStatusSkill:
    async def test_it_describes_what_it_can_do(self, settings, memory):
        skill = build_default_registry().get("status")
        result = await skill.execute(
            request_for("what can you do"),
            RecordingContext(settings, memory=memory,
                             registry=build_default_registry()))
        assert result.succeeded is True
        assert "open files" in result.text
        assert result.data["capabilities"]

    async def test_the_settings_shown_carry_no_secrets(self, settings, memory):
        from jarvis2.config.settings import Settings

        secret = Settings(ai_api_key="sk-secret", assistant_name="Friday")
        skill = build_default_registry().get("status")
        result = await skill.execute(
            request_for("what can you do"),
            RecordingContext(secret, memory=memory,
                             registry=build_default_registry()))
        assert "sk-secret" not in str(result.data)


class TestSelfTestSkill:
    async def test_it_reports_its_parts(self, settings, memory, assistant):
        skill = build_default_registry().get("selftest")
        context = RecordingContext(settings, memory=memory, session=assistant)
        result = await skill.execute(
            request_for("are you working"), context
        )
        assert result.succeeded is True
        assert result.data["memory"] is True
        assert result.data["provider"] == "none"

    async def test_it_says_what_is_missing(self, settings, memory, assistant):
        skill = build_default_registry().get("selftest")
        context = RecordingContext(settings, memory=memory, session=assistant)
        result = await skill.execute(request_for("health check"), context)
        assert "Working without" in result.text


class TestToolSchemas:
    def test_every_skill_advertises_itself(self):
        for skill in build_default_registry():
            schema = skill.tool_schema
            assert schema["function"]["name"] == skill.name
            assert isinstance(schema["function"]["parameters"], dict)

    def test_a_skill_with_arguments_declares_them(self):
        schema = build_default_registry().get("documents").tool_schema
        assert "query" in schema["function"]["parameters"]["properties"]

    def test_a_skill_with_no_arguments_says_so(self):
        schema = build_default_registry().get("power").tool_schema
        assert schema["function"]["parameters"]["additionalProperties"] is False

    def test_the_risk_shown_is_the_worst_the_skill_does(self):
        assert build_default_registry().get("power").risk is Risk.HIGH
        assert build_default_registry().get("clock").risk is Risk.LOW


def _recorder(opened):
    """A run_blocking that records what would have been opened."""

    async def run(function, *args, **kwargs):
        opened.append(args[0] if args else "")
        return None

    return run

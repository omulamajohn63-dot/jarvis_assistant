"""Choosing from a numbered list.

A list is offered because the assistant did not know which file was meant. Every
test here is about the two things that follow from that: saying a number opens
the row carrying that number, and anything that does not name a row opens
nothing at all. Guessing here opens a file the user did not ask for.
"""

from pathlib import Path

import pytest

from jarvis2.core.conversation import Conversation
from jarvis2.core.models import Choice, Source
from jarvis2.files import search


def three_choices() -> list:
    return [
        Choice(number=1, label="cv", payload=Path("C:/home/Documents/cv.docx")),
        Choice(number=2, label="cv one", payload=Path("C:/home/Documents/cv one.docx")),
        Choice(number=3, label="cv two", payload=Path("C:/home/Documents/cv two.pdf")),
    ]


@pytest.fixture
def waiting():
    """A conversation with three entries already on screen."""
    conversation = Conversation()
    conversation.remember_choices(three_choices(), "3 matches for cv", "open")
    return conversation


class TestNothingWaiting:
    def test_a_command_is_not_an_answer(self, waiting):
        conversation = Conversation()

        assert conversation.resolve_choice("open chrome") is None

    def test_a_number_with_nothing_waiting_is_not_an_answer(self, waiting):
        # Otherwise a bare "2" would reach into a list that is not there.
        conversation = Conversation()

        assert conversation.resolve_choice("3") is None

    def test_nothing_is_waiting(self):
        assert Conversation().has_choices() is False


class TestSayingANumber:
    @pytest.mark.parametrize("number,expected", [
        ("1", "cv"),
        ("2", "cv one"),
        ("3", "cv two"),
    ])
    def test_the_number_opens_the_row_carrying_it(self, waiting, number, expected):
        # The number shown and the number accepted must be the same list,
        # otherwise "say 2" does something other than line 2.
        chosen = waiting.resolve_choice(number)

        assert chosen is not None
        assert chosen.label == expected
        assert chosen.number == int(number)


class TestSayingAWordForANumber:
    @pytest.mark.parametrize("answer,expected", [
        ("first", 1),
        ("the first one", 1),
        ("the first", 1),
        ("1st", 1),
        ("second", 2),
        ("the second one", 2),
        ("the 2nd one", 2),
        ("third", 3),
        ("the third one", 3),
        ("last", 3),
        ("the last one", 3),
    ])
    def test_every_way_of_saying_it_reaches_the_same_row(self, waiting, answer,
                                                         expected):
        chosen = waiting.resolve_choice(answer)

        assert chosen is not None
        assert chosen.number == expected


class TestRefusingToGuess:
    @pytest.mark.parametrize("answer", [
        "that one",     # With three on screen this points at nothing.
        "yes",
        "no",
        "cancel",
        "no thanks",
        "",
        "   ",
        "banana",
    ])
    def test_words_that_name_no_row_open_nothing(self, waiting, answer):
        assert waiting.resolve_choice(answer) is None

    @pytest.mark.parametrize("answer", ["0", "4", "9", "99"])
    def test_a_number_that_is_not_on_screen_opens_nothing(self, waiting, answer):
        assert waiting.resolve_choice(answer) is None

    def test_an_ordinal_past_the_end_opens_nothing(self, waiting):
        assert waiting.resolve_choice("fifth") is None

    def test_an_ordinal_with_nothing_waiting_opens_nothing(self):
        conversation = Conversation()

        assert conversation.resolve_choice("first") is None

    def test_last_with_one_result_is_that_result(self):
        conversation = Conversation()
        conversation.remember_choices(three_choices()[:1], "1 match", "open")

        chosen = conversation.resolve_choice("last")

        assert chosen is not None
        assert chosen.number == 1


class TestTheListIsUsedOnce:
    def test_taking_the_list_clears_it(self, waiting):
        taken = waiting.take_choices()

        assert len(taken) == 3
        assert waiting.has_choices() is False
        assert waiting.state.pending_action == ""
        assert waiting.state.pending_topic == ""

    def test_an_answer_is_not_reused(self, waiting):
        # If "1" still worked after the list was answered, a second "1" would
        # open the same file again without being asked.
        waiting.resolve_choice("1")
        waiting.take_choices()

        assert waiting.resolve_choice("1") is None

    def test_a_bare_number_with_nothing_waiting_asks_what_is_meant(self, waiting):
        taken = waiting.take_choices()
        waiting.take_choices()

        assert waiting.resolve_choice("1") is None
        assert len(taken) == 3


class TestYesAndNo:
    def test_yes_with_one_result_on_screen_takes_it(self):
        conversation = Conversation()
        conversation.remember_choices(three_choices()[:1], "1 match", "open")

        # One entry cannot be ambiguous, so there is nothing to ask about.
        assert conversation.state.pending_choices[0].label == "cv"

    def test_yes_with_several_on_screen_names_nothing(self, waiting):
        # Acting on "yes" with three entries would pick one at random, which is
        # how the wrong file gets opened.
        assert waiting.resolve_choice("yes") is None


class TestWhatTheListWasFor:
    def test_a_file_list_opens_the_file(self):
        conversation = Conversation()
        conversation.remember_choices(three_choices(), "3 matches", "open")

        assert conversation.state.pending_action == "open"

    def test_an_article_list_is_marked_as_a_lookup(self):
        # This is the only thing that tells an article title from a path, and
        # treating "Mercury (planet)" as a file would refuse every answer.
        titles = [
            Choice(number=1, label="Mercury (planet)", payload="Mercury (planet)"),
            Choice(number=2, label="Mercury (element)", payload="Mercury (element)"),
            Choice(number=3, label="Mercury (mythology)", payload="Mercury (mythology)"),
        ]
        conversation = Conversation()
        conversation.remember_choices(titles, "3 articles", "lookup", "mercury")

        assert conversation.state.pending_action == "lookup"
        assert conversation.state.pending_topic == "mercury"

    def test_the_number_of_the_second_article_is_the_second_article(self):
        titles = [
            Choice(number=1, label="Mercury (planet)", payload="Mercury (planet)"),
            Choice(number=2, label="Mercury (element)", payload="Mercury (element)"),
        ]
        conversation = Conversation()
        conversation.remember_choices(titles, "2 articles", "lookup", "mercury")

        chosen = conversation.resolve_choice("2")

        assert chosen is not None
        assert chosen.payload == "Mercury (element)"


class TestChoicePositionIsPure:
    """The same reading, with no conversation attached."""

    @pytest.mark.parametrize("answer,expected", [
        ("1", 1),
        ("3", 3),
        ("first", 1),
        ("second", 2),
        ("third", 3),
        ("the second one", 2),
        ("2nd", 2),
        ("the 2nd one", 2),
        ("second please", 2),
        ("last", 3),
        ("the last one", 3),
    ])
    def test_a_position_is_found(self, answer, expected):
        assert search.choice_position(answer, 3) == expected

    @pytest.mark.parametrize("answer", [
        "yes", "no", "cancel", "", "   ", "that one", "no thanks", "banana",
    ])
    def test_words_naming_no_position_are_not_guessed(self, answer):
        assert search.choice_position(answer, 3) is None

    @pytest.mark.parametrize("answer", ["0", "9"])
    def test_a_number_past_the_end_is_not_guessed(self, answer):
        assert search.choice_position(answer, 3) is None

    def test_an_ordinal_past_the_end_is_not_guessed(self):
        assert search.choice_position("fifth", 3) is None

    def test_nothing_on_screen_means_nothing_to_choose(self):
        assert search.choice_position("first", 0) is None

    def test_last_with_one_on_screen_is_that_one(self):
        assert search.choice_position("last", 1) == 1


class TestAListDoesNotSwallowTheNextCommand:
    """A list on screen must not break anything said afterwards.

    This is the worst shape of bug in an assistant: one ambiguous question
    leaves a state behind that quietly refuses every later command.
    """

    @pytest.fixture
    def listed(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant
        from tests.v2.test_end_to_end import FakeWikipedia

        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=FakeWikipedia())
        return assistant

    async def test_a_new_command_still_works_after_a_list(self, listed):
        from jarvis2.core.models import Source

        asked = await listed.handle_input("tell me about mercury", Source.TERMINAL)
        assert asked.choices

        after = await listed.handle_input("what is the time", Source.TERMINAL)

        assert after.status.value == "ok"
        assert after.skill == "clock"

    async def test_words_naming_nothing_say_so_rather_than_refusing(self, listed):
        from jarvis2.core.models import Source

        await listed.handle_input("tell me about mercury", Source.TERMINAL)

        after = await listed.handle_input("please open chrome", Source.TERMINAL)

        assert "do not know how" not in after.text.lower()

    async def test_the_router_does_not_call_a_new_command_an_answer(self, listed):
        from jarvis2.core.models import Request, Source

        await listed.handle_input("tell me about mercury", Source.TERMINAL)

        for command in ("what is the time", "please open chrome",
                        "tell me a joke", "hello"):
            route = await listed.router.choose(
                Request(text=command, source=Source.TERMINAL))
            assert route.kind != "choice", command


class TestAnAnswerIsNotAQuestion:
    @pytest.mark.parametrize("text", [
        "yes", "no", "ok", "thanks", "more", "cancel", "1", "42",
    ])
    def test_a_reply_is_never_looked_up(self, text):
        # Looking "1" up on Wikipedia would answer a number with an article.
        from jarvis2.files import text as words

        assert words.is_a_reply(text) is True

    @pytest.mark.parametrize("text", [
        "who is einstein", "what is python", "mt everest",
    ])
    def test_a_question_is_not_a_reply(self, text):
        from jarvis2.files import text as words

        assert words.is_a_reply(text) is False


class TestTheRouterPrefersAnAnswerOverANewCommand:
    async def test_a_number_answers_the_list_rather_than_starting_a_command(
        self, settings, memory
    ):
        from jarvis2.core.assistant import JarvisAssistant

        class Opener(JarvisAssistant):
            def __init__(self, *args, **kwargs):
                self.opened: list = []
                super().__init__(*args, **kwargs)

            def _open_path(self, path):
                self.opened.append(path)

        assistant = Opener(settings=settings, memory=memory)
        for name in ("cv.docx", "cv one.docx", "cv two.pdf"):
            path = Path(settings.extra["root"]) / "Documents" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 64)

        listed = await assistant.handle_input("open my cv", Source.TERMINAL)
        assert len(listed.choices) >= 2

        before = len(assistant.opened)
        await assistant.handle_input("1", Source.TERMINAL)

        assert len(assistant.opened) == before + 1
        assert assistant.conversation.has_choices() is False

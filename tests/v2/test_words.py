"""Turning speech into something a machine can compare.

Every request passes through here first, so a mistake is not a wrong answer but
no answer at all. The cases below are the ones that were wrong at some point.
"""

import pytest

from jarvis2.files import text as words


class TestWords:
    def test_whole_words_only(self):
        assert words.words_of("hello there") == {"hello", "there"}

    def test_a_possessive_is_dropped(self):
        # So "today's date" and "today" are the same word to the helpers below.
        assert words.words_of("today's date") == {"today", "date"}

    def test_digits_survive_and_punctuation_does_not(self):
        assert words.words_of("episode 4, part 2") == {"episode", "4", "part", "2"}

    def test_nothing_gives_nothing(self):
        assert words.words_of("") == set()


class TestAskingForTheClock:
    @pytest.mark.parametrize("text", [
        "what is the time",
        "what's the time",
        "tell me the time",
        "what time is it",
        "what is the current time",
        "what is the time right now",
    ])
    def test_the_usual_ways_of_asking(self, text):
        assert words.asks_for_time(text) is True

    @pytest.mark.parametrize("text", [
        # This one is the whole point of the filler check: "what is the time
        # machine" must be looked up, not announced.
        "what is the time machine",
        "tell me about time zones",
        "time flies",
        "what is the date",
    ])
    def test_a_topic_that_merely_contains_the_word_is_not_the_clock(self, text):
        assert words.asks_for_time(text) is False


class TestAskingForTheDate:
    @pytest.mark.parametrize("text", [
        "what is the date",
        "what is today's date",
        "tell me the date",
        "what is today",
    ])
    def test_the_usual_ways_of_asking(self, text):
        assert words.asks_for_date(text) is True

    @pytest.mark.parametrize("text", [
        "what is the date of the moon landing",
        "tell me about date palm trees",
    ])
    def test_a_topic_that_merely_contains_the_word_is_not_the_date(self, text):
        assert words.asks_for_date(text) is False


class TestNamingASource:
    @pytest.mark.parametrize("text", ["wikipedia python", "wiki python"])
    def test_naming_the_site_asks_for_a_lookup(self, text):
        assert words.mentions_lookup(text) is True

    def test_a_plain_question_names_no_site(self):
        assert words.mentions_lookup("what is python") is False


class TestStrippingArticles:
    @pytest.mark.parametrize("given,expected", [
        ("the music folder", "music folder"),
        ("my cv", "cv"),
        ("a song", "song"),
        ("an app", "app"),
        ("music folder", "music folder"),
    ])
    def test_the_leading_article_is_dropped(self, given, expected):
        assert words.strip_articles(given) == expected


class TestFindingTheSubjectOfAQuestion:
    @pytest.mark.parametrize("given,expected", [
        ("who is einstein", "einstein"),
        ("what is python", "python"),
        ("tell me about kenya", "kenya"),
        ("why is the sky blue", "the sky blue"),
        ("how do magnets work", "magnets work"),
        ("wikipedia python", "python"),
        ("wiki python", "python"),
        ("who was einstein?", "einstein"),
        ("wikipedia for mercury", "mercury"),
    ])
    def test_the_question_wording_comes_off(self, given, expected):
        assert words.lookup_topic(given) == expected

    def test_prefixes_come_off_one_layer_at_a_time(self):
        assert words.lookup_topic("wikipedia what is python") == "python"

    def test_a_subject_that_starts_with_a_question_word_survives(self):
        # Unwrapping stops as soon as something worth looking up is left, so the
        # subject is not chewed down to "machine".
        assert words.lookup_topic("what is the time machine") == "the time machine"

    @pytest.mark.parametrize("given", ["tell me about", "wikipedia"])
    def test_nothing_left_means_there_is_no_subject(self, given):
        # An empty string tells the caller to ask what to look up, rather than
        # searching for the question wording itself.
        assert words.lookup_topic(given) == ""


class TestWhatCountsAsAQuestionWorthLookingUp:
    @pytest.mark.parametrize("text", [
        "who is ada lovelace",
        "what is python",
        "tell me about mercury",
        "wikipedia for blue screen of death",
    ])
    def test_a_question_with_a_subject(self, text):
        assert words.asks_for_knowledge(text) is True

    @pytest.mark.parametrize("text", [
        # None of these have a subject, and each one used to send something
        # pointless or wrong to Wikipedia.
        "hello",
        "who is",
        "thanks",
        "open my cv",
        "play collo blue top shotta",
        # A question about the machine, not about a subject.
        "how do i restart windows safely",
    ])
    def test_no_subject_to_look_up(self, text):
        assert words.asks_for_knowledge(text) is False


class TestTakingTheFirstFewSentences:
    def test_the_terminators_are_kept(self):
        assert words.first_sentences("One. Two. Three. Four.", 2) == "One. Two."

    def test_text_with_no_terminator_is_returned_whole(self):
        assert words.first_sentences("no full stop here", 2) == "no full stop here"

    def test_fewer_than_asked_for_is_fine(self):
        assert words.first_sentences("Only one.", 3) == "Only one."

    def test_nothing_gives_nothing(self):
        assert words.first_sentences("", 2) == ""


class TestNormalisingACommand:
    def test_it_is_idempotent(self):
        once = words.normalize_command("shut down my computer now")

        assert words.normalize_command(once) == once

    def test_wording_comes_off_both_ends_to_a_fixpoint(self):
        # Removing "now" leaves "my computer", which leaves an article, which has
        # to come off as well or the command would not be recognised.
        assert words.normalize_command("shut down my computer now") == "shut down"
        assert words.normalize_command("the computer") == "computer"


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
    def test_the_sentence_is_taken_apart(self, text, action, subject):
        from jarvis2.skills.files import strip_verb

        assert strip_verb(text) == (action, subject)

    @pytest.mark.parametrize("text", ["what is the time", "hello", "cv"])
    def test_a_request_with_no_verb_is_left_alone(self, text):
        from jarvis2.skills.files import strip_verb

        assert strip_verb(text)[0] is None

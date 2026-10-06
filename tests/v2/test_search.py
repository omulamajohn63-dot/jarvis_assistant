"""Finding the file somebody described out loud.

The whole of what "play oh jah" and "open my cv" rest on. The tests are written
against a library of names rather than a disk wherever possible, because a scan
of a real home folder is slow and depends on what the developer has downloaded.
"""

import pytest

from jarvis2.files import search


class TestNormalisingNames:
    @pytest.mark.parametrize("given,expected", [
        ("My CV (final)", "my cv"),
        ("Track [Remastered]", "track"),
        ("A-B_C", "a b c"),
        ("Oh Jah!", "oh jah"),
    ])
    def test_bracketed_text_is_dropped_and_punctuation_becomes_space(
        self, given, expected
    ):
        # "(final)" and "[Remastered]" are not part of what somebody says when
        # they ask for a file, and matching them would make every open fail.
        assert search.clean_name(given) == expected


class TestTwoWordsAreTheSameName:
    @pytest.mark.parametrize("token,word", [
        ("oh", "oh"),
        ("gospel", "gospel"),
        # A spaced out title still names one word.
        ("collo", "colloblue"),
        ("blue", "colloblue"),
        ("gospel", "23gospel"),
    ])
    def test_a_spoken_word_can_name_a_word_in_the_file_name(self, token, word):
        assert search.token_matches(token, word) is True

    @pytest.mark.parametrize("token,word", [
        # "youtube" begins with "you", which used to count as naming the word,
        # so "open youtube" opened an unrelated document.
        ("youtube", "you"),
        ("y", "you"),
        ("restart", "response"),
        ("cv", "c"),
        ("ab", "abc"),
        ("gospel", "gos"),
    ])
    def test_a_coincidence_is_not_a_match(self, token, word):
        assert search.token_matches(token, word) is False


class TestScoring:
    def test_the_same_name_scores_one(self):
        assert search.match_score("gospel", "GOSPEL") == 1.0

    def test_partial_credit_is_proportional(self):
        # One of two spoken words is in the name, so half of it is accounted for.
        assert search.match_score("gospel song", "Gospel") == 0.5

    def test_a_spaced_out_title_still_matches(self):
        # This is promised to users in the README, so it is pinned here.
        assert search.match_score(
            "collo blue top shotta", "COLLOBLUE - TOP SHOTTA FT KBC") == 1.0

    def test_nothing_in_common_scores_nothing(self):
        assert search.match_score(
            "youtube", "Since you are teaching beginners") == 0.0

    @pytest.mark.parametrize("query,label", [("", "gospel"), ("gospel", "")])
    def test_nothing_to_compare_scores_nothing(self, query, label):
        assert search.match_score(query, label) == 0.0

    def test_the_extension_is_not_part_of_the_name(self):
        # Nobody says "cv.pdf". Counting the extension would mean every spoken
        # request missed the file it names.
        assert search.match_score("cv.pdf", "cv") == 1.0


LIBRARY = {
    "gospel": ["C:/Music/gospel.mp3"],
    "23gospel rmh": ["C:/Downloads/23gospel.mp3"],
    "blues": ["C:/Music/blues.mp3"],
    "piano": ["C:/Music/piano.mp3"],
}


class TestRanking:
    def test_the_exact_name_comes_first(self):
        ranked = search.rank_matches(LIBRARY, "gospel")
        assert ranked[0].label == "gospel"
        assert ranked[0].path == "C:/Music/gospel.mp3"

    def test_the_best_match_is_first(self):
        scores = [match.score for match in search.rank_matches(LIBRARY, "gospel")]
        assert scores == sorted(scores, reverse=True)

    def test_a_limit_keeps_only_the_best(self):
        assert len(search.rank_matches(LIBRARY, "gospel", limit=1)) == 1

    def test_a_name_that_matches_nothing_is_not_offered(self):
        assert search.rank_matches(LIBRARY, "zzzzzz") == []

    def test_nothing_searched_matches_nothing(self):
        assert search.rank_matches({}, "gospel") == []

    def test_one_name_with_two_files_is_listed_once_per_file(self):
        # A song saved as both .mp3 and .m4a is two real files, and either may
        # be the one that plays.
        library = {"gospel": ["C:/Music/gospel.mp3", "C:/Music/gospel.m4a"]}
        assert [match.path for match in search.rank_matches(library, "gospel")] == [
            "C:/Music/gospel.mp3",
            "C:/Music/gospel.m4a",
        ]


class TestScanning:
    def test_a_word_lock_file_beside_the_real_one_is_never_indexed(self, tmp_path):
        # Word and Excel leave one of these beside the real file while a
        # document is open, and it is never what anybody meant to open.
        (tmp_path / "cv.docx").write_bytes(b"x" * 64)
        (tmp_path / "~$cv.docx").write_bytes(b"x" * 64)

        library = search.scan_roots([str(tmp_path)], search.DOCUMENT_EXTENSIONS)

        assert sorted(library) == ["cv"]

    def test_every_promised_format_is_searched(self, tmp_path):
        names = []
        for number, extension in enumerate(sorted(search.DOCUMENT_EXTENSIONS)):
            names.append(f"report{number}")
            (tmp_path / f"report{number}{extension}").write_bytes(b"x" * 8)

        library = search.scan_roots([str(tmp_path)], search.DOCUMENT_EXTENSIONS)

        assert sorted(library) == sorted(names)

    def test_a_dependency_directory_is_not_walked(self, tmp_path):
        # node_modules can hold more files than the rest of the disk put
        # together, and nothing anybody asks for is in there.
        (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
        (tmp_path / "node_modules" / "left-pad" / "song.mp3").write_bytes(b"x")
        (tmp_path / "wanted.mp3").write_bytes(b"x")

        library = search.scan_roots([str(tmp_path)], search.MEDIA_EXTENSIONS)

        assert sorted(library) == ["wanted"]

    def test_a_folder_that_is_not_there_is_skipped(self):
        assert search.scan_roots(["C:/nowhere-at-all"]) == {}


class TestTheIndexIsReused:
    def test_the_same_index_is_handed_back(self, monkeypatch, tmp_path):
        # A scan of a real home folder costs seconds. Doing it per question
        # would make the assistant unusable, so the index is kept and cleared
        # only on purpose.
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        search.clear_caches()

        calls = []
        real = search.scan_roots

        def counted(roots, extensions=None):
            calls.append(roots)
            return real(roots, extensions)

        monkeypatch.setattr(search, "scan_roots", counted)

        search.find("anything")
        search.find("something else")

        assert len(calls) == 1
        search.clear_caches()

    def test_clearing_forgets_it_so_a_new_file_is_found(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "Documents").mkdir()
        search.clear_caches()

        try:
            assert search.find_documents("late arrival") == []

            (tmp_path / "Documents" / "late arrival.docx").write_bytes(b"x" * 8)
            search.clear_caches()

            found = search.find_documents("late arrival")
            assert [match.label for match in found] == ["late arrival"]
        finally:
            search.clear_caches()

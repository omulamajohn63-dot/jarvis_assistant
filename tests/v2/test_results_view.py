"""The numbered list a user is shown.

Two things have to agree: the number rendered beside a row, and the number the
assistant accepts for that row. These tests pin both, along with where a file
lives and how much of a long list is left, because that is what tells somebody
whether the right file was found.
"""

import pytest

from jarvis2.files import search


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def entry(label, folder, drive="C:"):
    return (label, f"{drive}\\{folder}\\{label}.mp3")


class TestWhereAFileIs:
    def test_a_file_in_a_user_folder_is_named_by_that_folder(self, home):
        path = str(home / "Music" / "song.mp3")

        _drive, folder = search.media_location(path)

        assert folder == "Music"

    def test_a_nested_file_is_reported_under_its_top_level_folder(self, home):
        # "Documents\2024" would be read as a folder of its own, which is not a
        # place the user thinks of.
        path = str(home / "Documents" / "2024" / "cv.pdf")

        _drive, folder = search.media_location(path)

        assert folder == "Documents"

    def test_a_file_at_the_root_of_a_drive_says_so(self, home):
        _drive, folder = search.media_location("I:\\song.mp3")

        assert folder == "drive root"

    def test_a_document_is_reported_as_a_document(self, home):
        path = str(home / "Documents" / "cv.pdf")

        _drive, folder = search.media_location(path)

        assert folder == "Documents"


class TestTheOrderIsWhatIsShown:
    def test_the_rows_carry_the_order_the_function_produced(self):
        entries = [
            entry("zebra", "Music"),
            entry("apple", "Downloads"),
            entry("mango", "Music"),
        ]

        ordered = search.order_matches(entries)

        assert ordered == [
            ("apple", entries[1][1]),
            ("mango", entries[2][1]),
            ("zebra", entries[0][1]),
        ]

    def test_the_system_drive_comes_first(self, home):
        entries = [entry("song", "Music", drive="I:"), entry("other", "Music")]

        ordered = search.order_matches(entries)

        assert ordered[0][1].startswith("C:")


class TestTheResultsView:
    def test_numbering_starts_where_it_is_asked_to(self):
        entries = [
            entry("a", "Music"),
            entry("b", "Music"),
            entry("c", "Music"),
        ]

        view = search.build_results_view(entries[1:], 2, "song", entries)

        assert [row["n"] for row in view["rows"]] == [2, 3]

    def test_the_numbering_continues_across_pages(self):
        entries = [entry(f"song {n}", "Music") for n in range(10)]

        first = search.build_results_view(entries[:3], 1, "song", entries)
        second = search.build_results_view(entries[3:6], 4, "song", entries)

        assert [row["n"] for row in first["rows"]] == [1, 2, 3]
        assert [row["n"] for row in second["rows"]] == [4, 5, 6]

    def test_what_is_hidden_is_counted(self):
        entries = [entry(f"song {n}", "Music") for n in range(10)]

        view = search.build_results_view(entries[:3], 1, "song", entries)

        assert view["total"] == 10
        assert view["remaining"] == 7

    def test_nothing_hidden_never_counts_negative(self):
        entries = [entry("only", "Music")]

        view = search.build_results_view(entries, 1, "only", entries)

        assert view["remaining"] == 0

    def test_a_file_shows_its_format_and_size(self, tmp_path):
        path = tmp_path / "song.mp3"
        path.write_bytes(b"0" * 2048)

        view = search.single_result_view("song", "song", str(path))
        row = view["rows"][0]

        assert row["ext"] == "MP3"
        assert row["size"] == "2 KB"
        assert row["path"] == str(path)

    def test_a_file_that_is_gone_says_its_size_is_unknown(self, tmp_path):
        # Never a crash, and never a size invented for a file that is not there.
        view = search.single_result_view("gone", "gone", str(tmp_path / "gone.mp3"))

        assert view["rows"][0]["size"] == "size unknown"

    def test_one_result_needs_no_choosing(self, tmp_path):
        path = tmp_path / "song.mp3"
        path.write_bytes(b"0" * 16)

        view = search.single_result_view("song", "song", str(path))

        assert view["total"] == 1
        assert view["rows"][0]["n"] == 1

    def test_where_the_files_are_is_grouped(self, home):
        entries = [
            entry("a", "Music"),
            entry("b", "Music"),
            entry("c", "Documents"),
        ]

        view = search.build_results_view(entries, 1, "song", entries)

        folders = {item["folder"]: item["count"] for item in view["locations"]}
        assert folders == {"Music": 2, "Documents": 1}
        assert "C:" in view["drives"]


class TestTheArticleView:
    def test_articles_are_shaped_like_files_so_one_renderer_draws_both(self):
        titles = ["Mercury (planet)", "Mercury (element)"]

        view = search.build_list_view(titles, 1, "mercury", 5)

        assert view["drives"] == ["Wikipedia"]
        assert [row["n"] for row in view["rows"]] == [1, 2]
        assert view["rows"][0]["label"] == "Mercury (planet)"
        assert view["rows"][0]["path"] == ""
        assert view["locations"] == []

    def test_wikipedia_order_is_kept_and_not_regrouped(self):
        # Files are grouped by folder, which would scramble an article list.
        # These have to come back in the order the site gave them.
        titles = [
            "Mercury (planet)",
            "Mercury (element)",
            "Mercury (mythology)",
        ]

        view = search.build_list_view(titles, 1, "mercury", 3)

        assert [row["label"] for row in view["rows"]] == titles

    def test_what_is_hidden_is_counted(self):
        view = search.build_list_view(["a", "b"], 1, "mercury", 5)

        assert view["total"] == 5
        assert view["remaining"] == 3

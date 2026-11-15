"""#56 black-box coverage: Finder-style search. `cmd+f`/`ctrl+f` (or File >
Find…) opens a search box; Enter opens a search tab whose listing is every
match below the folder, with a Where column; the tab's address bar toggles
the scope between that folder and This Mac (Spotlight -- stubbed here, since
the suite can't depend on a real Spotlight index). The search itself runs
on a worker thread and hands results over through a waker wake, so these
tests wait for the worker and then let that wake through, the way a real
run loop would."""

import time
from pathlib import Path

import pytest
from conftest import activate_child, click, find_row

from quadraui_files import FileManager
from quadraui_files.app import MENU_FILE_FIND_ID, SEARCH_WAKE, _key_event

ESCAPE_KEY = {"Named": "Escape"}
BACKSPACE_KEY = {"Named": "Backspace"}
CTRL_F_EVENT = {
    "KeyPressed": {
        "key": {"Char": "f"},
        "modifiers": {"shift": False, "ctrl": True, "alt": False, "meta": False},
        "repeat": False,
    }
}


@pytest.fixture
def search_tree(tmp_path: Path) -> Path:
    """Matches for "report" at three depths, one hidden in a dot folder (never
    listed, so never found), and a non-match."""
    (tmp_path / "alpha" / "deep").mkdir(parents=True)
    (tmp_path / "alpha" / "deep" / "report.txt").write_text("deep")
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "Report-final.md").write_text("final")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "q1.csv").write_text("q1")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "report.txt").write_text("hidden")
    (tmp_path / "readme.txt").write_text("hello")
    return tmp_path


def _fm(root: Path, spotlight=None) -> FileManager:
    return FileManager(root, width=160, height=30, spotlight=spotlight)


def _type(fm: FileManager, text: str) -> None:
    for ch in text:
        fm.step(_key_event({"Char": ch}))


def _settle(fm: FileManager) -> None:
    """Wait for the active tab's search worker to finish, then deliver its
    wake through the waker (a `User` payload can't be pushed directly)."""
    search = fm.cursor.search
    assert search is not None, "the active tab isn't a search"
    deadline = time.time() + 5
    while not search.done:
        assert time.time() < deadline, "search worker never finished"
        time.sleep(0.01)
    fm.app.waker().post(SEARCH_WAKE)
    fm.app.step()


def _search(fm: FileManager, query: str) -> None:
    fm.step(CTRL_F_EVENT)
    for _ in fm.edit_text:  # from a search tab the box opens on its current query
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, query)
    fm.step(_key_event({"Named": "Enter"}))
    _settle(fm)


def _results(fm: FileManager) -> list[str]:
    return [c.name for c in fm._visible_children(fm.cursor)]


def test_find_opens_a_search_tab_listing_matches_from_every_subfolder(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")

    screen = fm.app.screen()
    assert "Search: report" in screen  # the new tab's label
    assert len(fm.open) == 2 and fm.active_tab == 1
    for name in ("report.txt", "Report-final.md", "reports/"):
        assert name in screen, f"{name} missing:\n{screen}"
    assert "readme.txt" not in screen
    assert "3 found" in screen
    # The dot folder's own copy is never found: only one report.txt.
    assert _results(fm).count("report.txt") == 1


def test_results_show_where_each_one_lives(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")

    screen = fm.app.screen()
    assert "Where" in screen
    assert "alpha/deep" in screen  # relative to the folder searched from
    assert fm.app.screen_contains("beta")


def test_the_search_box_says_where_it_will_look_and_escape_cancels_it(search_tree):
    fm = _fm(search_tree)
    fm.step(CTRL_F_EVENT)
    _type(fm, "rep")

    assert f"Search in {search_tree.name}: rep" in fm.app.screen()

    fm.step(_key_event(ESCAPE_KEY))
    assert fm.edit_mode is None
    assert len(fm.open) == 1, "a cancelled search must not open a tab"


def test_find_from_a_search_tab_starts_from_its_query(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")
    fm.step(CTRL_F_EVENT)
    assert fm.edit_text == "report"


def test_file_menu_find_opens_the_same_search_box(search_tree):
    fm = _fm(search_tree)
    fm.step({"MenuActivated": MENU_FILE_FIND_ID})
    assert fm.edit_mode == "search"


def test_no_matches_says_so(search_tree):
    fm = _fm(search_tree)
    _search(fm, "zzz-nothing")

    screen = fm.app.screen()
    assert "(no results)" in screen
    assert "0 found" in screen


def test_opening_a_folder_result_navigates_and_back_returns_to_the_results(search_tree):
    fm = _fm(search_tree)
    _search(fm, "reports")

    activate_child(fm, "reports")
    assert fm.cursor.path == search_tree / "reports"
    assert "q1.csv" in fm.app.screen()
    # A real folder node, with a real parent chain for Up/breadcrumbs.
    assert fm.cursor.parent is not None and fm.cursor.parent.path == search_tree

    fm.step(_key_event(BACKSPACE_KEY))
    assert fm.cursor.search is not None
    assert "Search: reports" in fm.app.screen()


def test_opening_a_file_result_hands_it_to_the_os(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")

    activate_child(fm, "report.txt")
    assert fm.actions.opened == [str(search_tree / "alpha" / "deep" / "report.txt")]


def test_searching_again_from_a_search_tab_reuses_it(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")
    _search(fm, "q1")

    assert len(fm.open) == 2, "the second search should replace the first, not open a third tab"
    assert _results(fm) == ["q1.csv"]
    assert "Search: q1" in fm.app.screen()


def test_the_scope_toggle_switches_to_this_mac(search_tree):
    elsewhere = search_tree / "beta" / "Report-final.md"
    queries: list[str] = []

    def spotlight(query: str) -> list[str]:
        queries.append(query)
        return [str(elsewhere), str(search_tree / ".cache" / "report.txt")]

    fm = _fm(search_tree, spotlight=spotlight)
    _search(fm, "report")
    assert "This Mac" in fm.app.screen()

    click(fm, *find_row(fm, "This Mac"))
    _settle(fm)

    assert queries == ["report"]
    assert _results(fm) == ["Report-final.md"], "Spotlight's dotfile hit must be dropped"

    click(fm, *find_row(fm, f'"{search_tree.name}"'))
    _settle(fm)
    assert "report.txt" in _results(fm)


def test_this_mac_is_not_offered_without_spotlight(search_tree):
    fm = _fm(search_tree, spotlight=None)
    _search(fm, "report")
    assert "This Mac" not in fm.app.screen()


def test_closing_the_search_tab_returns_to_the_folder(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")

    fm.step(_key_event({"Char": "w"}))
    assert len(fm.open) == 1
    assert fm.cursor.path == search_tree
    assert "readme.txt" in fm.app.screen()


def test_new_folder_is_refused_in_search_results(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")
    before = sorted(p.name for p in search_tree.iterdir())

    fm.step({"MenuActivated": "file:new_folder"})

    assert sorted(p.name for p in search_tree.iterdir()) == before
    assert "can't create a folder in search results" in fm.app.screen()


def test_renaming_a_result_renames_it_on_disk_and_in_the_results(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")
    idx = _results(fm).index("report.txt")
    fm.step({"DataTable": ["fm:grid:1", {"RowSelected": {"idx": idx}}]})

    fm.step(_key_event({"Named": {"F": 2}}))
    for _ in "report.txt":
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, "report-old.txt")
    fm.step(_key_event({"Named": "Enter"}))

    assert (search_tree / "alpha" / "deep" / "report-old.txt").exists()
    assert "report-old.txt" in _results(fm)
    assert "report.txt" not in _results(fm)


def test_the_slash_filter_narrows_the_results(search_tree):
    fm = _fm(search_tree)
    _search(fm, "report")

    fm.step(_key_event({"Char": "/"}))
    _type(fm, ".md")

    assert _results(fm) == ["Report-final.md"]

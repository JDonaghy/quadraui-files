"""Core smoke set — the critical flows guarded on every change. Feature tranches
add their own black-box tests alongside these."""

from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, ENTER_KEY, _key_event


def test_app_opens_and_lists_subfolders(sample_tree):
    fm = FileManager(sample_tree)
    screen = fm.app.screen()
    assert screen.strip(), "app rendered an empty screen"
    assert "alpha" in screen
    assert "beta" in screen


def test_opening_a_folder_shows_its_files(sample_tree):
    fm = FileManager(sample_tree)
    # select the first subfolder, open it (navigates the tab in place)
    for event in (_key_event(DOWN_KEY), _key_event(ENTER_KEY)):
        fm.app.push_event(event)
        fm.app.step()
    screen = fm.app.screen()
    assert "notes.txt" in screen, f"alpha's file not shown; screen was:\n{screen}"

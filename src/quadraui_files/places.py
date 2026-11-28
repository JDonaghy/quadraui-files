"""Per-OS sidebar places -> `(Place, PlaceSection)` descriptors.

The sidebar is navigation only, like Finder's: `default_sections` picks
Finder's own default sidebar on macOS, Explorer's on Windows, Nautilus's
elsewhere -- decided by the host OS, not the backend, so the TUI on a Mac
shows Finder's places too. Framework-free -- no `quadraui` import.
`quadraui_files.app` re-exports every public name here; tests keep
importing them from there.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Place:
    """One sidebar entry: a folder the platform's own file manager pins
    there (Desktop, Downloads, a mounted volume, ...). `codicon` must be in
    quadraui's curated subset (`codicon_names::NAMES` -- ~50 names, no
    home/cloud/drive/download glyphs yet -- JDonaghy/quadraui#2449), so
    some icons are stand-ins. An unknown name only raises on the second
    rendered frame (JDonaghy/quadraui#2450)."""

    label: str
    path: Path
    codicon: str
    # Painted instead of the codicon when nerd fonts are off (the TUI's
    # default): a single-width symbol any terminal font has, so places stay
    # distinguishable at a glance without one.
    fallback: str = "▪"


@dataclass(frozen=True)
class PlaceSection:
    """A titled, collapsible group of `Place`s."""

    title: str
    places: tuple[Place, ...]


def _existing(places: list[Place]) -> tuple[Place, ...]:
    """`places` minus any whose folder doesn't exist on this machine (no
    iCloud, no `~/Music`, an unmounted drive...)."""
    return tuple(p for p in places if p.path.is_dir())


def _mac_volumes() -> list[Place]:
    """Finder's Locations: every volume under `/Volumes`. The boot volume
    shows up there as a symlink back to `/` -- it keeps its own name
    ("Macintosh HD") but browses `/` itself, as Finder's does."""
    volumes: list[Place] = []
    try:
        entries = sorted(Path("/Volumes").iterdir(), key=lambda p: p.name.lower())
    except OSError:
        entries = []
    boot: list[Place] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            is_boot = entry.resolve() == Path("/")
        except OSError:
            continue
        if is_boot:
            boot.append(Place(entry.name, Path("/"), "root-folder", "▣"))
        else:
            volumes.append(Place(entry.name, entry, "database", "▤"))
    if not boot:
        boot.append(Place("Macintosh HD", Path("/"), "root-folder", "▣"))
    return boot + volumes


def _mac_sections(home: Path) -> list[PlaceSection]:
    """Finder's default sidebar (AirDrop/Recents/Tags left out: they are
    searches and services, not folders)."""
    sections = [
        PlaceSection(
            "Favorites",
            _existing([
                Place("Applications", Path("/Applications"), "package", "◆"),
                Place("Desktop", home / "Desktop", "layout", "▭"),
                Place("Documents", home / "Documents", "files", "≡"),
                Place("Downloads", home / "Downloads", "folder", "↓"),
                Place(home.name, home, "account", "⌂"),
            ]),
        ),
        PlaceSection(
            "iCloud",
            _existing([
                Place("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs", "sync", "○"),
            ]),
        ),
        PlaceSection("Locations", _existing(_mac_volumes())),
    ]
    return [s for s in sections if s.places]


def _windows_sections(home: Path) -> list[PlaceSection]:
    """Explorer's navigation pane: Quick access's default pins, then This
    PC's drives."""
    drives: list[Place] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if root.exists():
            drives.append(Place(f"Local Disk ({letter}:)" if letter == "C" else f"{letter}:", root, "database", "▤"))
    sections = [
        PlaceSection(
            "Quick access",
            _existing([
                Place("Home", home, "account", "⌂"),
                Place("Desktop", home / "Desktop", "layout", "▭"),
                Place("Downloads", home / "Downloads", "folder", "↓"),
                Place("Documents", home / "Documents", "files", "≡"),
                Place("Pictures", home / "Pictures", "file-media", "▨"),
                Place("Music", home / "Music", "file-media", "♪"),
                Place("Videos", home / "Videos", "file-media", "►"),
            ]),
        ),
        PlaceSection("This PC", tuple(drives)),
    ]
    return [s for s in sections if s.places]


def _linux_sections(home: Path) -> list[PlaceSection]:
    """Nautilus's sidebar: the XDG user folders, then the computer itself
    and whatever removable media is mounted for this user."""
    user = home.name
    mounts: list[Place] = [Place("Computer", Path("/"), "root-folder", "▣")]
    for base in (Path("/media") / user, Path("/run/media") / user):
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        mounts.extend(Place(e.name, e, "database", "▤") for e in entries if e.is_dir())
    sections = [
        PlaceSection(
            "Places",
            _existing([
                Place("Home", home, "account", "⌂"),
                Place("Desktop", home / "Desktop", "layout", "▭"),
                Place("Documents", home / "Documents", "files", "≡"),
                Place("Downloads", home / "Downloads", "folder", "↓"),
                Place("Music", home / "Music", "file-media", "♪"),
                Place("Pictures", home / "Pictures", "file-media", "▨"),
                Place("Videos", home / "Videos", "file-media", "►"),
            ]),
        ),
        PlaceSection("Devices", _existing(mounts)),
    ]
    return [s for s in sections if s.places]


def default_sections(platform: str | None = None, home: Path | None = None) -> list[PlaceSection]:
    """The sidebar the host OS's own file manager would show -- Finder's on
    macOS, Explorer's on Windows, Nautilus's elsewhere. Decided by the host
    OS, not the backend: the TUI on a Mac shows Finder's places too."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "darwin":
        return _mac_sections(home)
    if platform == "win32":
        return _windows_sections(home)
    return _linux_sections(home)

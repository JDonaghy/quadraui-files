"""quadraui-files — a cross-backend file manager built on quadraui's Python
bindings. The same descriptor code runs on the TUI and as a native desktop
window; only the final `run_*` call differs per platform.

Seeded from quadraui-py's `examples/file_manager.py` and grown into a
standalone, coord-managed demo (the flagship "prototype in your terminal,
ship a native GUI for free" showcase)."""

__all__ = ["FileManager", "Node", "build_root"]
__version__ = "0.1.0"


def __getattr__(name: str):
    """Lazily resolves `FileManager`/`Node`/`build_root` from `.app` on first
    access, instead of importing `.app` (and so `quadraui`) at package-import
    time -- `quadraui_files.fs`/`.search`/`.places`/`.tags` are framework-free
    and have to stay importable with no `quadraui` wheel installed at all
    (see those modules' own docs), which an eager `from .app import ...`
    here would break: importing any submodule of this package runs this
    file first, regardless of which submodule was asked for."""
    if name in __all__:
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

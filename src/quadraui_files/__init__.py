"""quadraui-files — a cross-backend file manager built on quadraui's Python
bindings. The same descriptor code runs on the TUI and as a native desktop
window; only the final `run_*` call differs per platform.

Seeded from quadraui-py's `examples/file_manager.py` and grown into a
standalone, coord-managed demo (the flagship "prototype in your terminal,
ship a native GUI for free" showcase)."""

from .app import FileManager, Node, build_root

__all__ = ["FileManager", "Node", "build_root"]
__version__ = "0.1.0"

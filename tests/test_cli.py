"""The console entry point's `--native` guard: on a quadraui build with no
native backend compiled in, the CLI explains how to rebuild instead of
crashing with an `AttributeError` on `run_native`."""

from quadraui_files import cli


class _TerminalOnlyQuiApp:
    """Stands in for a `QuiApp` class compiled without a native feature,
    which has no `run_native` attribute at all."""


def test_native_on_a_terminal_only_build_prints_the_rebuild_hint(sample_tree, monkeypatch, capsys):
    monkeypatch.setattr(cli, "QuiApp", _TerminalOnlyQuiApp)

    assert cli.main([str(sample_tree), "--native"]) == 2

    err = capsys.readouterr().err
    assert "terminal-only" in err
    assert f'MATURIN_PEP517_ARGS="--features {cli._NATIVE_FEATURE}"' in err
    assert "--no-cache-dir" in err
    assert "quadraui.git@" in err
    assert "--tui" in err

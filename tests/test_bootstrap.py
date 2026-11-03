"""The environment bootstrap: `. .venv/bin/activate && pytest -q` -- the command
automated runners execute against a bare checkout -- has to work with nothing
provisioned. These tests drive the real shell entry points, so they guard the
tracked `.venv/bin/activate` against being deleted, re-ignored, or broken.

`PYTHON` is pinned to the interpreter running this suite, which already has
`quadraui` + `pytest`, so the bootstrap resolves on its first branch and never
builds anything.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVATE = REPO_ROOT / ".venv" / "bin" / "activate"


def _sh(script: str, cwd: Path, **env_extra: str) -> subprocess.CompletedProcess:
    """Run `script` under /bin/sh -- the shell automated runners use."""
    env = {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin",
        "PYTHON": sys.executable,
        **env_extra,
    }
    return subprocess.run(
        ["/bin/sh", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_activate_is_present_in_the_checkout():
    """A fresh clone/worktree must already have the file runners source."""
    assert ACTIVATE.is_file(), f"{ACTIVATE} missing from the checkout"
    inside_git = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if inside_git.returncode != 0:
        pytest.skip("not a git work tree, so tracking cannot be checked")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".venv/bin/activate"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, "`.venv/bin/activate` is not tracked by git"


def test_sourcing_activate_puts_the_dependencies_on_path():
    """The runner's command shape: source, then run a bare `python`/`pytest`."""
    done = _sh(
        '. .venv/bin/activate && python -c "import quadraui, pytest; print(\'deps ok\')"'
        " && pytest --version >/dev/null && echo 'pytest ok'",
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0, f"stdout={done.stdout!r} stderr={done.stderr!r}"
    assert "deps ok" in done.stdout
    assert "pytest ok" in done.stdout


def test_sourcing_activate_is_idempotent_and_reversible():
    done = _sh(
        'before=$PATH; . .venv/bin/activate; . .venv/bin/activate;'
        ' [ "$PATH" != "$before" ] && echo activated;'
        ' deactivate; [ "$PATH" = "$before" ] && echo restored',
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0, f"stderr={done.stderr!r}"
    assert "activated" in done.stdout
    assert "restored" in done.stdout


def test_sourcing_activate_outside_the_checkout_fails_loudly(tmp_path):
    """Sourced where the repo can't be found, it reports why instead of
    silently leaving the caller with no environment."""
    done = _sh(f". {ACTIVATE} && echo should-not-get-here", cwd=tmp_path)
    assert done.returncode != 0
    assert "should-not-get-here" not in done.stdout
    assert "QUADRAUI_FILES_ROOT" in done.stderr


def test_bootstrap_env_prints_a_usable_interpreter():
    """`scripts/bootstrap-env.sh` prints only the interpreter path on stdout,
    so callers can use `$(sh scripts/bootstrap-env.sh)` directly."""
    done = _sh("sh scripts/bootstrap-env.sh", cwd=REPO_ROOT)
    assert done.returncode == 0, f"stderr={done.stderr!r}"
    printed = done.stdout.strip()
    assert printed == sys.executable, f"expected {sys.executable}, got {printed!r}"


def test_test_sh_runs_the_suite_from_a_bare_checkout():
    """`scripts/test.sh` forwards arguments to pytest in the resolved env."""
    done = _sh("sh scripts/test.sh tests/test_smoke.py -q", cwd=REPO_ROOT)
    assert done.returncode == 0, f"stdout={done.stdout!r} stderr={done.stderr!r}"
    assert "passed" in done.stdout

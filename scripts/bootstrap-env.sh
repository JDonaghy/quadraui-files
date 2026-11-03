#!/bin/sh
# Resolve an environment the black-box suite can run in, and print the absolute
# path of its Python interpreter on stdout. Progress goes to stderr, so callers
# can use the stdout value directly:
#
#     python=$(sh scripts/bootstrap-env.sh)
#
# Why this exists: `quadraui` is compiled from source, so it only ever lives in
# a virtualenv -- a bare `pytest` in a fresh clone or git worktree cannot import
# it. Automated runners check out a clean worktree and run a single command, so
# the environment has to be established rather than assumed to exist. Both
# entry points share this resolver: `scripts/test.sh` and the sourceable
# `.venv/bin/activate` bootstrap.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

PYTHON=${PYTHON:-python3}

# Both halves of a runnable suite: the binding under test and the runner.
has_deps() {
    "$1" -c 'import quadraui, pytest' >/dev/null 2>&1
}

# 1. An already-usable ambient environment (a developer with
#    `. .venv/bin/activate` live, or CI right after `pip install -e ".[dev]"`)
#    is used as-is -- never rebuilt behind the caller's back.
if has_deps "$PYTHON"; then
    "$PYTHON" -c 'import sys; print(sys.executable)'
    exit 0
fi

# 2. A provisioned in-tree virtualenv, the layout the README documents.
if [ -x .venv/bin/python ] && has_deps .venv/bin/python; then
    echo "$repo_root/.venv/bin/python"
    exit 0
fi

# 3. Otherwise bootstrap a virtualenv shared by every worktree on this machine,
#    keyed by the pinned quadraui commit: a new pin builds once into a new
#    venv, an unchanged pin reuses that build. Keyed because building
#    quadraui-py is a multi-minute Rust compile that must not repeat per
#    worktree.
requirement=$(sed -n 's/^[[:space:]]*"\(quadraui @ git+[^"]*\)".*/\1/p' pyproject.toml | head -n 1)
if [ -z "$requirement" ]; then
    echo "bootstrap-env.sh: no 'quadraui @ git+...' dependency in pyproject.toml" >&2
    exit 1
fi
pin=$(printf '%s' "$requirement" | sed -n 's/.*quadraui\.git@\([0-9A-Za-z]*\).*/\1/p')
if [ -z "$pin" ]; then
    echo "bootstrap-env.sh: no pinned quadraui commit in: $requirement" >&2
    exit 1
fi

cache_home=${XDG_CACHE_HOME:-$HOME/.cache}
venv=${QUADRAUI_FILES_VENV:-$cache_home/quadraui-files/venv-$pin}

# `pyvenv.cfg` is what makes the interpreter below resolve to this prefix; a
# `bin/python` without it would quietly install into the system environment.
if [ ! -x "$venv/bin/python" ] || [ ! -f "$venv/pyvenv.cfg" ]; then
    echo "bootstrap-env.sh: creating $venv" >&2
    "$PYTHON" -m venv "$venv"
    "$venv/bin/python" -m pip install --quiet --upgrade pip >&2
fi

if ! "$venv/bin/python" -c 'import quadraui' >/dev/null 2>&1; then
    # Keep the Rust artifacts out of pip's throwaway build directory so the
    # next bootstrap (a new pin, or a wiped venv) links against a warm cache.
    CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$cache_home/quadraui-files/cargo}
    export CARGO_TARGET_DIR
    echo "bootstrap-env.sh: building $requirement (Rust compile, several minutes)" >&2
    "$venv/bin/python" -m pip install --quiet "$requirement" >&2
fi

if ! "$venv/bin/python" -c 'import pytest' >/dev/null 2>&1; then
    # Only dependencies go in the shared venv -- never this project, whose
    # editable install would pin one worktree's path for all the others. pytest
    # reaches `src/` through `pythonpath` in pyproject.toml instead.
    "$venv/bin/python" -m pip install --quiet "pytest>=8" >&2
fi

echo "$venv/bin/python"

#!/bin/sh
# Test entry point that works from a bare checkout: resolve (or build) an
# environment with `quadraui` importable, then run the black-box suite in it.
# Arguments are forwarded to pytest.
#
# Usage: sh scripts/test.sh [pytest args...]        (default args: -q)
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

python=$(sh "$repo_root/scripts/bootstrap-env.sh")

if [ "$#" -eq 0 ]; then
    set -- -q
fi

echo "scripts/test.sh: $python -m pytest $*" >&2
exec "$python" -m pytest "$@"

#!/bin/sh
# The two takes the demo records, typed out at a readable speed. Run under asciinema by
# `make demo`; tools/demo_setup.sh has already built the repo this runs in.
set -eu
DEMO=${DEMO:-/tmp/jev-commit-demo}

type_out() {
  printf '\033[38;5;245m$\033[0m '
  i=1
  while [ "$i" -le "${#1}" ]; do
    printf '%s' "$(printf '%s' "$1" | cut -c "$i")"
    sleep 0.035
    i=$((i + 1))
  done
  printf '\n'
  sleep 0.4
}

cd "$DEMO"
sleep 1
type_out "git commit -m 'fix: null check in parser'"
git commit -m 'fix: null check in parser' || true
sleep 4

# Take two asks about a different diff, so the fake answers from a different fixture file.
ROOT=$(cd "$(dirname "$0")/.." && pwd)
pkill -f "fake_jev.py" 2>/dev/null || true
FAKE_JEV_FIXTURES="$ROOT/tools/fixtures-secret.json" PORT=${PORT:-4398} python3 "$ROOT/tools/fake_jev.py" 2>/dev/null &
sleep 1

printf '\n'
type_out "git add deploy_key && git commit -m 'chore: add the deploy key'"
git add deploy_key
git commit -m 'chore: add the deploy key' || true
sleep 4

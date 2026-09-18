#!/bin/sh
# The two takes the demo records: a message that does not match its diff, then a staged
# private key. Run under asciinema by `make demo`; tools/demo_setup.sh built the repo.
# Timings are tuned for a muted autoplay: nothing on screen sits still for more than a beat.
set -eu
DEMO=${DEMO:-/tmp/jev-commit-demo}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export JEV_COMMIT_DEMO_PACE=${JEV_COMMIT_DEMO_PACE:-0.02}

DIM='\033[38;5;245m'
OFF='\033[0m'

say() {
  printf "${DIM}# %s${OFF}\n" "$1"
  sleep 0.7
}

type_out() {
  printf "${DIM}\$${OFF} "
  i=1
  while [ "$i" -le "${#1}" ]; do
    printf '%s' "$(printf '%s' "$1" | cut -c "$i")"
    sleep 0.022
    i=$((i + 1))
  done
  printf '\n'
  sleep 0.3
}

cd "$DEMO"
clear
sleep 0.8

say "the message says one thing. the diff does three."
type_out "git commit -m 'fix: null check in parser'"
git commit -m 'fix: null check in parser' || true
sleep 3

# Take two asks about a different diff, so the fake answers from a different fixture file.
# Against the real gateway the fixtures are unused and this is a no-op.
if pgrep -f fake_jev.py > /dev/null 2>&1; then
  pkill -f "fake_jev.py" 2>/dev/null || true
  FAKE_JEV_FIXTURES="$ROOT/tools/fixtures-secret.json" PORT=${PORT:-4398} \
    python3 "$ROOT/tools/fake_jev.py" 2>/dev/null &
  sleep 1
fi

clear
sleep 0.5
say "and the one mistake you cannot take back."
type_out "git add deploy_key && git commit -m 'chore: add the deploy key'"
git add deploy_key
git commit -m 'chore: add the deploy key' || true
sleep 3

printf '\n'
printf "${DIM}# one call per commit. it warns, the belt blocks.${OFF}\n"
printf "${DIM}# github.com/valentynkit/jev-commit${OFF}\n"
sleep 2

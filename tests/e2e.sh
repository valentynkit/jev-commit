#!/bin/sh
# End to end: install the hook through the pre-commit framework in a scratch repo and
# commit twice, once on a lying message and once on a staged private key.
#
# Two local workarounds, both from Known limits rather than around them: pre-commit refuses
# to install while core.hooksPath is set, so the install runs with the global config out of
# the way, and this machine's global core.hooksPath is overridden per commit.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCRATCH=${SCRATCH:-/tmp/jev-commit-e2e}
PORT=${PORT:-4399}
GIT="git -c core.hooksPath=.git/hooks -c user.name=t -c user.email=t@t -c commit.gpgsign=false"

rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/hook" "$SCRATCH/app"

tar --exclude .git --exclude __pycache__ --exclude .pytest_cache -cf - -C "$ROOT" . | tar -xf - -C "$SCRATCH/hook"
(cd "$SCRATCH/hook" && git init -q && $GIT add -A && $GIT commit -q -m hook --no-verify)
REV=$(git -C "$SCRATCH/hook" rev-parse HEAD)

FAKE_JEV_FIXTURES="$ROOT/tools/fixtures.json" PORT="$PORT" python3 "$ROOT/tools/fake_jev.py" &
FAKE=$!
trap 'kill $FAKE 2>/dev/null || true' EXIT
sleep 1

cd "$SCRATCH/app"
git init -q
cat > .pre-commit-config.yaml <<YAML
repos:
  - repo: $SCRATCH/hook
    rev: $REV
    hooks:
      - id: jev-commit
YAML
mkdir -p src
printf 'def parse(text):\n    return text.split()\n' > src/parser.py
$GIT add -A
$GIT commit -q -m "chore: start" --no-verify
GIT_CONFIG_GLOBAL=/dev/null pre-commit install --hook-type commit-msg >/dev/null

export JEV_BASE_URL="http://127.0.0.1:$PORT"

echo "--- take one: the message names one change, the diff does three"
printf 'def parse(text):\n    print("here", text)\n    if text is None:\n        return None\n    return text.split()\n' > src/parser.py
printf 'def endpoint(request):\n    return {"ok": True}\n' > src/api.py
$GIT add -A
set +e
$GIT commit -m "fix: null check in parser"
ONE=$?
set -e
test "$ONE" -eq 0 || { echo "take one should have landed, exit $ONE"; exit 1; }
echo "take one exit $ONE, commit landed: $($GIT log -1 --pretty=%s)"

echo
echo "--- take two: a private key is staged"
printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn\n-----END OPENSSH PRIVATE KEY-----\n' > deploy_key
$GIT add -A
set +e
$GIT commit -m "chore: add the deploy key"
TWO=$?
set -e
test "$TWO" -ne 0 || { echo "take two should have been blocked"; exit 1; }
echo "take two exit $TWO, head is still: $($GIT log -1 --pretty=%s)"

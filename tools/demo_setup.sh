#!/bin/sh
# Builds the repo the demo records in: a scratch git repo with jev-commit installed as a
# plain commit-msg hook, and a fake Jev behind it so the take costs nothing and never varies.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEMO=${DEMO:-/tmp/jev-commit-demo}
PORT=${PORT:-4398}
BASE=${JEV_BASE_URL:-http://127.0.0.1:$PORT}

pkill -f "fake_jev.py" 2>/dev/null || true
rm -rf "$DEMO"
mkdir -p "$DEMO/src"
cd "$DEMO"
git init -q
git config core.hooksPath .git/hooks
git config user.name "you"
git config user.email "you@example.com"
git config commit.gpgsign false

printf 'def parse(text):\n    return text.split()\n' > src/parser.py
git add -A
git commit -q -m "chore: start"

cat > .git/hooks/commit-msg <<HOOK
#!/bin/sh
JEV_BASE_URL=$BASE PYTHONPATH=$ROOT exec python3 -m jev_commit.cli "\$1"
HOOK
chmod +x .git/hooks/commit-msg

# The change the demo commits: one claim in the message, three changes in the diff.
printf 'def parse(text):\n    print("HERE", text)\n    if text is None:\n        return None\n    return text.split()\n' > src/parser.py
printf 'def endpoint(request):\n    return {"ok": True}\n' > src/api.py
git add -A
printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn\n-----END OPENSSH PRIVATE KEY-----\n' > deploy_key

if [ "$BASE" = "http://127.0.0.1:$PORT" ]; then
  FAKE_JEV_FIXTURES="$ROOT/tools/fixtures.json" PORT="$PORT" python3 "$ROOT/tools/fake_jev.py" 2>/dev/null &
  sleep 1
fi
clear

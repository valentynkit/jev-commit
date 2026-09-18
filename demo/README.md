# Recording the demo

Two takes in one session: a commit whose message does not match its diff (three findings,
commit lands), then a staged private key (belt hit, commit refused). `demo.gif` goes in the
README, `demo.mp4` goes to X.

    make demo

That is `tools/demo_setup.sh` (scratch repo, fake Jev), `asciinema rec`, then `agg` twice:
once at font 18 for the gif, once at font 28 for the video. Re-render without re-recording
by deleting only the target:

    rm -f demo.gif && make demo.gif

Re-record from scratch:

    rm -f /tmp/jev-commit-demo.cast demo.gif demo.mp4 && make demo

## What the pieces do

| | |
|---|---|
| `tools/demo_setup.sh` | builds `/tmp/jev-commit-demo`, installs the hook, stages the diff and writes `deploy_key` |
| `tools/demo_script.sh` | types the two commands, `clear` between takes, end card last |
| `JEV_COMMIT_DEMO_PACE` | seconds per bar cell. `0.02` while recording, `0.006` in real use |
| `--cols 72` | the widest frame still legible on a phone timeline |
| `--crop 0,0-0,420` | asciinema ignores `--rows` with no tty, so the empty rows come off after |
| `--theme kanagawa` | agg ships it; it is the same palette as the terminal, unforked |

## Real numbers

The fake backend answers in about 25 ms, which is not a Jev latency. For a take with real
numbers on screen, start the gateway shim and point the hook at it:

    cd ~/Projects/mine/jev-lab/tools/jev-proxy && AI_GATEWAY_API_KEY=... npm start
    JEV_BASE_URL=http://127.0.0.1:4322 make demo

Anything recorded that way is measured through the shim, not the direct API, and the post
has to say so. As of 2026-09-19 the gateway account is on the free tier and answers every
request with HTTP 429, so the committed takes are fake-backed and the latency and cost on
screen are placeholders.

## Without a key

`make demo` needs no key and no network: `tools/demo_setup.sh` starts `tools/fake_jev.py`
with `tools/fixtures.json` for take one and `tools/fixtures-secret.json` for take two. Edit
those two files to change what the bars say.

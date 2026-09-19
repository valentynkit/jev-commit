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

The fake backend answers in about 20 ms, which is not a Jev latency, so the latency and the
cost in the committed takes are placeholders. For a recording with real numbers, point the
hook at a real endpoint and record again:

    JEV_BASE_URL=https://api.typesafe.ai TYPESAFE_API_KEY=... make demo

Anything recorded through a proxy rather than the API says so wherever the number is used.

## Without a key

`make demo` needs no key and no network: `tools/demo_setup.sh` starts `tools/fake_jev.py`
with `tools/fixtures.json` for take one and `tools/fixtures-secret.json` for take two. Edit
those two files to change what the bars say.

# pytest comes from an ephemeral uv env; the hook itself has no dependencies.
PY ?= uv run --no-project --with pytest python
SCRATCH ?= /tmp/jev-commit-scratch

.PHONY: test e2e try-repo measure fixtures demo clean

test:
	$(PY) -m pytest -q

e2e:
	./tests/e2e.sh

try-repo:
	rm -rf $(SCRATCH)/repo && mkdir -p $(SCRATCH)/repo
	tar --exclude .git --exclude __pycache__ --exclude .pytest_cache -cf - . | tar -xf - -C $(SCRATCH)/repo
	git -C $(SCRATCH)/repo init -q
	git -C $(SCRATCH)/repo add -A
	git -C $(SCRATCH)/repo -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m skeleton --no-verify
	printf 'fix: null check in parser\n' > $(SCRATCH)/msg
	pre-commit try-repo $(SCRATCH)/repo jev-commit --hook-stage commit-msg --commit-msg-filename $(SCRATCH)/msg

measure:
	$(PY) -m jev_commit.measure

fixtures:
	$(PY) -m jev_commit.record

# vhs 0.12.0 renders blank frames against ffmpeg 9 on macOS, so the demo takes
# research/04's other path: a real session under asciinema, converted by agg.
demo:
	sh tools/demo_setup.sh
	asciinema rec --cols 100 --rows 26 --overwrite -c "sh $$PWD/tools/demo_script.sh" /tmp/jev-commit-demo.cast
	agg --font-size 18 --idle-time-limit 2 --fps-cap 15 --theme asciinema /tmp/jev-commit-demo.cast demo.gif
	ls -lh demo.gif

clean:
	rm -rf .pytest_cache jev_commit/__pycache__ tests/__pycache__ measure.json

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
# the other path: a real session under asciinema, converted by agg.
# 72 columns is the widest frame still legible on a phone timeline. asciinema ignores --rows
# with no tty, so both renders crop the empty rows off the bottom. demo/README.md has the rest.
CAST ?= /tmp/jev-commit-demo.cast

demo: $(CAST) demo.gif demo.mp4

$(CAST):
	sh tools/demo_setup.sh
	asciinema rec --cols 72 --rows 16 --overwrite -c "sh $$PWD/tools/demo_script.sh" $(CAST)

demo.gif: $(CAST)
	agg --font-size 18 --line-height 1.3 --idle-time-limit 2 --fps-cap 20 --theme kanagawa $(CAST) /tmp/jev-commit-demo.gif
	gifsicle --crop 0,0-0,420 --colors 256 -O3 --lossy=40 /tmp/jev-commit-demo.gif -o demo.gif
	ls -lh demo.gif

# X wants an even-sized H.264; agg renders at 2x and ffmpeg pads it to 1280x720.
demo.mp4: $(CAST)
	agg --font-size 28 --line-height 1.3 --idle-time-limit 2 --fps-cap 30 --theme kanagawa $(CAST) /tmp/jev-commit-demo-2x.gif
	ffmpeg -y -loglevel error -i /tmp/jev-commit-demo-2x.gif \
		-vf "crop=iw:654:0:0,scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x1f1f28,format=yuv420p" \
		-r 30 -c:v libx264 -preset slow -crf 20 -movflags +faststart demo.mp4
	ls -lh demo.mp4

clean:
	rm -rf .pytest_cache jev_commit/__pycache__ tests/__pycache__ measure.json

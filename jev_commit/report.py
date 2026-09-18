"""The stderr report: a header, a spinner that resolves into the real cost, five bars.

This is the surface people see, so it shows the Jev call happening rather than printing a
verdict out of nowhere. Every number in it is measured: the file and line counts come from
the diff, the milliseconds from a monotonic clock around the request, the dollars from the
usage the response reports. Under NO_COLOR or a non-TTY it degrades to the same lines in
plain text with no animation and no cursor tricks.
"""

import itertools
import os
import shutil
import sys
import threading
import time

BAR_CELLS = 12  # 20 cells pushed a flag row to 57 columns, which wrapped at 60
LABEL_WIDTH = 22
FULL, EMPTY = "█", "░"
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
DOT = " · "
MARKS = {"ok": "", "warn": "?", "flag": "✗"}

# Seconds per bar cell. Five rows of 12 cells is 0.36 s of fill, which reads as the answers
# landing rather than as a wait. JEV_COMMIT_DEMO_PACE slows it down for the screen capture.
PACE = 0.006

GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)

DEAD_BAND = (0.30, 0.70)
PRICE_PER_MTOK = 0.042


def cost_of(usage):
    return (usage.get("input_tokens") or 0) * PRICE_PER_MTOK / 1_000_000


def status_of(probability, finding_at, healthy_high):
    """ok, warn in the dead band, flag past the finding threshold.

    The band is checked against `signal`, the same direction-adjusted number the flag uses.
    Reading raw `probability` here only agreed by accident, because (0.30, 0.70) happens to
    be symmetric about 0.5; any swept band would have dead-banded one question backwards.
    """
    signal = 1 - probability if healthy_high else probability
    if signal >= finding_at:
        return "flag"
    if 1 - DEAD_BAND[1] <= signal <= 1 - DEAD_BAND[0]:
        return "warn"
    return "ok"


class Report:
    def __init__(self, stream=None, env=None):
        env = os.environ if env is None else env
        self.out = stream or sys.stderr
        # NO_COLOR is presence, not value: NO_COLOR= with an empty value still counts.
        self.color = (
            "NO_COLOR" not in env and hasattr(self.out, "isatty") and self.out.isatty()
        )
        self.animate = self.color
        self.pace = _pace(env.get("JEV_COMMIT_DEMO_PACE"))
        self._spinner = None
        self._stop = None

    def _paint(self, text, code):
        return code + text + RESET if self.color else text

    def _write(self, text):
        self.out.write(text)
        self.out.flush()

    def line(self, text=""):
        self._write(text + "\n")

    def header(self, files, added, removed, tokens, requests):
        parts = [
            self._paint("jev-commit", BOLD),
            "%d file%s" % (files, "" if files == 1 else "s"),
            "%s %s"
            % (self._paint("+%d" % added, GREEN), self._paint("−%d" % removed, RED)),
            "~%s tokens" % _short(tokens),
            "%d request%s" % (requests, "" if requests == 1 else "s"),
        ]
        self.line(DOT.join(parts) if self.color else " · ".join(parts))

    def asking(self, model):
        self.stop_spinner()  # two live spinners painted the same line at once
        label = "asking %s " % model
        if not self.animate:
            self.line(self._paint(label + "...", DIM))
            return
        self._stop = threading.Event()

        def spin():
            for frame in itertools.cycle(FRAMES):
                if self._stop.is_set():
                    return
                self._write("\r\033[2K" + self._paint(label + frame, DIM))
                time.sleep(0.08)

        self._spinner = threading.Thread(target=spin, daemon=True)
        self._spinner.start()

    def stop_spinner(self):
        """Safe to call twice, and safe when asking() never ran."""
        if self._spinner:
            self._stop.set()
            self._spinner.join()
            self._spinner = None
            self._write("\r\033[2K")

    def resolved(self, model, ms, dollars):
        self.stop_spinner()
        parts = [self._paint(model, BOLD), "%d ms" % ms, "$%.5f" % dollars]
        self.line(DOT.join(parts) if self.color else " · ".join(parts))
        self.line()

    def check(self, label, risk, status):
        """`risk` is direction-adjusted, so a long bar means a problem on every row."""
        filled = max(0, min(BAR_CELLS, round(risk * BAR_CELLS)))
        code = {"ok": GREEN, "warn": YELLOW, "flag": RED}[status]
        if not (self.animate and self.pace):
            self.line(self._row(label, filled, risk, status, code))
            return
        for cells in range(filled + 1):
            self._write("\r\033[2K" + self._row(label, cells, risk, status, code))
            time.sleep(self.pace)
        self.line()

    def _row(self, label, cells, risk, status, code):
        bar = FULL * cells + EMPTY * (BAR_CELLS - cells)
        mark = MARKS[status]  # an ok row ends at the number, with no trailing pad
        return (
            "  %-*s %s %5.2f  %s"
            % (
                LABEL_WIDTH,
                label,
                self._paint(bar, code),
                risk,
                self._paint(mark, code) if mark else "",
            )
        ).rstrip()

    def blocked_line(self, kind, path, redacted):
        self.line(
            "  "
            + self._paint(
                "blocked  %s in %s (%s)" % (kind.replace("_", " "), path, redacted), RED
            )
        )

    def verdict(self, text, level):
        code = {"ok": GREEN, "warn": YELLOW, "flag": RED}[level]
        self.line()
        self.line("  " + self._paint(text, code))

    def note(self, text):
        self.line("  " + self._paint(text, DIM))

    def skipped(self, reason):
        self.line(self._paint("jev-commit: skipped (%s)" % reason, DIM))


def _pace(raw):
    """Seconds per cell from the env, clamped. A junk value falls back to the default."""
    try:
        return min(0.2, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return PACE


def _short(count):
    return "%.1fk" % (count / 1000) if count >= 1000 else str(count)

"""An interactive drill session: one exercise at a time, checked on every save."""

from __future__ import annotations

import random
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time
from collections import deque
from pathlib import Path

from . import term
from .complexity import CLASSES, Measurement, measure, report
from .exercises import Exercise
from .library import Collection
from .langs import Language, Outcome
from .store import INTERVALS, Card, Store, grade, pick
from .term import bold, cyan, dim, fmt_time, green, red, yellow

KEYS_HELP = "[h]int [s]kip [p]ause [r]erun [o]pen [q]uit"
COMPLEXITY_KEY = "[c]omplexity "


def open_in_editor(editor: str, path: Path) -> bool:
    """Open `path` in the editor, without waiting for it. False if it cannot start."""
    try:
        subprocess.Popen(
            [*shlex.split(editor), str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        term.say(red(f"Cannot start the editor ({e}); open {path} yourself."))
        return False
    return True


def level_note(before: Card | None, after: Card, reason: str) -> str:
    """What an attempt did to the exercise's level, and when it comes back."""
    move = f"level {before.box} → {after.box}" if before else f"new → level {after.box}"
    if after.box == 0:
        return f"{reason}: {move}, it comes back later in this session."
    days = INTERVALS[after.box]
    return f"{reason}: {move}, next review in {days} day{'s' if days > 1 else ''}."


def grade_reason(seconds: float, target: float, hinted: bool, skipped: bool) -> str:
    result = grade(seconds, target, hinted, skipped)
    if skipped:
        return "Skipped"
    if result == "fail":
        return "Over twice the target"
    if hinted:
        return "Hint used"
    return "Over the target" if result == "ok" else "Within the target"


def clip(text: str, width: int = 160) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def explanation_lines(ex: Exercise) -> list[str]:
    """The exercise's theory, wrapped to the terminal. Lists and indented lines are kept."""
    if not ex.explanation:
        return []
    width = max(40, min(100, shutil.get_terminal_size().columns - 4))
    lines = [cyan("Why")]
    for paragraph in textwrap.dedent(ex.explanation).strip().split("\n\n"):
        raw = paragraph.splitlines()
        if any(line.startswith(("-", " ", "*")) for line in raw):
            lines += ["  " + line for line in raw]
        else:
            lines += ["  " + line for line in textwrap.wrap(" ".join(paragraph.split()), width)]
        lines.append("")
    return lines


def failure_lines(ex: Exercise, lang: Language, outcome: Outcome) -> list[str]:
    """Explain why a run failed: the error, or the first failing test."""
    if outcome.error:
        first, *rest = outcome.error.splitlines()
        return [red(f"✗ {first}"), *(dim("  " + clip(line)) for line in rest)]
    failing = next(r for r in outcome.results if not r.get("ok"))
    if ex.kind == "code":
        lines = [
            red(f"✗ {outcome.n_ok}/{outcome.total} checks pass"),
            f"  {dim('check   ')} {clip(failing['label'])}",
        ]
        if "error" in failing:
            return [*lines, f"  {dim('error   ')} {clip(failing['error'])}"]
        return [
            *lines,
            f"  {dim('expected')} {clip(failing['expected'])}",
            f"  {dim('got     ')} {clip(failing['got'])}",
        ]
    case = ex.cases[failing["i"]]
    lines = [red(f"✗ {outcome.n_ok}/{outcome.total} tests pass")]
    if "label" in case:
        lines.append(f"  {dim('perf    ')} {case['label']}")
    else:
        lines.append(f"  {dim('call    ')} {clip(lang.call(ex, case))}")
    if failing.get("timeout"):
        limit = case["limit"]
        lines.append(f"  {dim('got     ')} {yellow(f'over the {limit:g}s time limit')}")
        return lines
    got = failing["error"] if "error" in failing else lang.literal(failing.get("got"))
    lines.append(f"  {dim('expected')} {clip(lang.literal(case['out']))}")
    lines.append(f"  {dim('got     ')} {clip(got)}")
    return lines


class Clock:
    """A stopwatch that can be paused."""

    def __init__(self):
        self.start = time.monotonic()
        self.paused_at: float | None = None
        self.paused = 0.0

    def elapsed(self) -> float:
        now = self.paused_at or time.monotonic()
        return now - self.start - self.paused

    def pause(self) -> None:
        self.paused_at = time.monotonic()

    def resume(self) -> None:
        self.paused += time.monotonic() - self.paused_at
        self.paused_at = None


class Watcher:
    """Tells when a file has been saved with new content."""

    def __init__(self, path: Path):
        self.path = path
        self.mtime = path.stat().st_mtime_ns
        self.content = path.read_bytes()

    def changed(self) -> bool:
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return False
        if mtime == self.mtime:
            return False
        self.mtime = mtime
        time.sleep(0.05)  # let the editor finish writing
        content = self.path.read_bytes()
        if content == self.content:
            return False
        self.content = content
        return True


class Session:
    def __init__(
        self,
        name: str,
        exercises: list[Exercise],
        langs: list[Language],
        store: Store,
        editor: str | None,
        minutes: float | None,
        keep: bool,
        course: Collection | None = None,
        sandbox: bool = False,
    ):
        """A session over `exercises` (a mode's, or a search's), named `name` in the history.

        `course`, a learn module, serves its new exercises in the file's order. A `sandbox`
        session records nothing: it serves the exercises in turn, as long as you like.
        """
        self.course = course
        self.sandbox = sandbox
        self.name = name
        self.langs = langs
        self.store = store
        self.editor = editor
        self.minutes = minutes
        self.keep = keep
        self.pool = [(ex, lang) for ex in exercises for lang in langs if ex.supports(lang.key)]
        self.n_solved = self.n_skipped = self.n_records = 0
        self.ratios: list[float] = []
        self.reference_measurements: dict[tuple[str, str], Measurement | None] = {}
        self.laid_out: list[Path] = []
        self.played: dict[tuple[str, str, int], float] = {}  # when, in this session

    def run(self) -> None:
        if not self.pool:
            names = ", ".join(lang.label for lang in self.langs)
            raise SystemExit(f"drill: no {self.name} exercises for {names}")
        for lang in self.langs:
            lang.warm_up()
        self.dir = Path(tempfile.mkdtemp(prefix="drill-"))
        self.started = time.monotonic()
        self.deadline = self.started + self.minutes * 60 if self.minutes else None
        self.session = self.store.start_session(self.name, [lang.key for lang in self.langs])
        distinct = len({ex.id for ex, _ in self.pool})
        recent = deque(maxlen=min(3, distinct - 1))
        number = 0
        try:
            with term.Keys() as self.keys:
                while self.deadline is None or time.monotonic() < self.deadline:
                    pair = self.next_pair(recent)
                    if pair is None:
                        term.say(green("Nothing left to practise for now: all done until the next reviews."))
                        break
                    ex, lang = pair
                    recent.append(ex.id)
                    sandbox = self.sandbox
                    while True:  # [r] after an attempt: the same exercise again, as a run
                        number += 1
                        action = self.play(number, self.choose_variant(ex, lang), lang, sandbox)
                        if action != "again":
                            break
                        sandbox = True
                    if action == "quit":
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.store.end_session(self.session)
            if self.keep:
                term.say(dim(f"Session files kept in {self.dir}"))
            else:
                shutil.rmtree(self.dir, ignore_errors=True)
            self.summary()

    def next_pair(self, recent) -> tuple[Exercise, Language] | None:
        """What comes next: by the session rule, or in a sandbox the pair played least
        recently in this session."""
        if not self.sandbox:
            return pick(self.pool, self.store.cards(), recent, in_order=self.course is not None)

        def last(pair):
            ex, lang = pair
            times = [t for (e, l, _), t in self.played.items() if (e, l) == (ex.id, lang.key)]
            return max(times, default=0.0), random.random()

        return min(self.pool, key=last)

    def choose_variant(self, ex: Exercise, lang: Language) -> Exercise:
        """The variant practised least recently in this language, a new one first."""
        options = [v for v in ex.instances if v.supports(lang.key)]
        last = self.store.variants_seen(ex.id, lang.key)

        def when(v):
            return self.played.get((ex.id, lang.key, v.variant), last.get(v.variant, 0.0))

        return min(options, key=lambda v: (when(v), random.random()))

    def lay_out(self, ex: Exercise, lang: Language) -> Path:
        """Write the exercise's file and the files given with it; remove the last one's."""
        for old in self.laid_out:
            if old.is_symlink() or old.is_file():
                old.unlink()
            elif old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
        self.laid_out = [self.dir / "flake.lock", self.dir / "result"]
        for name, text in lang.fixtures(ex).items():
            target = self.dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            self.laid_out.append(self.dir / Path(name).parts[0])
        path = self.dir / lang.filename_for(ex)
        if path.name != lang.filename:
            self.laid_out.append(path)
        path.write_text(lang.starter(ex))
        return path

    def step_label(self, ex: Exercise, card: Card | None) -> str:
        """Where `ex` stands in its learn module: its part, its rank, new or a review."""
        steps = [step.id for step in self.course.exercises]
        rank = f"{steps.index(ex.id) + 1}/{len(steps)}" if ex.id in steps else ""
        kind = "new" if card is None else "review"
        return " · ".join(filter(None, [ex.chapter, rank, kind]))

    def play(self, number: int, ex: Exercise, lang: Language, sandbox: bool) -> str:
        """Run one exercise until it is solved or skipped; in a `sandbox`, record nothing.

        Returns what comes next: "next", "again" (the same exercise, as a run) or "quit".
        """
        self.played[(ex.id, lang.key, ex.variant)] = time.time()
        path = self.lay_out(ex, lang)
        # Generating the large inputs takes a moment: do it while the user reads
        threading.Thread(target=lambda: (ex.cases, ex.scale and ex.scale_cases), daemon=True).start()
        card = self.store.card(ex.id, lang.key)
        best = card.best if card else None
        runs, hinted, report = 0, False, []
        if sandbox:
            step = "run · not recorded"
        else:
            step = self.step_label(ex, card) if self.course else ""

        def redraw() -> None:
            term.clear()
            record = f"record {fmt_time(best)}" if best else "new"
            level = f"level {card.box}/{len(INTERVALS) - 1}" if card else ""
            variant = f" · variant {ex.variant + 1}/{ex.n_variants}" if ex.n_variants > 1 else ""
            if step:
                term.say(cyan(step))
            term.say(
                bold(f"#{number}  {ex.title}")
                + dim(f"   {lang.label} · target {fmt_time(ex.target)} · {record}")
                + dim(f" · {level}" if level else "") + dim(variant)
            )
            if ex.ref:
                term.say(dim(f"cf. {ex.ref}"))
            term.say(dim(str(path)))
            term.say()
            if hinted:
                term.say(cyan(f"Hint: {ex.hint or 'none for this one.'}"))
                term.say()
            for line in report:
                term.say(line)

        redraw()
        self.open_editor(path)
        watcher, clock = Watcher(path), Clock()
        while True:
            term.status(self.status_line(clock.elapsed(), ex, lang))
            key = self.keys.get(0.2)
            if key == "q":
                return "quit"
            if key == "o":
                self.open_editor(path)
            elif key == "c" and ex.scale and lang.measurable:
                clock.pause()  # a detour to learn from, not part of the solving time
                lines = self.estimate(ex, lang, path)
                clock.resume()
                if lines:
                    report = lines
                    redraw()
            elif key == "h" and not hinted:
                hinted = True
                redraw()
            elif key == "p":
                clock.pause()
                term.status(yellow("⏸ Paused") + dim("   [p] resume  [q] quit"))
                key = self.keys.wait("pq")
                clock.resume()
                if key == "q":
                    return "quit"
            elif key == "s":
                self.n_skipped += 1
                term.say()
                if sandbox:
                    term.say(yellow("↷ Skipped"))
                else:
                    after = self.store.record(
                        self.session, ex.id, lang.key, ex.mode, clock.elapsed(), ex.target,
                        runs, hinted, skipped=True, variant=ex.variant,
                    )
                    term.say(yellow("↷ " + level_note(card, after, "Skipped")))
                return self.reveal(ex, lang, sandbox)
            if key == "r" or watcher.changed():
                runs += 1
                solved_at = clock.elapsed()
                term.status(dim("Running tests…"))
                outcome = lang.run(ex, path, self.dir / ".build" / lang.key)
                if outcome.passed:
                    return self.solved(ex, lang, solved_at, runs, hinted, card, sandbox)
                report = [*failure_lines(ex, lang, outcome), dim(f"  run {runs}")]
                redraw()

    def solved(
        self, ex: Exercise, lang: Language, seconds: float, runs: int, hinted: bool,
        before: Card | None, sandbox: bool,
    ) -> str:
        best = before.best if before else None
        self.n_solved += 1
        ratio = seconds / ex.target
        self.ratios.append(ratio)
        line = green(bold(f"✓ Solved in {fmt_time(seconds)}"))
        line += dim(f"  {ratio:.1f}× target · {runs} run{'s' if runs > 1 else ''}")
        if best is not None and not hinted and not sandbox:
            if seconds < best:
                self.n_records += 1
                line += "  " + yellow(bold(f"New record! −{fmt_time(best - seconds)}"))
            else:
                line += dim(f"  · record {fmt_time(best)}")
        elif best is not None and sandbox:
            line += dim(f"  · record {fmt_time(best)}")
        term.say()
        term.say(line)
        if not sandbox:
            card = self.store.record(
                self.session, ex.id, lang.key, ex.mode, seconds, ex.target, runs, hinted,
                skipped=False, variant=ex.variant,
            )
            term.say(dim(level_note(before, card, grade_reason(seconds, ex.target, hinted, False))))
        return self.reveal(ex, lang, sandbox)

    def reveal(self, ex: Exercise, lang: Language, sandbox: bool) -> str:
        code = ex.solutions.get(lang.key)
        term.say()
        if code is None:
            term.say(dim(f"No {lang.label} reference solution for this exercise yet."))
        else:
            term.say(cyan(f"Reference solution ({lang.label})"))
            for line in code.strip("\n").splitlines():
                term.say(dim("│ ") + line)
        if ex.explanation:
            term.say()
            for line in explanation_lines(ex):
                term.say(line)
        back = "next exercise" if self.sandbox or not sandbox else f"back to {self.kind}"
        term.status(dim(f"[enter] {back}  [r] run it again, not recorded  [q] quit"))
        return {"q": "quit", "r": "again"}.get(self.keys.wait("\n qr"), "next")

    def estimate(self, ex: Exercise, lang: Language, path: Path) -> list[str]:
        """Ask for the complexity of the code in `path`, measure it, and report.

        Returns the report lines, or nothing if the user cancelled.
        """
        names = list(CLASSES)
        term.say()
        term.say(cyan("What is the time complexity of your code, as it is now?"))
        term.say("  " + "   ".join(f"{bold(str(i))} {name}" for i, name in enumerate(names, 1)))
        term.status(dim(f"[1-{len(names)}] your estimate   [x] cancel"))
        key = self.keys.wait("".join(str(i) for i in range(1, len(names) + 1)) + "x")
        if key == "x":
            return []
        guess = names[int(key) - 1]
        term.status(dim(f"Measuring your code on growing inputs ({ex.scale_label})…"))
        yours = measure(ex, lang, path, self.dir / ".build" / lang.key)
        reference = self.reference_measurement(ex, lang)
        if yours.slope is not None and not yours.error:
            self.store.record_estimate(ex.id, lang.key, guess, yours.consistent, yours.slope)
        return report(ex, guess, yours, reference)

    def reference_measurement(self, ex: Exercise, lang: Language) -> Measurement | None:
        """The reference solution's measurement, made once per session."""
        key = (ex.key, lang.key)
        if key not in self.reference_measurements:
            code = lang.reference(ex)
            if code is None:
                self.reference_measurements[key] = None
            else:
                term.status(dim("Measuring the reference solution…"))
                folder = self.dir / ".reference" / lang.key
                folder.mkdir(parents=True, exist_ok=True)
                source = folder / lang.filename_for(ex)
                source.write_text(code)
                self.reference_measurements[key] = measure(ex, lang, source, folder / ".build")
        return self.reference_measurements[key]

    def status_line(self, elapsed: float, ex: Exercise, lang: Language) -> str:
        target = ex.target
        colour = green if elapsed <= target else yellow if elapsed <= 2 * target else red
        parts = [colour(f"⏱ {fmt_time(elapsed)}") + dim(f" / {fmt_time(target)}")]
        if self.deadline:
            parts.append(dim(f"session {fmt_time(max(0.0, self.deadline - time.monotonic()))} left"))
        keys = COMPLEXITY_KEY if ex.scale and lang.measurable else ""
        parts.append(dim(keys + KEYS_HELP))
        return "   ".join(parts)

    def open_editor(self, path: Path) -> None:
        if self.editor and not open_in_editor(self.editor, path):
            self.editor = None

    @property
    def kind(self) -> str:
        """What the session practises, as the user calls it."""
        return "learn" if self.course else "drill"

    def summary(self) -> None:
        term.say(bold(f"Session over · {fmt_time(time.monotonic() - self.started)}"))
        parts = [f"{self.n_solved} solved", f"{self.n_skipped} skipped"]
        if self.n_records:
            parts.append(yellow(f"{self.n_records} record{'s' if self.n_records > 1 else ''}"))
        term.say("  " + " · ".join(parts))
        if self.ratios:
            term.say(dim(f"  average {sum(self.ratios) / len(self.ratios):.1f}× target"))

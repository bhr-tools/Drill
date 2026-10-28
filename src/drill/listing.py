"""`drill list`: the exercises of the library with your progress on each, and the sheet of
one exercise."""

from __future__ import annotations

import textwrap
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .exercises import MODES, Exercise
from .langs import LANGUAGES
from .library import Collection, Library
from .store import INTERVALS, Card, Store
from .term import ago, bold, cyan, dim, fmt_time, green, pad, red, spark, yellow

TOP = len(INTERVALS) - 1  # the highest level
MODE_HELP = {
    "sprint": "very short exercises, one after another",
    "normal": "longer exercises that need a bit more thought",
    "hard": "data structures and language subtleties that take a while",
    "optim": "working but slow solutions to make faster, and why",
}


def select(exercises: list[Exercise], queries: list[str]) -> list[Exercise]:
    """Exercises named by an exact id, plus those matching every other query (a part of
    an id, a title, a tag, a mode, or drill, pack, learn)."""
    exact = {q for q in queries if any(ex.id == q for ex in exercises)}
    rest = [q for q in queries if q not in exact]
    return [
        ex for ex in exercises
        if ex.id in exact or (rest and all(ex.matches(q) for q in rest))
    ]


@dataclass
class Progress:
    """Your history on one exercise, over some languages."""

    tries: int = 0
    best: float | None = None
    box: int | None = None  # the highest level reached among the languages; None: never done
    due: float | None = None  # the soonest review among the languages
    langs: set[str] = field(default_factory=set)  # the languages practised

    @property
    def new(self) -> bool:
        return self.box is None


def progress(
    exercises: list[Exercise], store: Store, langs: list[str] | None
) -> dict[str, Progress]:
    cards = store.cards()
    tries: dict[tuple[str, str], int] = defaultdict(int)
    for row in store.attempts():
        tries[row["exercise"], row["lang"]] += 1
    found = {}
    for ex in exercises:
        p = Progress()
        for key in langs or LANGUAGES:
            card: Card | None = cards.get((ex.id, key))
            p.tries += tries.get((ex.id, key), 0)
            if card is None:
                continue
            p.langs.add(key)
            if card.best is not None and (p.best is None or card.best < p.best):
                p.best = card.best
            p.box = card.box if p.box is None else max(p.box, card.box)
            p.due = card.due if p.due is None else min(p.due, card.due)
        found[ex.id] = p
    return found


def level_bar(box: int | None) -> str:
    if box is None:
        return dim("·" * TOP)
    colour = green if box >= 3 else yellow if box >= 1 else red
    return colour("▮" * box) + dim("▯" * (TOP - box))


def when(due: float | None, now: float) -> str:
    if due is None:
        return ""
    return yellow("now") if due <= now else f"in {ago(due - now)}"


def row(ex: Exercise, p: Progress, now: float, short: bool) -> str:
    name = ex.id.split(":", 1)[1] if short and ":" in ex.id else ex.id
    variants = f"×{ex.n_variants}" if ex.n_variants > 1 else ""
    langs = " ".join(
        bold(key) if key in p.langs else dim(key) for key in LANGUAGES if ex.supports(key)
    )
    best = fmt_time(p.best) if p.best else dim("—")
    return (
        f"  {name:30}{variants:>3}{fmt_time(ex.target):>6}{pad(best, 6, right=True)}"
        f"{p.tries or '':>6}  {level_bar(p.box)} {pad(when(p.due, now), 7)}"
        f"  {langs}  {dim(' '.join(ex.tags))}"
    )


HEADER = dim(f"  {'':30}{'':3}{'target':>6}{'best':>6}{'tries':>6}  {'level':6}{'review':7}"
             "  languages  tags")


def mastery(exercises: list[Exercise], prog: dict[str, Progress]) -> tuple[int, int, int]:
    """How many exercises are known (level 3 or more), started, and in all."""
    known = sum(1 for ex in exercises if (prog[ex.id].box or 0) >= 3)
    started = sum(1 for ex in exercises if not prog[ex.id].new)
    return known, started, len(exercises)


def collection_line(c: Collection, prog: dict[str, Progress], store: Store, now: float) -> str:
    known, started, total = mastery(c.exercises, prog)
    due = sum(1 for ex in c.exercises if (prog[ex.id].due or now + 1) <= now)
    if c.kind == "learn":
        done = store.passed()
        steps = sum(ex.id in done for ex in c.exercises)
        state = f"step {min(steps + 1, total)}/{total}" if steps < total else green("done")
    else:
        state = f"{known}/{total} known · {started - known} started"
    parts = [state] + ([yellow(f"{due} due")] if due else [])
    days = c.days_left()
    if days is not None:
        parts.append(red(f"{-days} d past the deadline") if days < 0 else f"{days} d left")
    langs = ", ".join(c.langs())
    return f"  {c.slug:30} {' · '.join(parts)}  {dim(langs)}"


def show(
    lib: Library, store: Store, queries: list[str], langs: list[str] | None,
    due: bool, new: bool,
) -> int:
    now = time.time()
    everything = lib.exercises()
    prog = progress(everything, store, langs)
    chosen = select(everything, queries) if queries else lib.drill
    if langs:
        chosen = [ex for ex in chosen if any(ex.supports(key) for key in langs)]
    if due:
        chosen = [ex for ex in chosen if (prog[ex.id].due or now + 1) <= now]
    if new:
        chosen = [ex for ex in chosen if prog[ex.id].new]
    if queries and not chosen:
        print(red(f"No exercise matches {' '.join(queries)}."))
        return 1
    if queries and len(chosen) == 1:
        sheet(chosen[0], lib, store, langs)
        return 0

    groups: list[tuple[str, list[Exercise], bool]] = []
    for mode in MODES:
        found = [ex for ex in chosen if ex.origin == "drill" and ex.mode == mode]
        if found:
            groups.append((f"{mode} — {MODE_HELP[mode]}", found, False))
    for c in lib.collections:
        found = [ex for ex in chosen if ex.pack == c.slug]
        if found:
            groups.append((f"{c.kind} {c.slug} — {c.name}", found, True))
    print(HEADER)
    for title, found, short in groups:
        print(bold(title))
        for ex in found:
            print(row(ex, prog[ex.id], now, short))
        print()

    if not queries and lib.collections:
        for kind in ("pack", "learn"):
            collections = lib.of_kind(kind)
            if collections:
                title = "packs" if kind == "pack" else "learn courses"
                print(bold(title) + dim(f"  (drill list {kind} for their exercises)"))
                for c in collections:
                    print(collection_line(c, prog, store, now))
                print()

    n_due = sum(1 for ex in chosen if (prog[ex.id].due or now + 1) <= now)
    n_new = sum(1 for ex in chosen if prog[ex.id].new)
    print(dim(f"{len(chosen)} exercises · {n_due} due · {n_new} never done · "
              f"×N: variants · level ▮▮▮▯▯ = 3/{TOP} · `drill help` explains levels"))
    return 0


def variant_name(instance: Exercise, base: Exercise) -> str:
    if instance.title != base.title or instance.variant == 0:
        return instance.title
    if instance.name and instance.name != base.name:
        return instance.name
    first = textwrap.dedent(instance.statement).strip().splitlines()[0]
    return first[:60] + ("…" if len(first) > 60 else "")


def sheet(ex: Exercise, lib: Library, store: Store, langs: list[str] | None) -> None:
    """Everything about one exercise, and your history on it."""
    now = time.time()
    where = f"{ex.origin} {ex.pack}" if ex.pack else "drill"
    print(bold(ex.title) + dim(f"  ·  {ex.id}  ·  {ex.mode}  ·  target {fmt_time(ex.target)}"
                               f"  ·  {where}"))
    supported = [key for key in LANGUAGES if any(i.supports(key) for i in ex.instances)]
    print(dim(f"languages {', '.join(supported)}  ·  tags {', '.join(ex.tags) or '—'}"))
    print()
    statement = textwrap.dedent(ex.statement).strip().splitlines()
    for line in statement[:6]:
        print("  " + line)
    if len(statement) > 6:
        print(dim("  …"))

    rows = [r for r in store.attempts() if r["exercise"] == ex.id]
    last = defaultdict(float)
    for r in rows:
        last[r["variant"]] = max(last[r["variant"]], r["finished"])
    if ex.n_variants > 1:
        print()
        print(bold(f"Variants ({ex.n_variants})") + dim("  served in turn, least recent first"))
        for instance in ex.instances:
            seen = last.get(instance.variant)
            seen_text = f"last {ago(now - seen)} ago" if seen else "never"
            print(f"  {instance.variant + 1}. {variant_name(instance, ex):50} {dim(seen_text)}")

    print()
    print(bold("Your progress"))
    cards = store.cards()
    shown = [key for key in (langs or supported) if key in supported]
    for key in shown:
        card = cards.get((ex.id, key))
        lang_rows = [r for r in rows if r["lang"] == key]
        label = LANGUAGES[key].label
        if card is None:
            print(f"  {label:8} {level_bar(None)}  {dim('never done')}")
            continue
        review = when(card.due, now)
        best = fmt_time(card.best) if card.best else "—"
        print(f"  {label:8} {level_bar(card.box)}  level {card.box}/{TOP} · review {review}"
              f" · best {best} · {len(lang_rows)} tries")
        recent = lang_rows[-12:]
        if recent:
            ratios = [3.0 if r["outcome"] == "skip" else min(r["seconds"] / r["target"], 3.0)
                      for r in recent]
            print(dim(f"  {'':8} time/target {spark(ratios, 3.0)}  (last {len(recent)}, "
                      "lower is faster)"))
            for r in recent[-3:]:
                day = datetime.fromtimestamp(r["finished"]).strftime("%Y-%m-%d")
                result = "skipped" if r["outcome"] == "skip" else fmt_time(r["seconds"])
                variant = f" · variant {r['variant'] + 1}" if ex.n_variants > 1 else ""
                print(dim(f"  {'':8} {day}  {result:>7}  {r['grade']}{variant}"))
    print()
    print(cyan(f"drill run {ex.id}") + dim("  to practise it"))

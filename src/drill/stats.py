"""`drill stats`: your progress, computed from the attempt history."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean

from .langs import LANGUAGES
from .library import Library
from .listing import TOP, collection_line, mastery, progress
from .store import DAY, Store
from .term import bold, dim, fmt_duration, green, pad, red, spark, yellow

SKIP_SCORE = 3.0  # a skip weighs like a solve at 3× the target
WINDOW = 14  # days compared by the trend column
ACTIVITY_DAYS = 30


def score(row) -> float:
    """Time over target: 1.0 is on target, lower is faster."""
    if row["outcome"] == "skip":
        return SKIP_SCORE
    return min(row["seconds"] / row["target"], SKIP_SCORE)


def day_of(row) -> date:
    return datetime.fromtimestamp(row["finished"]).date()


def streak(rows) -> int:
    days = {day_of(r) for r in rows}
    day = date.today()
    if day not in days:
        day -= timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count


def trend(rows, now: float) -> str:
    """Change of the time over target in the last WINDOW days versus the window before."""
    recent = [score(r) for r in rows if r["finished"] > now - WINDOW * DAY]
    before = [score(r) for r in rows if now - 2 * WINDOW * DAY < r["finished"] <= now - WINDOW * DAY]
    if not recent or not before:
        return dim("—")
    change = (mean(recent) / mean(before) - 1) * 100
    text = f"{change:+.0f}%"
    # Lower scores mean faster solves
    return green(text) if change < 0 else red(text) if change > 0 else text


def week(rows, start: date) -> tuple[int, float]:
    chosen = [r for r in rows if start <= day_of(r) < start + timedelta(days=7)]
    return len(chosen), sum(r["seconds"] for r in chosen)


def overview(rows, store: Store) -> None:
    today = date.today()
    this_week = week(rows, today - timedelta(days=6))
    last_week = week(rows, today - timedelta(days=13))
    print(bold("Practice"))
    print(f"  last 7 days   {this_week[0]:>4} exercises  {fmt_duration(this_week[1]):>7}"
          + dim(f"   the 7 before: {last_week[0]} exercises, {fmt_duration(last_week[1])}"))
    total = sum(r["seconds"] for r in rows)
    print(f"  in all        {len(rows):>4} exercises  {fmt_duration(total):>7}"
          f"   streak {streak(rows)} day(s)")
    minutes = defaultdict(float)
    for r in rows:
        minutes[day_of(r)] += r["seconds"] / 60
    days = [today - timedelta(days=ACTIVITY_DAYS - 1 - i) for i in range(ACTIVITY_DAYS)]
    line = "".join(spark([minutes[d]], max(minutes.values())) if minutes[d] else dim("·")
                   for d in days)
    print(f"  {ACTIVITY_DAYS} days       {line}" + dim("  minutes per day, today on the right"))


def mastery_table(lib: Library, store: Store, now: float) -> None:
    prog = progress(lib.exercises(), store, None)
    print(bold("Mastery") + dim(f"  known: level 3 or more, out of {TOP}"))
    known, started, total = mastery(lib.drill, prog)
    print(f"  {'drill':30} {known}/{total} known · {started - known} started · "
          f"{total - started} never done")
    for c in lib.collections:
        print(collection_line(c, prog, store, now))


def coming_up(store: Store, lib: Library, now: float) -> None:
    present = {ex.id for ex in lib.exercises()}
    dues = [card.due for (ex_id, _), card in store.cards().items() if ex_id in present]
    if not dues:
        return
    today_end = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).timestamp()
    parts = [yellow(f"today {sum(d < today_end for d in dues)}")]
    for i in range(1, 7):
        start = today_end + (i - 1) * DAY
        n = sum(start <= d < start + DAY for d in dues)
        label = (date.today() + timedelta(days=i)).strftime("%a")
        parts.append(f"{label} {n}" if n else dim(f"{label} 0"))
    print(bold("Reviews coming up"))
    print("  " + " · ".join(parts))


def speed(rows, store: Store, now: float) -> None:
    cards = store.cards()
    print(bold("By language"))
    print(dim(f"  {'':10}{'solved':>7}{'skipped':>8}{'time/target':>12}{'trend':>7}"
              f"{'known':>7}   practice"))
    for key in sorted({r["lang"] for r in rows}):
        lang_rows = [r for r in rows if r["lang"] == key]
        passed = [r for r in lang_rows if r["outcome"] == "pass"]
        avg = f"{mean(r['seconds'] / r['target'] for r in passed):.1f}×" if passed else "—"
        known = sum(1 for (_, lang), card in cards.items() if lang == key and card.box >= 3)
        label = LANGUAGES[key].label if key in LANGUAGES else key
        print(f"  {label:10}{len(passed):>7}{len(lang_rows) - len(passed):>8}{avg:>12}"
              f"{pad(trend(lang_rows, now), 7, right=True)}{known:>7}"
              f"   {fmt_duration(sum(r['seconds'] for r in lang_rows))}")
    print(dim(f"  time/target: solve time over the target, 1.0× is on target, lower is faster ·"
              f" trend: last {WINDOW} days vs the {WINDOW} before"))


def weak_spots(rows, lib: Library) -> None:
    by_id = {ex.id: ex for ex in lib.exercises()}
    tags = defaultdict(list)
    for r in rows:
        for tag in by_id[r["exercise"]].tags if r["exercise"] in by_id else ():
            tags[tag].append(score(r))
    weakest_tags = sorted(
        ((mean(scores), tag, len(scores)) for tag, scores in tags.items() if len(scores) >= 2),
        reverse=True,
    )[:5]
    misses = defaultdict(int)
    for r in rows:
        if r["grade"] == "fail":
            misses[r["exercise"]] += 1
    missed = sorted(((n, ex_id) for ex_id, n in misses.items()), reverse=True)[:5]
    if not weakest_tags and not missed:
        return
    print(bold("Weak spots"))
    for value, tag, n in weakest_tags:
        colour = green if value <= 1 else yellow if value <= 2 else red
        print(f"  tag {tag:24}{colour(f'{value:.1f}×')}  {dim(f'{n} attempts')}")
    for n, ex_id in missed:
        print(f"  {ex_id:28}{red(f'{n} missed')}  {dim('skipped or over twice the target')}")


def show(store: Store, lib: Library) -> None:
    rows = store.attempts()
    if not rows:
        print("No attempts yet. Start with `drill sprint`, `drill pack` or `drill learn`.")
        return
    now = time.time()
    overview(rows, store)
    estimates = store.estimates()
    if estimates:
        right = sum(e["correct"] for e in estimates)
        print(f"  complexity estimates: {right}/{len(estimates)} right ({right / len(estimates):.0%})")
    print()
    mastery_table(lib, store, now)
    print()
    coming_up(store, lib, now)
    print()
    speed(rows, store, now)
    print()
    weak_spots(rows, lib)
    print(dim("\n`drill list` shows each exercise; `drill list <id>` its history; "
              "`drill help` how levels and reviews work."))

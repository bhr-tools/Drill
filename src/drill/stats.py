"""Statistics computed from the attempt history."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean

from .exercises import Exercise
from .langs import LANGUAGES
from .store import DAY, Store
from .term import bold, dim, fmt_duration, fmt_time, green, red, yellow

SKIP_SCORE = 3.0  # a skip weighs like a solve at 3× the target
WINDOW = 14  # days compared by the trend column
ANSI = re.compile(r"\033\[[0-9;]*m")  # stripped to pad coloured cells


def score(row) -> float:
    if row["outcome"] == "skip":
        return SKIP_SCORE
    return min(row["seconds"] / row["target"], SKIP_SCORE)


def streak(rows) -> int:
    days = {datetime.fromtimestamp(r["finished"]).date() for r in rows}
    day = date.today()
    if day not in days:
        day -= timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count


def trend(rows, now: float) -> str:
    """Change of the average score over the last WINDOW days versus the window before."""
    recent = [score(r) for r in rows if r["finished"] > now - WINDOW * DAY]
    before = [score(r) for r in rows if now - 2 * WINDOW * DAY < r["finished"] <= now - WINDOW * DAY]
    if not recent or not before:
        return dim("—")
    change = (mean(recent) / mean(before) - 1) * 100
    text = f"{change:+.0f}%"
    # Lower scores mean faster solves
    return green(text) if change < 0 else red(text) if change > 0 else text


def show(store: Store, exercises: list[Exercise], per_exercise: bool) -> None:
    rows = store.attempts()
    if not rows:
        print("No attempts yet. Start with `drill sprint`.")
        return
    now = time.time()
    by_id = {ex.id: ex for ex in exercises}

    print(bold("Overview"))
    total = sum(r["seconds"] for r in rows)
    print(f"  {len(rows)} attempts · {fmt_duration(total)} of practice · streak {streak(rows)} day(s)")
    estimates = store.estimates()
    if estimates:
        right = sum(e["correct"] for e in estimates)
        print(f"  complexity estimates: {right}/{len(estimates)} right ({right / len(estimates):.0%})")
    cards = store.cards()
    due = defaultdict(int)
    for (ex_id, _), card in cards.items():
        if ex_id in by_id and card.due <= now:
            due[by_id[ex_id].mode] += 1
    if due:
        print(dim("  due now: " + " · ".join(f"{mode} {n}" for mode, n in sorted(due.items()))))

    print()
    print(bold("By language"))
    print(dim(f"  {'':10}{'solved':>8}{'skipped':>9}{'avg':>8}{'trend':>8}   practice"))
    for key in sorted({r["lang"] for r in rows}):
        lang_rows = [r for r in rows if r["lang"] == key]
        passed = [r for r in lang_rows if r["outcome"] == "pass"]
        avg = f"{mean(r['seconds'] / r['target'] for r in passed):.1f}×" if passed else "—"
        label = LANGUAGES[key].label if key in LANGUAGES else key
        change = trend(lang_rows, now)
        print(
            f"  {label:10}{len(passed):>8}{len(lang_rows) - len(passed):>9}{avg:>8}"
            f"{' ' * (8 - len(ANSI.sub('', change)))}{change}"
            f"   {fmt_duration(sum(r['seconds'] for r in lang_rows))}"
        )
    print(dim(f"  avg: solve time / target (lower is better) · trend: last {WINDOW} days vs the {WINDOW} before"))

    tags = defaultdict(list)
    for r in rows:
        for tag in by_id[r["exercise"]].tags if r["exercise"] in by_id else ():
            tags[tag].append(score(r))
    weakest = sorted(
        ((mean(scores), tag, len(scores)) for tag, scores in tags.items() if len(scores) >= 2),
        reverse=True,
    )[:5]
    if weakest:
        print()
        print(bold("Weakest tags"))
        for value, tag, n in weakest:
            colour = green if value <= 1 else yellow if value <= 2 else red
            print(f"  {tag:18}{colour(f'{value:.1f}×')}  {dim(f'{n} attempts')}")

    if per_exercise:
        print()
        print(bold("By exercise"))
        print(dim(f"  {'exercise':28}{'lang':8}{'tries':>6}{'best':>7}{'box':>5}   next review"))
        tries = defaultdict(int)
        for r in rows:
            tries[r["exercise"], r["lang"]] += 1
        for (ex_id, lang), card in sorted(cards.items()):
            best = fmt_time(card.best) if card.best else "—"
            wait = card.due - now
            if wait <= 0:
                when = "now"
            elif wait < 20 * 3600:
                when = f"in {wait / 3600:.0f} h"
            else:
                when = f"in {max(1, round(wait / DAY))} d"
            print(f"  {ex_id:28}{lang:8}{tries[ex_id, lang]:>6}{best:>7}{card.box:>5}   {when}")

"""Measuring how a solution's running time grows with the size of its input.

A solution is timed on inputs of growing size n. On a log-log scale, a running time
in O(n^k) is a line of slope k, so the slope of the measurements tells the growth.
Each complexity class has its own slope over the same sizes (about 1.1 for n log n
between 10^3 and 10^6), and the classes close to the measured slope are the ones
the measurement is consistent with. Telling n from n log n, or 1 from log n, is
beyond what timing noise allows, so both are then reported as consistent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .term import cyan, dim, green, red, yellow

if TYPE_CHECKING:
    from .exercises import Exercise
    from .langs import Language

# log f(n) for each class, from the smallest to the largest
CLASSES = {
    "O(1)": lambda n: 0.0,
    "O(log n)": lambda n: math.log(math.log2(max(n, 2))),
    "O(n)": lambda n: math.log(n),
    "O(n log n)": lambda n: math.log(n * math.log2(max(n, 2))),
    "O(n²)": lambda n: 2 * math.log(n),
    "O(n³)": lambda n: 3 * math.log(n),
    "O(2ⁿ)": lambda n: n * math.log(2),
}
ALIASES = {"O(n^2)": "O(n²)", "O(n^3)": "O(n³)", "O(2^n)": "O(2ⁿ)", "O(nlogn)": "O(n log n)"}
# How far the measured slope may be above or below a class's slope. Above is more
# lenient: on large inputs, cache misses and memory allocation make each operation
# slower, which steepens the slope (a graph search on 10^5 nodes measures ~n^1.45).
TOLERANCE_ABOVE = 0.5
TOLERANCE_BELOW = 0.2
MIN_US = 200  # shorter times are mostly overhead and noise
FIT_POINTS = 5  # the slope comes from the largest sizes: the asymptotic behaviour
SLOWER_MARGIN = 0.5  # a measured slope this far above the optimal one is not optimal


def canonical(text: str) -> str | None:
    text = ALIASES.get(text.strip(), text.strip())
    return text if text in CLASSES else None


def _slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of ys against xs."""
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0


@dataclass
class Measurement:
    points: list[tuple[int, float]] = field(default_factory=list)  # (n, microseconds)
    stopped_at: int | None = None  # the first size over the time limit
    limit: float = 0.0
    error: str | None = None

    def _fit_points(self) -> list[tuple[int, float]]:
        # Small sizes measure fixed costs (calls, allocation, an unwarmed JIT) more
        # than growth: keep the largest ones
        usable = [(n, t) for n, t in self.points if t >= MIN_US]
        return (usable if len(usable) >= 3 else self.points)[-FIT_POINTS:]

    @property
    def slope(self) -> float | None:
        points = self._fit_points()
        if len(points) < 2:
            return None
        return _slope([math.log(n) for n, _ in points], [math.log(max(t, 1e-3)) for _, t in points])

    def class_slope(self, name: str) -> float:
        """The slope class `name` would show over the measured sizes."""
        sizes = [n for n, _ in self._fit_points()]
        return _slope([math.log(n) for n in sizes], [CLASSES[name](n) for n in sizes])

    @property
    def consistent(self) -> list[str]:
        """The classes this measurement is consistent with, best first."""
        slope = self.slope
        if slope is None:
            return []
        if slope > self.class_slope("O(n³)") + 1:
            return ["O(2ⁿ)"]  # faster than any polynomial over these sizes
        gap = {name: slope - self.class_slope(name) for name in CLASSES}

        def distance(name: str) -> float:
            # Being measured above a class is the usual effect of memory: count it a third
            return gap[name] / 3 if gap[name] > 0 else -gap[name]

        close = [name for name in CLASSES if -TOLERANCE_BELOW <= gap[name] <= TOLERANCE_ABOVE]
        return sorted(close, key=distance) or [min(CLASSES, key=distance)]

    def slower_than(self, optimal: str) -> bool:
        slope = self.slope
        return slope is not None and slope > self.class_slope(optimal) + SLOWER_MARGIN


def measure(ex: Exercise, lang: Language, source: Path, build: Path) -> Measurement:
    """Time the solution in `source` on the exercise's inputs of growing size."""
    # A first, discarded run on a mid-size input warms up caches and the JIT
    cases = [ex.scale_cases[min(2, len(ex.scale_cases) - 1)], *ex.scale_cases]
    outcome = lang.run(ex, source, build, cases=cases, tag="scale")
    result = Measurement(limit=cases[0]["limit"])
    for r in outcome.results:
        if r["i"] == 0:
            continue
        n = cases[r["i"]]["n"]
        if r.get("timeout"):
            result.stopped_at = n
        elif "error" in r:
            result.error = f"failed at n = {n:,}: {r['error']}"
            break
        elif "us" in r:
            result.points.append((n, r["us"]))
    if outcome.error:
        result.error = outcome.error
    return result


def fmt_us(us: float) -> str:
    if us < 1000:
        return f"{us:.0f} µs" if us >= 10 else f"{us:.1f} µs"
    if us < 1e6:
        return f"{us / 1000:.1f} ms"
    return f"{us / 1e6:.2f} s"


def _growth(m: Measurement) -> str:
    if m.slope is None:
        return "not enough data"
    return f"~ n^{m.slope:.2f} → {' or '.join(m.consistent[:2])}"


def report(
    ex: Exercise, guess: str, yours: Measurement, reference: Measurement | None
) -> list[str]:
    """The measurements side by side, then the verdict on the estimate and on optimality."""
    lines = [cyan(f"Complexity  ·  {ex.scale_label}"), ""]
    if yours.error:
        first, *rest = yours.error.splitlines()
        return [*lines, red(f"Your code {first}"), *(dim("  " + line) for line in rest[:8])]

    def cell(m: Measurement | None, n: int) -> str:
        if m is None:
            return ""
        times = dict(m.points)
        if n in times:
            return fmt_us(times[n])
        if m.stopped_at == n:
            return f"over {m.limit:g} s"
        return ""

    sizes = sorted({n for n, _ in yours.points} | ({n for n, _ in reference.points} if reference else set())
                   | {m.stopped_at for m in (yours, reference) if m and m.stopped_at})
    lines.append(dim(f"  {'n':>11}   {'yours':>12}   {'reference' if reference else '':>12}"))
    for n in sizes:
        lines.append(f"  {n:>11,}   {cell(yours, n):>12}   {cell(reference, n):>12}")
    lines.append("")
    lines.append(f"  {dim('your code ')}  {_growth(yours)}")
    if reference:
        lines.append(f"  {dim('reference ')}  {_growth(reference)}")
    lines.append("")

    if yours.slope is None:
        lines.append(yellow("Too few measurements to judge: the code is too fast or too slow at these sizes."))
        return lines
    if guess in yours.consistent:
        lines.append(green(f"✓ Your estimate {guess} matches the measurement."))
    else:
        lines.append(red(f"✗ Your estimate {guess} does not match: the measurement says {yours.consistent[0]}."))
    if ex.complexity:
        if yours.slower_than(ex.complexity):
            lines.append(yellow(f"↗ The optimal complexity is {ex.complexity}: this code can do better."))
        else:
            lines.append(green(f"✓ Optimal: the best possible is {ex.complexity}."))
    return lines

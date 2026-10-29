"""Checking reference solutions, and the clipboard round trip with the AI that wrote them."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .exercises import Exercise
from .langs import Language, Outcome
from .session import failure_lines
from .term import bold, dim, green, red

ANSI = re.compile(r"\033\[[0-9;]*m")
FENCE_OPEN = re.compile(r"^(```+|~~~+)\s*toml\s*$", re.M)


def perf_usage(ex: Exercise, lang: Language, outcome: Outcome) -> str:
    """The slowest performance case, as a share of its time limit."""
    if ex.kind == "code" or not lang.measurable:
        return ""
    usage = [
        (r.get("us", 0) / 1e6 / ex.cases[r["i"]]["limit"], r.get("us", 0), ex.cases[r["i"]]["limit"])
        for r in outcome.results
        if "limit" in ex.cases[r["i"]]
    ]
    if not usage:
        return ""
    share, us, limit = max(usage)
    return f"  perf {us / 1000:.0f} ms / {limit:g}s ({share:.0%})"


def check(exercises: list[Exercise], langs: list[Language]) -> list[str]:
    """Run every reference solution of every variant against its tests.

    Prints the results and returns the failures, as plain text.
    """
    jobs = [
        (instance, lang)
        for ex in exercises
        for lang in langs
        if ex.supports(lang.key)
        for instance in ex.instances
        if instance.supports(lang.key)
    ]
    root = Path(tempfile.mkdtemp(prefix="drill-check-"))

    def run(job):
        ex, lang = job
        code = lang.reference(ex)
        if code is None:
            return None
        work = root / f"{ex.key}-{lang.key}"
        work.mkdir()
        source = work / lang.filename_for(ex)
        source.write_text(code)
        return lang.run(ex, source, work / ".build")

    failures: list[str] = []
    missing = 0
    try:
        with ThreadPoolExecutor(os.cpu_count()) as pool:
            for (ex, lang), outcome in zip(jobs, pool.map(run, jobs)):
                name = f"{ex.mode}/{ex.key} [{lang.key}]"
                if outcome is None:
                    missing += 1
                    print(dim(f"  · {name}: no reference solution"))
                elif outcome.passed:
                    print(green("  ✓ ") + name + dim(perf_usage(ex, lang, outcome)))
                else:
                    lines = failure_lines(ex, lang, outcome)
                    print(red("  ✗ ") + name)
                    for line in lines:
                        print("      " + line)
                    details = "\n".join("    " + ANSI.sub("", line).strip() for line in lines)
                    variant = f" (variant {ex.variant + 1})" if ex.variant else ""
                    failures.append(f"- {ex.id}{variant} [{lang.key}]:\n{details}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    checked = len(jobs) - missing
    summary = f"{checked - len(failures)}/{checked} reference solutions pass"
    print(bold(summary) + (dim(f" · {missing} missing") if missing else ""))
    return failures


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"]):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd, input=text, text=True).returncode == 0
    return False


def paste() -> str | None:
    """The clipboard's text, or None when no clipboard tool is available."""
    for cmd in (["wl-paste", "--no-newline"], ["xclip", "-o", "-selection", "clipboard"], ["pbpaste"]):
        if shutil.which(cmd[0]):
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout if result.returncode == 0 else ""
    return None


def unfence(text: str) -> str:
    """The TOML of an AI's reply: the text itself when it is TOML (the code block alone was
    copied), else its ```toml block. The block runs to the last closing fence of the reply,
    as lessons inside it may hold code blocks of their own."""
    try:
        tomllib.loads(text)
        return text
    except tomllib.TOMLDecodeError:
        pass
    match = FENCE_OPEN.search(text)
    if not match:
        return text
    fence = match.group(1)
    lines = text[match.end():].split("\n")[1:]
    closing = [i for i, line in enumerate(lines) if line.strip() == fence]
    return "\n".join(lines[: closing[-1]] if closing else lines) + "\n"


def fix_request(problems: list[str]) -> str:
    """A message to paste back to the AI, so it corrects its file."""
    return "\n".join([
        "drill rejected the file. Problems found:",
        "",
        *problems,
        "",
        "Fix every problem above: recompute the expected outputs from the reference solutions,"
        " or fix the solutions or the checks. Then send the whole corrected TOML file again.",
    ])

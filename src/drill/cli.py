"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import packs, prompt, stats
from .exercises import MODES, Exercise, ExerciseError, load_all
from .langs import ALIASES, LANGUAGES, Language, Outcome
from .session import Session, failure_lines
from .store import Store
from .term import bold, cyan, dim, fmt_time, green, red, yellow

ANSI = re.compile(r"\033\[[0-9;]*m")
MODE_HELP = {
    "sprint": "very short exercises, one after another",
    "normal": "longer exercises that need a bit more thought",
    "hard": "data structures and language subtleties that take a while",
    "optim": "working but slow solutions to make faster, and why",
}


def parse_langs(spec: str) -> list[Language]:
    if spec in ("mix", "all"):
        return list(LANGUAGES.values())
    langs = []
    for name in spec.split(","):
        name = name.strip().lower()
        name = ALIASES.get(name, name)
        if name not in LANGUAGES:
            raise argparse.ArgumentTypeError(
                f"unknown language {name!r} (choose from {', '.join(LANGUAGES)}, or mix)"
            )
        langs.append(LANGUAGES[name])
    return langs


def default_editor() -> str | None:
    editor = os.environ.get("DRILL_EDITOR")
    if editor is None:
        return "code" if shutil.which("code") else None
    return None if editor in ("", "none") else editor


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


def check(exercises: list[Exercise], langs: list[Language], ids: list[str]) -> list[str]:
    """Run every reference solution against its tests.

    Prints the results and returns the failures, as plain text.
    """
    unknown = set(ids) - {ex.id for ex in exercises}
    if unknown:
        print(red(f"Unknown exercise(s): {', '.join(sorted(unknown))}"))
        return [f"unknown exercise {name}" for name in sorted(unknown)]
    jobs = [
        (instance, lang)
        for ex in exercises
        if not ids or ex.id in ids
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


def exercise_row(ex: Exercise) -> str:
    langs = ",".join(k for k in LANGUAGES if ex.supports(k))
    variants = f"×{ex.n_variants}" if ex.n_variants > 1 else ""
    return (
        f"  {ex.id:30}{variants:>3}{fmt_time(ex.target):>6}  {dim(f'{langs:18}')}"
        f"  {dim(' '.join(ex.tags))}"
    )


def list_exercises(exercises: list[Exercise], mode: str | None) -> None:
    for current in MODES:
        if mode and current != mode:
            continue
        print(bold(f"{current} — {MODE_HELP[current]}"))
        for ex in exercises:
            if ex.mode == current:
                print(exercise_row(ex))
        print()


def search(exercises: list[Exercise], queries: list[str]) -> list[Exercise]:
    """Exercises matching any query: an exact id, or part of an id, title, tag or mode."""
    exact = [ex for ex in exercises if ex.id in queries]
    rest = [q for q in queries if q not in {ex.id for ex in exact}]
    return [ex for ex in exercises if ex in exact or any(ex.matches(q) for q in rest)]


def add_session_options(p: argparse.ArgumentParser, lang_default: str | None) -> None:
    lang_help = f"{', '.join(LANGUAGES)}, a comma-separated list, or mix"
    p.add_argument(
        "-l", "--lang", type=parse_langs, default=lang_default,
        help=f"{lang_help} (default: $DRILL_LANG or python)" if lang_default else
             f"{lang_help} (default: $DRILL_LANG or python when the exercises support it, "
             "else every language they support)",
    )
    p.add_argument("-m", "--minutes", type=float, help="end the session after this many minutes")
    p.add_argument(
        "-e", "--editor", default=default_editor(),
        help="command that opens the exercise file, or none "
             "(default: $DRILL_EDITOR, else code when available)",
    )
    p.add_argument("--keep", action="store_true", help="keep the session folder at the end")


def run_session(parser, args, name: str, chosen: list[Exercise]) -> None:
    if not sys.stdin.isatty():
        parser.error("a session needs an interactive terminal")
    langs = args.lang
    if langs is None:
        preferred = parse_langs(os.environ.get("DRILL_LANG", "python"))
        supported = [lang for lang in preferred if any(ex.supports(lang.key) for ex in chosen)]
        langs = supported or [
            lang for lang in LANGUAGES.values() if any(ex.supports(lang.key) for ex in chosen)
        ]
    editor = None if args.editor in ("", "none") else args.editor
    Session(name, chosen, langs, Store(), editor, args.minutes, args.keep).run()


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"]):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd, input=text, text=True).returncode == 0
    return False


def show_prompt(langs: list[Language], count: int, copy: bool) -> None:
    text = prompt.build([lang.key for lang in langs], count)
    if not (copy and copy_to_clipboard(text)):
        print(text)
        copy = False
    steps = [
        "Copied to the clipboard." if copy else "That was the prompt.",
        "1. Send it to Claude with your course PDFs (lectures, tutorials, lab sheets).",
        "2. Save the TOML file it replies with, e.g. as graphs.toml.",
        "3. Run `drill pack add graphs.toml`: it checks every exercise, then installs the pack.",
        "4. Practise with `drill pack`.",
    ]
    print(cyan("\n".join(steps)), file=sys.stderr)


def fix_request(problems: list[str]) -> str:
    """A message to paste back to the AI, so it corrects the pack."""
    return "\n".join([
        "drill rejected the pack. Problems found:",
        "",
        *problems,
        "",
        "Fix every problem above: recompute the expected outputs from the reference solutions,"
        " or fix the solutions or the checks. Then send the whole corrected TOML file again.",
    ])


def add_pack(file: Path, name: str | None, force: bool) -> int:
    if not file.is_file():
        print(red(f"No such file: {file}"))
        return 1
    try:
        pack = packs.load(file)
        slug = packs.slugify(name or pack.name)
        if slug != pack.slug:
            pack = packs.load(file, slug)
    except ExerciseError as e:
        print(red(str(e)))
        print(yellow("\nPaste this to Claude to get a corrected file:\n"))
        print(fix_request([f"- the file: {e}"]))
        return 1
    print(bold(f"{pack.name}") + dim(f"  ·  {len(pack.exercises)} exercises  ·  {pack.counts()}"))
    problems = [f"- {error}" for error in pack.errors]
    for error in pack.errors:
        print(red(f"  ✗ {error}"))
    problems += check(pack.exercises, list(LANGUAGES.values()), [])
    if problems and not force:
        print(red(f"\nNot installed: {len(problems)} problem(s)."))
        print(yellow("Paste this to Claude, in the same conversation, to get a corrected file:\n"))
        print(fix_request(problems))
        print(dim("\n(--force installs the pack anyway.)"))
        return 1
    existed = (packs.packs_dir() / f"{slug}.toml").exists()
    target = packs.install(file, slug)
    print(green(f"\n{'Replaced' if existed else 'Installed'} pack {slug}") + dim(f"  ({target})"))
    print(f"Practise it with `drill pack run {slug}`, or just `drill pack`.")
    return 0


def list_packs(installed: list[packs.Pack]) -> None:
    if not installed:
        print("No pack installed yet. `drill prompt` shows how to make one from your course.")
        return
    for index, pack in enumerate(installed, 1):
        langs = ", ".join(pack.langs())
        print(f"  {bold(str(index))}  {bold(pack.name)}  {dim(f'({pack.slug})')}")
        print(f"     {dim(pack.counts())}  {dim('· ' + langs) if langs else ''}")
        if pack.description:
            print(f"     {dim(pack.description)}")


def choose_pack(installed: list[packs.Pack]) -> tuple[packs.Pack, list[Exercise]] | None:
    """Ask which pack, then which mode, to practise."""
    list_packs(installed)
    if not installed:
        return None
    try:
        answer = input(f"\nPack [1-{len(installed)}]: ").strip() if len(installed) > 1 else "1"
        pack = installed[int(answer) - 1]
        modes = [mode for mode in MODES if any(ex.mode == mode for ex in pack.exercises)]
        mode = ""
        if len(modes) > 1:
            mode = input(f"Mode [{'/'.join(modes)}, enter for all]: ").strip()
    except (ValueError, IndexError, EOFError, KeyboardInterrupt):
        print()
        return None
    chosen = [ex for ex in pack.exercises if not mode or ex.mode.startswith(mode)]
    return (pack, chosen) if chosen else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drill", description="Rapid-fire coding exercises, solved in your own editor."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for mode in MODES:
        p = sub.add_parser(mode, help=MODE_HELP[mode], description=f"Start a session of {MODE_HELP[mode]}.")
        add_session_options(p, os.environ.get("DRILL_LANG", "python"))

    p = sub.add_parser(
        "run", help="practise chosen exercises",
        description="Start a session on the exercises matching any query: an exact id, or "
                    "part of an id, title, tag or mode. A single exercise repeats, kata style.",
    )
    p.add_argument("queries", nargs="+", metavar="query")
    add_session_options(p, None)

    p = sub.add_parser("search", help="find exercises by id, title, tag or mode")
    p.add_argument("queries", nargs="+", metavar="query")

    p = sub.add_parser("stats", help="show your progress")
    p.add_argument("-e", "--exercises", action="store_true", help="also list every exercise")

    p = sub.add_parser("list", help="list the exercises")
    p.add_argument("mode", nargs="?", choices=MODES)

    p = sub.add_parser("check", help="verify the reference solutions against their tests")
    p.add_argument("ids", nargs="*", help="exercise ids (default: all)")
    p.add_argument("-l", "--lang", type=parse_langs, default="mix")

    p = sub.add_parser(
        "prompt", help="the prompt asking an AI for a pack made from your course",
        description="Print the prompt to send to an AI with your course material; it replies "
                    "with a pack file for `drill pack add`.",
    )
    p.add_argument(
        "-l", "--lang", type=parse_langs, default=os.environ.get("DRILL_LANG", "python"),
        help="languages of the exercises (default: $DRILL_LANG or python; mix for all)",
    )
    p.add_argument("-n", "--count", type=int, default=20, help="number of exercises (default: 20)")
    p.add_argument("-c", "--copy", action="store_true", help="copy it to the clipboard instead")

    p = sub.add_parser(
        "pack", help="custom packs of exercises made from your course",
        description="Without a subcommand: choose an installed pack and a mode, and practise.",
    )
    add_session_options(p, None)
    pack_sub = p.add_subparsers(dest="pack_command", metavar="{list,add,run,check,remove}")
    pack_sub.add_parser("list", help="list the installed packs")
    pp = pack_sub.add_parser("add", help="check a pack file, then install it")
    pp.add_argument("file", type=Path)
    pp.add_argument("--name", help="the name to install it under (default: from the file)")
    pp.add_argument("--force", action="store_true", help="install even if some exercises fail")
    pp = pack_sub.add_parser("run", help="practise a pack")
    pp.add_argument("name")
    pp.add_argument("--mode", choices=MODES, help="only this mode (default: all)")
    add_session_options(pp, None)
    pp = pack_sub.add_parser("check", help="check an installed pack again")
    pp.add_argument("name")
    pp = pack_sub.add_parser("remove", help="delete an installed pack")
    pp.add_argument("name")

    args = parser.parse_args(argv)
    if args.command == "pack":
        return pack_command(parser, args)
    if args.command == "prompt":
        show_prompt(args.lang, args.count, args.copy)
        return 0
    exercises = load_all()

    if args.command in MODES:
        chosen = [ex for ex in exercises if ex.mode == args.command]
        run_session(parser, args, args.command, chosen)
    elif args.command in ("run", "search"):
        chosen = search(exercises, args.queries)
        if not chosen:
            print(red(f"No exercise matches {' '.join(args.queries)}. Try `drill list`."))
            return 1
        if args.command == "search":
            for ex in chosen:
                print(exercise_row(ex) + dim(f"  {ex.mode}"))
        else:
            run_session(parser, args, "run", chosen)
    elif args.command == "stats":
        pack_exercises = [ex for pack in packs.installed() for ex in pack.exercises]
        stats.show(Store(), exercises + pack_exercises, args.exercises)
    elif args.command == "list":
        list_exercises(exercises, args.mode)
    elif args.command == "check":
        return 1 if check(exercises, args.lang, args.ids) else 0
    return 0


def pack_command(parser: argparse.ArgumentParser, args) -> int:
    command = args.pack_command
    if command == "add":
        return add_pack(args.file, args.name, args.force)
    if command == "list":
        list_packs(packs.installed())
        return 0
    if command is None:
        picked = choose_pack(packs.installed())
        if picked is None:
            return 1
        pack, chosen = picked
        run_session(parser, args, f"pack:{pack.slug}", chosen)
        return 0
    pack = packs.find(args.name)
    if pack is None:
        print(red(f"No installed pack matches {args.name!r}. `drill pack list` shows them."))
        return 1
    if command == "run":
        chosen = [ex for ex in pack.exercises if not args.mode or ex.mode == args.mode]
        if not chosen:
            print(red(f"Pack {pack.slug} has no {args.mode} exercises."))
            return 1
        run_session(parser, args, f"pack:{pack.slug}", chosen)
    elif command == "check":
        for error in pack.errors:
            print(red(f"  ✗ {error}"))
        return 1 if check(pack.exercises, list(LANGUAGES.values()), []) or pack.errors else 0
    elif command == "remove":
        pack.path.unlink()
        print(f"Removed pack {pack.slug}.")
    return 0

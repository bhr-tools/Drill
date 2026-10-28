"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import adding, completion, listing, prompt, stats, sync
from .checking import check, copy_to_clipboard
from .exercises import MODES, Exercise
from .help import HELP
from .langs import ALIASES, LANGUAGES, Language
from .learn import Course
from .library import Collection, Library, LibraryError
from .listing import MODE_HELP, select
from .session import Session
from .store import Store
from .term import bold, cyan, dim, red


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


def add_prompt_options(
    p: argparse.ArgumentParser, lang_default: str | None, locale: bool = True
) -> None:
    p.add_argument(
        "-l", "--lang", type=parse_langs, default=lang_default,
        help=f"languages of the exercises: {', '.join(LANGUAGES)}, a comma-separated list, or "
             "mix" + ("" if lang_default else " (default: the ones the material uses, else "
                                               "$DRILL_LANG or python)"),
    )
    if locale:
        p.add_argument(
            "-L", "--locale", choices=list(prompt.LOCALES),
            default=os.environ.get("DRILL_LOCALE", "en"),
            help="language of the statements and lessons (default: $DRILL_LOCALE or en)",
        )
    p.add_argument("--print", action="store_true", help="print the prompt instead of copying it")


def add_material_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--topic", help="the part of the material to cover, or the subject without it")
    p.add_argument(
        "--no-material", action="store_true",
        help="no course material attached: the AI works from --topic alone",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drill", description="Rapid-fire coding exercises, solved in your own editor.",
        epilog="`drill help` explains levels, reviews, variants, packs and courses.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for mode in MODES:
        p = sub.add_parser(mode, help=MODE_HELP[mode], description=f"Start a session of {MODE_HELP[mode]}.")
        add_session_options(p, os.environ.get("DRILL_LANG", "python"))

    p = sub.add_parser(
        "pack", help="practise a pack", description="Practise a pack (asks which one without a name).",
    )
    p.add_argument("name", nargs="?", help="the pack's name, or a part of it")
    p.add_argument("--mode", choices=MODES, help="only this mode (default: all)")
    add_session_options(p, None)

    p = sub.add_parser(
        "learn", help="follow a learn course",
        description="Follow a learn course: its steps in order, with reviews of the steps done.",
    )
    p.add_argument("name", nargs="?", help="the course's name, or a part of it")
    add_session_options(p, None)

    p = sub.add_parser(
        "run", help="practise chosen exercises",
        description="Start a session on the exercises named by an exact id, or matching every "
                    "other query (a part of an id, a title, a tag, a mode, drill, pack, learn). "
                    "A single exercise repeats, kata style.",
    )
    p.add_argument("queries", nargs="+", metavar="query")
    add_session_options(p, None)

    p = sub.add_parser(
        "list", help="the exercises and your progress on each",
        description="List the exercises named by an exact id, or matching every query (a part "
                    "of an id, a title, a tag, a mode, drill, pack, learn), with your progress. "
                    "A single match shows its sheet: variants and history.",
        epilog="`drill help` explains levels and reviews.",
    )
    p.add_argument("queries", nargs="*", metavar="query")
    p.add_argument("-l", "--lang", type=parse_langs, help="only exercises in these languages, "
                   "with your progress in them")
    p.add_argument("--due", action="store_true", help="only the exercises due for review")
    p.add_argument("--new", action="store_true", help="only the exercises never done")

    sub.add_parser("stats", help="your progress", epilog="`drill help` explains levels and reviews.")

    p = sub.add_parser(
        "prompt", help="the request to send an AI for new exercises",
        description="Copy the request to send an AI. Its reply goes through `drill add`.",
    )
    kinds = p.add_subparsers(dest="kind", required=True)
    pp = kinds.add_parser(
        "drill", help="one exercise for the base, from an idea or a statement seen elsewhere",
    )
    pp.add_argument("idea", nargs="*", help="the idea or the statement (default: read stdin)")
    add_prompt_options(pp, "mix", locale=False)
    pp = kinds.add_parser("pack", help="a pack aimed at one goal, from your course material")
    pp.add_argument("-n", "--count", type=int, default=20, help="number of exercises (default: 20)")
    add_material_options(pp)
    add_prompt_options(pp, None)
    pp = kinds.add_parser(
        "learn", help="a course to learn a subject step by step, with lessons",
        description="The AI first plans the course from the material (chapters, steps, their "
                    "number), then writes it one chapter per reply, each added with `drill add`.",
    )
    add_material_options(pp)
    add_prompt_options(pp, None)
    pp = kinds.add_parser("variant", help="new variants of an exercise of the library")
    pp.add_argument("id", help="the exercise's id")
    pp.add_argument("-n", "--count", type=int, default=2, help="number of variants (default: 2)")
    pp.add_argument("--print", action="store_true", help="print the prompt instead of copying it")

    p = sub.add_parser(
        "add", help="check an AI's reply, then file it in the library",
        description="Check an exercise, pack, course or variants (from the clipboard, or a file),"
                    " then file it in the library.",
    )
    p.add_argument("file", type=Path, nargs="?", help="a TOML file (default: the clipboard)")
    p.add_argument("--to", help="for an exercise: the library folder to file it in "
                   "(default: drill/<its language>, or drill/shared)")
    p.add_argument("--force", action="store_true", help="add it even if some checks fail")

    p = sub.add_parser("rm", help="remove an exercise, a pack or a course from the library")
    p.add_argument("target", help="an exercise id, or a pack's or course's name")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    p = sub.add_parser("check", help="verify the reference solutions against their tests")
    p.add_argument("queries", nargs="*", metavar="query", help="exercises (default: all)")
    p.add_argument("-l", "--lang", type=parse_langs, default="mix")

    p = sub.add_parser("completion", help="the shell completion script")
    p.add_argument("shell", choices=list(completion.SCRIPTS))

    sub.add_parser("help", help="how drill works: levels, reviews, variants, packs, courses")
    return parser


def run_session(
    parser, args, store: Store, name: str, chosen: list[Exercise], course: Course | None = None
) -> Session:
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
    session = Session(name, chosen, langs, store, editor, args.minutes, args.keep, course)
    session.run()
    return session


def choose(collections: list[Collection], kind: str, name: str | None) -> Collection | None:
    """The collection named, or the one the user picks."""
    if not collections:
        print(f"No {kind} yet. `drill prompt {kind}` writes the request to make one.")
        return None
    if name is not None:
        found = next((c for c in collections if name in (c.slug, c.name)), None)
        matches = [c for c in collections if name.lower() in c.slug or name.lower() in c.name.lower()]
        found = found or (matches[0] if len(matches) == 1 else None)
        if found is None:
            print(red(f"No {kind} matches {name!r}. `drill list {kind}` shows them."))
        return found
    if len(collections) == 1:
        return collections[0]
    for index, c in enumerate(collections, 1):
        print(f"  {bold(str(index))}  {bold(c.name)}  {dim(f'({c.slug}) · {c.counts()}')}")
    try:
        answer = input(f"\n{kind.capitalize()} [1-{len(collections)}]: ").strip()
        return collections[int(answer) - 1]
    except (ValueError, IndexError, EOFError, KeyboardInterrupt):
        print()
        return None


def show_prompt(text: str, printed: bool, attach: bool, learn: bool = False) -> None:
    if printed or not copy_to_clipboard(text):
        print(text)
        first = "That was the prompt."
    else:
        first = "The prompt is in the clipboard."
    paste = "1. Paste it to Claude" + (", and attach your course material (PDFs)." if attach else ".")
    if learn:
        steps = [
            first,
            paste + " It replies with the plan of the course.",
            "2. Ask for changes if you want, then approve it: it sends the first chapter.",
            "3. Copy each chapter, run `drill add` (it is appended to the course), then answer",
            "   \"next\". If something is wrong, the request to fix it is copied: paste it back.",
        ]
    else:
        steps = [
            first,
            paste,
            "2. Copy its reply, then run `drill add`: it checks the reply and files it.",
            "   If something is wrong, the request to fix it is copied for you: paste it back.",
        ]
    print(cyan("\n".join(steps)), file=sys.stderr)


def prompt_command(parser, args, lib_or_none) -> int:
    kind = args.kind
    if kind == "variant":
        lib = lib_or_none()
        found = adding.find_exercise(lib, args.id)
        if found is None:
            print(red(f"No exercise {args.id} in the library."))
            return 1
        ex, path = found
        langs = [key for key in LANGUAGES if any(i.supports(key) for i in ex.instances)]
        text = prompt.build_variant(adding.exercise_text(ex, path), ex.id, langs, args.count)
        show_prompt(text, args.print, attach=False)
        return 0
    langs = [lang.key for lang in args.lang] if args.lang else None
    fallback = os.environ.get("DRILL_LANG", "python")
    if kind == "drill":
        idea = " ".join(args.idea) or (sys.stdin.read() if not sys.stdin.isatty() else "")
        if not idea.strip():
            parser.error("describe the exercise: drill prompt drill \"...\" (or through stdin)")
        show_prompt(prompt.build_drill(langs, idea), args.print, attach=False)
        return 0
    material = not args.no_material
    if not material and not args.topic:
        parser.error("--no-material needs --topic: the subject to cover")
    if kind == "pack":
        text = prompt.build_pack(
            langs, args.count, args.locale, material, args.topic, fallback
        )
    else:
        text = prompt.build_learn(langs, args.locale, material, args.topic, fallback)
    show_prompt(text, args.print, attach=material, learn=kind == "learn")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if argv[:1] == ["__complete"]:
        shell, position, *words = argv[1:]
        print(completion.complete(parser, shell, int(position), words))
        return 0
    args = parser.parse_args(argv)
    command = args.command
    if command == "help":
        print(HELP)
        return 0
    if command == "completion":
        print(completion.SCRIPTS[args.shell], end="")
        return 0

    def library() -> Library:
        try:
            lib = Library()
        except LibraryError as e:
            raise SystemExit(f"drill: {e}") from None
        return lib

    sessions = (*MODES, "run", "pack", "learn")
    if command == "prompt" and args.kind != "variant":
        return prompt_command(parser, args, library)
    root = library().root
    sync.pull(root, force=command in (*sessions, "add", "rm"))
    lib = Library(root)
    if command == "prompt":
        return prompt_command(parser, args, lambda: lib)
    if command in ("add", "rm"):
        if command == "add":
            code = adding.add(lib, args.file, args.to, args.force)
        else:
            code = adding.remove(lib, args.target, args.yes)
        if code == 0:
            sync.push(root, command)
        return code
    lib.warn()
    store = Store(root / "history")

    if command in sessions:
        session = start(parser, args, lib, store)
        if session is None:
            return 1
        sync.push(root, f"{session.name} session, {session.n_solved} solved")
        return 0
    if command == "list":
        langs = [lang.key for lang in args.lang] if args.lang else None
        return listing.show(lib, store, args.queries, langs, args.due, args.new)
    elif command == "stats":
        stats.show(store, lib)
    elif command == "check":
        chosen = select(lib.exercises(), args.queries) if args.queries else lib.exercises()
        if args.queries and not chosen:
            print(red(f"No exercise matches {' '.join(args.queries)}."))
            return 1
        errors = [] if args.queries else [
            f"{c.slug}: {error}" for c in lib.collections for error in c.errors
        ]
        for error in errors:
            print(red(f"  ✗ {error}"))
        return 1 if check(chosen, args.lang) or errors or lib.errors else 0
    return 0


def start(parser, args, lib: Library, store: Store) -> Session | None:
    """Run the session a command asks for; None if there is nothing to practise."""
    command = args.command
    if command in MODES:
        chosen = [ex for ex in lib.drill if ex.mode == command]
        return run_session(parser, args, store, command, chosen)
    if command == "run":
        chosen = select(lib.exercises(), args.queries)
        if not chosen:
            print(red(f"No exercise matches {' '.join(args.queries)}. Try `drill list`."))
            return None
        return run_session(parser, args, store, "run", chosen)
    collection = choose(lib.of_kind(command), command, args.name)
    if collection is None:
        return None
    chosen = collection.exercises
    if command == "pack" and args.mode:
        chosen = [ex for ex in chosen if ex.mode == args.mode]
    if not chosen:
        print(red(f"{collection.slug} has no exercises to practise."))
        return None
    course = Course(collection, store) if command == "learn" else None
    return run_session(parser, args, store, f"{command}:{collection.slug}", chosen, course)

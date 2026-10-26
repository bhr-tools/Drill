# Drill

Rapid-fire coding exercises, solved in your own editor.

Drill gives you one exercise at a time. You write the solution in your usual
editor, and every time you save, the tests run. As soon as they pass, the next
exercise starts. You never leave the keyboard, and you train with your own
shortcuts, snippets and language server.

```
$ drill sprint -l cpp -m 30
```

## Modes

- `drill sprint`: very short exercises (1–2 min targets). Idioms, classic
  patterns, the reflexes you want instant.
- `drill normal`: exercises that need a bit more thought (5–10 min targets).
  Choosing the right structure is part of the drill: sliding window,
  monotonic stack, union-find, Dijkstra, DP…
- `drill hard`: data structures and language subtleties (12–20 min targets).
  An LRU cache, a versioned store or a trie, written idiomatically in each
  language. Also decorators, generators and dataclasses in Python; move
  semantics, custom iterators and variadic templates in C++; generics with
  wildcards and `equals`/`hashCode`/`compareTo` in Java.
- `drill optim`: the code you start with works, but it is too slow. Estimate
  its complexity, measure it, then make it fast enough for the performance
  test. Once it is solved, an explanation covers the theory: why the first
  version was slow and why the new one is faster.

Each mode also has language idioms (ids starting with `py-`, `cpp-`, `java-`),
served only when you train in that language.

## Languages

Python, C++ and Java share the general exercises (algorithms and data
structures), on top of their own idioms. OCaml and Nix only get exercises
written for them, about what each language is for:

- OCaml (`-l ocaml`, ids `ml-`): pattern matching, variant types, recursion with
  accumulators, `Option`, `Result` and `let*`, `Map.Make` and `Set.Make`,
  functors, lazy `Seq`. A few list-friendly classics (merging, parentheses,
  maximum subarray) also have an OCaml version.
- Nix (`-l nix`, ids `nix-`): the language and `lib` (attribute sets, lists,
  strings, fixed points), packaging (`mkDerivation`, `writeShellApplication`,
  raw `derivation`), overlays (`final` and `prev`), flakes (dev shells, outputs
  per system, NixOS modules and configurations), the NixOS module system
  (options, `mkIf`, priorities and merging), and exploring a configuration in
  `nix repl`. For those, the folder contains the files the exercise is about (a
  flake, a project to package, a base module), and the file to edit is the one
  the exercise names: `flake.nix`, `package.nix`, `module.nix`, `answer.nix`…

Nix exercises are checked by evaluating your file with `nix-instantiate`,
without network: a flake's `nixpkgs` input is the nixpkgs drill was built with
(`$DRILL_NIXPKGS`, else `<nixpkgs>`), and checks build only small things. The
`c` key and performance tests do not apply to Nix.

## Variants

Many exercises come in several variants: the same concept on other data, or
with a twist (a lower bound instead of an exact search, a difference instead of
a sum, a dev shell for Node instead of Python). The variants share the schedule
of their exercise, and each time it comes back, drill serves the variant you
have practised least recently, so that you learn the concept rather than one
answer. `drill list` shows the number of variants (`×3`).

To practise specific exercises:

```
$ drill search iterator          # by id, title, tag or mode
$ drill run lru-cache -l cpp     # one exercise, again and again (kata)
$ drill run graph dp             # every exercise tagged graph or dp
```

Without `-l`, `drill run` uses your default language when the exercises
support it, and otherwise every language they support.

Options for both:

| Option | |
|---|---|
| `-l python`, `-l cpp,java`, `-l nix`, `-l mix` | language(s); `mix` alternates all of them |
| `-m 30` | stop after 30 minutes |
| `-e code`, `-e none` | command that opens the exercise file (default: `$DRILL_EDITOR`, else `code` if found) |
| `--keep` | keep the session folder at the end |

## During a session

The exercise is written to a temporary folder (`/tmp/drill-…`), with the
statement and examples as a comment at the top of the file. The folder is
removed when the session ends.

| Key | |
|---|---|
| save the file | run the tests |
| `h` | show the hint (the attempt then cannot set a record) |
| `s` | skip: shows the reference solution, and the exercise comes back soon |
| `p` | pause the clock |
| `r` | rerun the tests |
| `o` | reopen the file in the editor |
| `c` | measure the complexity of your code (exercises that support it) |
| `q` | quit |

After a solve, the next exercise starts after 3 seconds. Press `v` to read
the reference solution first, `p` to hold, or `enter` to go right away.

With VS Code, the most comfortable setup is running `drill` in the integrated
terminal. With a terminal editor, use `-e none` and open the printed path in
another pane. The file is rewritten in place for each exercise.

## Measuring complexity

On most function exercises, `c` asks for your estimate of your code's time
complexity, then times it on inputs of growing size (1 000, 2 000, 4 000…, up to
the first size that takes over 1.5 s). The reference solution gets the same
treatment, and you see both side by side:

```
            n          yours      reference
        1,000         144 µs          68 µs
        …
       64,000       452.4 ms         5.2 ms
      128,000     over 1.5 s        11.2 ms
  your code   ~ n^2.09 → O(n²)
  reference   ~ n^1.06 → O(n) or O(n log n)
✓ Your estimate O(n²) matches the measurement.
↗ The optimal complexity is O(n): this code can do better.
```

A running time in O(nᵏ) is a line of slope k on a log-log scale, so the slope
measured over the largest sizes gives the growth. Timing cannot tell n from
n log n, or 1 from log n: both are then reported as consistent. On large inputs,
cache misses make each operation slower, which makes the slope read a little
high. The comparison allows for that. The clock is paused during the
measurement, and `drill stats` keeps track of how often your estimates are right.

## Packs made from your course

A pack is a set of exercises on what you are studying, generated by an AI from
your course material and kept apart from the built-in exercises:

```
$ drill prompt -l python,cpp -n 20 --copy   # the prompt, copied to the clipboard
$ drill prompt -l nix --copy                # a Nix / NixOS pack
```

The prompt asks for exercises that suit each language rather than the same
exercise translated everywhere, and for two or three variants per exercise.

1. Send the prompt to Claude with the PDFs of your lectures, tutorials and lab sheets.
2. Save the TOML file it replies with, e.g. `graphs.toml`.
3. `drill pack add graphs.toml` runs every reference solution against its tests,
   then installs the pack in `~/.local/share/drill/packs/`. If an exercise fails,
   the pack is rejected and drill prints a message to paste back to Claude to get
   a corrected file.
4. `drill pack` lists your packs, asks which one and which mode (sprint, normal,
   hard, optim), and starts the session.

```
$ drill pack list
$ drill pack run graphs --mode hard -l cpp
$ drill pack remove graphs
```

`examples/sorting-pack.toml` is a small example pack.

## Scheduling

Every (exercise, language) pair lives in a Leitner box:

- solved within the target: it moves up a box (next review in 1, 3, 7, 16, 35 days);
- within twice the target, or with the hint: it moves down a box;
- slower than that, or skipped: it comes back later in the same session.

Sessions serve due reviews first, mixed with new exercises.

## Statistics

```
$ drill stats        # by language, trend, weakest tags, streak
$ drill stats -e     # plus every exercise: best time, box, next review
```

History is stored in `~/.local/share/drill/history.db` (SQLite).

## Writing exercises

There are two kinds of exercises. A function exercise is one TOML file,
written once for every language:

```toml
title = "Two sum"
tags = ["hashmap"]
target = 90                       # seconds
signature = "two_sum(nums: list[int], target: int) -> list[int]"
statement = """
Return the indices [i, j], with i < j, of the two numbers that add up to target.
"""
hint = "Remember each value's index in a hashmap."
tests = [
  { in = [[2, 7, 11, 15], 9], out = [0, 1] },
  { in = [[3, 3], 6], out = [0, 1] },
]

[solutions]
python = '''
def two_sum(nums, target): ...
'''
cpp = '''
vector<int> twoSum(vector<int>& nums, int target) { ... }
'''
java = '''
public int[] twoSum(int[] nums, int target) { ... }
'''
```

- `[[perf]]` entries add performance tests, generated from Python with a
  seeded `rng` (`random.Random`), so they are identical on every run. The
  expected output comes from the Python reference solution unless `out` is
  given. `limit` is in seconds (default 2). The harness stops the solution as
  soon as it goes over the limit:

  ```toml
  [[perf]]
  label = "n = 200 000"
  in = "[[rng.randint(-10_000, 10_000) for _ in range(200_000)]]"

  [[perf]]
  label = "n = 300 000, the pair at the very end"
  code = '''
  nums = [2 * x for x in rng.sample(range(-10**8, 10**8), 300_000)]
  nums[-2] += 1
  args = [nums, nums[-2] + nums[-1]]
  '''
  ```

  Size them so the naive solution fails even in C++ and Java (around 10¹⁰
  operations), while the reference stays well under the limit. `drill check`
  shows how much of the limit each reference uses.
- `complexity` (the optimal one: `O(1)`, `O(log n)`, `O(n)`, `O(n log n)`,
  `O(n²)`, `O(n³)` or `O(2ⁿ)`) and a `[scale]` table enable the `c` key. The
  `[scale]` table takes an `in` expression or a `code` block, like `[[perf]]` but
  with `n` defined, plus optional `label`, `sizes` and `limit` (seconds per
  size, default 1.5). Its outputs are not checked.
- `explanation`: the theory behind the solution, shown with the reference
  solution, and after each solve in optim mode.
- `[starter]` gives the starting code per language, instead of an empty
  function. An optim exercise starts from its slow solution this way.
- Types: `int`, `long`, `bool`, `str` and `list[...]` of those, nested as
  deep as needed. They map to `vector<>` in C++, arrays in Java and lists in
  OCaml. `any` is any JSON value (attribute sets in Nix), for Python and Nix
  only. Function and parameter names are written in snake_case and become
  camelCase in C++, Java and Nix.
- `[[variants]]` add variants: each replaces any key it sets (statement,
  signature, tests, solutions, starter, checks, files…). One that sets a
  signature needs its own tests and solutions.
- The mode comes from the folder (`sprint/`, `normal/`, `hard/`, `optim/`), or a `mode` key.
- Reference solutions skip the boilerplate: no includes in C++, no `class
  Solution` wrapper in Java.
- `langs = ["python"]` restricts an exercise to some languages. Without it, a
  function exercise is offered in the languages of its solutions (in Python,
  C++ and Java when it has none).
- OCaml function solutions are top-level definitions; Nix ones are the function
  itself (`xs: target: …`), with `{ lib }:` added above.

A code exercise (`kind = "code"`) is for what a signature cannot express:
classes, generators, templates, iterators. It has a starter and tests written
in each language it supports:

```toml
title = "Generic LRU cache"
kind = "code"
target = 900
statement = "..."

[starter]
python = '''
class LRUCache: ...
'''

[setup]      # optional: file-level helpers for the checks
python = "..."

[checks]
python = '''
cache = LRUCache(2)
check("get a", cache.get("a"), None)            # check(label, got, expected=True)
raises("bad capacity", ValueError, LRUCache, -1)
'''
cpp = '''
CHECK(cache.size() == 0);
CHECK_EQ(cache.get("a"), std::optional<int>());
CHECK_THROWS(std::invalid_argument, LRUCache<int, int>(-1));
'''
java = '''
check("get a", cache.get("a"), null);           // or check(label, condition)
checkThrows("bad capacity", IllegalArgumentException.class, () -> new LRUCache<>(-1));
'''

[solutions]  # whole files
python = "..."
```

Each check counts as one test. C++ checks run inside a function body, Java
checks inside a static method of `Main`. C++ is compiled with
`-Werror=return-type`, so a function that is missing a return fails to
compile instead of crashing.

OCaml checks run after `open Solution`, separated by `;`: `check label cond`,
`check_eq ~show:Show.(list int) label got expected`, `check_raises label (fun
() -> …)`.

Nix checks are a list of `(check "label" got expected)` and `(checkThrows
"label" value)`, with `[setup]` holding let bindings. In scope: `lib`, `pkgs`,
`nixpkgs`, `system`, `dir` (the folder) and `file` (your file), plus
`loadFlake dir`, `nixos [ modules ]`, `sh "script"` (the output of a script run
in a build), `contains` and `packageNames`. A code exercise can name the file to
edit (`file = "flake.nix"`) and give files next to it (`[files]`), where
`@NIXPKGS@` stands for the local nixpkgs:

```toml
kind = "code"
file = "package.nix"

[files]
"src/greet.c" = "…"

[setup]
nix = "greet = pkgs.callPackage file { };"

[checks]
nix = '''
(check "pname" (greet.pname or null) "greet")
(check "it runs" (sh "${greet}/bin/greet") "Hello\n")
'''
```

Built-in exercises live in `src/drill/exercises/`. Your own go in
`~/.local/share/drill/exercises/` or any folder listed in `$DRILL_EXERCISES`.
Check them with:

```
$ drill check              # every reference solution against its tests
$ drill check two-sum -l cpp
```

## Development

```
$ nix develop
$ drill check      # runs the working tree
$ nix build        # the packaged app, with g++, the JDK and OCaml on its PATH
```

The first C++ run builds a precompiled `<bits/stdc++.h>` in `~/.cache/drill`
(about 150 MB, a few seconds). After that, each C++ build takes about 0.5 s.

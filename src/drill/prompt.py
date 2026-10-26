"""The prompt that asks an AI for a pack of exercises built from course material."""

from __future__ import annotations

from .complexity import CLASSES

NIX_NOTES = """\
Nix: train what Nix is used for, not generic algorithms. The language (attribute sets,
lib functions, laziness, recursion, fixed points, string interpolation), packaging
(mkDerivation and its phases, callPackage, writeShellApplication, override and
overrideAttrs, overlays with final and prev), flakes (inputs, outputs per system,
devShells, packages, apps, overlays, nixosModules, nixosConfigurations), the NixOS module
system (options and types, mkIf, mkMerge, mkDefault, mkForce, mkBefore, mkAfter), and
exploring a configuration in nix repl. No perf, scale or complexity for Nix.
  Function exercises: the solution is the function itself, curried (`xs: target: …`);
  `{ lib }:` is added above it for you, so lib is in scope. Names are camelCase. They
  may use the type any (any JSON value: attribute sets are objects, with string keys).
  Code exercises: the student edits one file, named by `file` (flake.nix, package.nix,
  module.nix, overlay.nix, answer.nix…), next to the files given in
  [exercises.files] (paths relative to the folder: sources to package, a base module, a
  flake to explore…). In those files, @NIXPKGS@ is replaced by the path of a local
  nixpkgs: a flake given to explore uses inputs.nixpkgs.url = "path:@NIXPKGS@", so
  that `nix repl` then `:lf .` works offline. A flake the student writes has nixpkgs as
  its only input; the checks load it without a lock or network.
  Checks are a list of parenthesised items, one per test case, each a call to:
  (check "label" got expected), compared with ==; (checkThrows "label" value), which
  must fail with a throw or an assert (a type error of the module system counts).
  [exercises.setup] holds let bindings (`name = value;`) used by the checks.
  In scope: lib, pkgs (nixpkgs for the current system), nixpkgs (its path), system,
  dir (the folder, with the student's file in it), file (the student's file: import it,
  or pkgs.callPackage file { }), loadFlake dir (the flake's outputs, its nixpkgs input
  provided), nixos modules (lib.nixosSystem on top of a minimal bootable base: use
  .config and .options), sh "script" (the output of a shell script run in a build
  sandbox, building what it refers to, followed by "exit status N" if it fails),
  contains needle haystack (hasInfix, store paths allowed), packageNames drv (the names
  of a derivation's or a shell's inputs). Prefer evaluating attributes to building; build
  (sh, readFile of an output) only small things. When an expected value depends on the
  nixpkgs version (a package version, an option default), compute it in the check
  rather than writing it, and write the reference solution as an expression too."""

LANG_NOTES = {
    "python": (
        "Python: function solutions are the plain function (imports allowed above it). "
        "Use idiomatic Python: comprehensions, collections, itertools, heapq, bisect."
    ),
    "cpp": (
        "C++20: function solutions are just the function: <bits/stdc++.h> and "
        "`using namespace std;` are added for you. Types: list[int] is vector<int>, "
        "passed as vector<int>&; str is const string&; long is long long. Names are "
        "camelCase (two_sum becomes twoSum)."
    ),
    "java": (
        "Java 21: function solutions are only the method(s) of `class Solution` (no class "
        "line), `java.util.*` and `java.util.stream.*` are imported. Types: list[int] is "
        "int[], list[str] is String[], list[list[int]] is int[][], long is long, bool is "
        "boolean. Names are camelCase (two_sum becomes twoSum)."
    ),
    "ocaml": (
        "OCaml 5: function solutions are top-level definitions (let rec, helpers, modules), "
        "compiled as module Solution. Types: list[int] is int list (lists, not arrays), str is "
        "string, long is int. Names stay snake_case. Train what OCaml is about: pattern "
        "matching, variant types, recursion with accumulators, List/Option/Result/Seq, Map.Make "
        "and Set.Make, modules and functors, immutability. Code exercises fit OCaml best, as "
        "the signature types cannot express variants, records or modules. Checks run after "
        "`open Solution`, between begin and end: separate them with `;`, and bind values with "
        "`let x = … in`. Helpers: check label condition; check_eq ~show label got expected "
        "(structural equality; show is a printer, built from Show.int, Show.string, Show.bool, "
        "Show.float, Show.list, Show.array, Show.option, Show.pair, Show.result, e.g. "
        "Show.(list (pair string int))); check_raises ?matches label (fun () -> …), matches "
        "being an exn -> bool. In starters, write bodies as failwith \"todo\"."
    ),
    "nix": NIX_NOTES,
}

FUNCTION_EXAMPLE = """\
[[exercises]]
id = "two-sum"
mode = "sprint"                 # sprint | normal | hard | optim
title = "Two sum"
tags = ["hashing", "arrays"]    # the course concepts it trains
target = 90                     # seconds a fluent student needs
signature = "two_sum(nums: list[int], target: int) -> list[int]"
statement = \"\"\"
Return the indices [i, j], with i < j, of the two numbers of nums that add up
to target. There is exactly one answer.
\"\"\"
hint = "Remember each value's index in a hashmap; look up target - x first."
explanation = \"\"\"
(normal, hard and optim only) The theory: why the solution works, its
complexity, the pitfall. 5 to 15 lines, like a good textbook.
\"\"\"
complexity = "O(n)"             # optional: the optimal time complexity
tests = [
  { in = [[2, 7, 11, 15], 9], out = [0, 1] },
  { in = [[3, 3], 6], out = [0, 1] },
  { in = [[-1, -2, -3, -4, -5], -8], out = [2, 4] },
]

[exercises.solutions]
python = '''
def two_sum(nums, target):
    seen = {}
    for j, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], j]
        seen[x] = j
    return []
'''
cpp = '''
vector<int> twoSum(vector<int>& nums, int target) {
    unordered_map<int, int> seen;
    for (int j = 0; j < (int)nums.size(); ++j) {
        if (auto it = seen.find(target - nums[j]); it != seen.end()) return {it->second, j};
        seen[nums[j]] = j;
    }
    return {};
}
'''
java = '''
public int[] twoSum(int[] nums, int target) {
    Map<Integer, Integer> seen = new HashMap<>();
    for (int j = 0; j < nums.length; j++) {
        Integer i = seen.get(target - nums[j]);
        if (i != null) return new int[]{i, j};
        seen.put(nums[j], j);
    }
    return new int[0];
}
'''

# Optional: a performance test with a large generated input. `in` is a Python
# expression (or `code` a block that sets `args`), with `rng` a seeded
# random.Random. Its expected output is computed by the Python solution.
[[exercises.perf]]
label = "n = 200 000"
code = '''
nums = [2 * x for x in rng.sample(range(-10**8, 10**8), 200_000)]
nums[-2] += 1  # the only odd value: exactly one answer
args = [nums, nums[-2] + nums[-1]]
'''

# Optional, with `complexity`: inputs of size n, used when the student measures
# the complexity of their code. Same syntax, with `n` defined.
[exercises.scale]
label = "n = len(nums)"
code = '''
nums = [2 * x for x in rng.sample(range(-10**8, 10**8), n)]
nums[-2] += 1
args = [nums, nums[-2] + nums[-1]]
'''

# Variants: the same concept on other data or with another twist. A variant replaces
# any key it sets; when it sets a signature, it also needs its own tests and solutions.
[[exercises.variants]]
signature = "pair_with_difference(nums: list[int], k: int) -> list[int]"
statement = \"\"\"
Return the indices [i, j], with i < j, of the first pair (by j, then by i) such that
nums[j] - nums[i] == k. There is exactly one answer.
\"\"\"
hint = "Look up nums[j] - k in a hashmap of the values seen so far."
tests = [
  { in = [[1, 5, 3, 4], 2], out = [0, 2] },
  ...
]
[exercises.variants.solutions]
python = '''...'''
cpp = '''...'''
java = '''...'''
"""

CODE_EXAMPLE = """\
[[exercises]]
id = "lru-cache"
mode = "hard"
kind = "code"
title = "Generic LRU cache"
tags = ["hashing", "linked-lists", "design"]
target = 900
statement = \"\"\"
Implement a least-recently-used cache with a fixed capacity: get(key) returns the
value or nothing and marks the key as recently used; put(key, value) inserts or
updates, evicting the least recently used key when over capacity. Both in O(1).
A capacity below 1 raises ValueError (Python) or std::invalid_argument (C++).
\"\"\"
hint = "A hash map to the nodes of a doubly linked list ordered by use."
explanation = \"\"\"The theory, as above.\"\"\"

[exercises.starter]   # complete files, given to the student
python = '''
class LRUCache:
    def __init__(self, capacity: int):
        pass

    def get(self, key, default=None):
        pass

    def put(self, key, value) -> None:
        pass
'''
cpp = '''
#include <bits/stdc++.h>

template <class K, class V>
class LRUCache {
public:
    explicit LRUCache(std::size_t capacity) {}
    std::optional<V> get(const K& key) {}
    void put(const K& key, V value) {}
};
'''

[exercises.checks]    # test code, run after the student's file
python = '''
cache = LRUCache(2)
cache.put("a", 1)
cache.put("b", 2)
check("get a", cache.get("a"), 1)          # check(label, got, expected=True)
cache.put("c", 3)
check("b was evicted", cache.get("b"), None)
raises("negative capacity", ValueError, LRUCache, -1)
'''
cpp = '''
LRUCache<std::string, int> cache(2);
cache.put("a", 1);
cache.put("b", 2);
CHECK_EQ(cache.get("a"), std::optional<int>(1));
cache.put("c", 3);
CHECK(!cache.get("b").has_value());
CHECK_THROWS(std::invalid_argument, LRUCache<int, int>(0));
'''

[exercises.solutions] # complete files
python = '''...'''
cpp = '''...'''
"""


NIX_EXAMPLE = '''\
[[exercises]]
id = "package-greet"
mode = "normal"
kind = "code"
file = "package.nix"            # the file the student edits
title = "Packaging with mkDerivation"
tags = ["derivations", "callpackage"]
target = 360
statement = \"\"\"
Package the C program in src/ in package.nix, a function for callPackage: pname
"greet", version "1.0", built with $CC and installed as $out/bin/greet.
\"\"\"
hint = "buildPhase and installPhase: there is no Makefile."

[exercises.files]               # written next to the student's file
"src/greet.c" = \"\"\"
#include <stdio.h>
int main(void) { puts("Hello"); return 0; }
\"\"\"

[exercises.starter]
nix = \'\'\'
{ stdenv }:

stdenv.mkDerivation {
}
\'\'\'

[exercises.setup]               # let bindings for the checks
nix = \'\'\'
greet = pkgs.callPackage file { };
\'\'\'

[exercises.checks]              # a list: one parenthesised check per test case
nix = \'\'\'
(check "pname" (greet.pname or null) "greet")
(check "version" (greet.version or null) "1.0")
(check "it runs" (sh "${greet}/bin/greet") "Hello\\n")
\'\'\'

[exercises.solutions]           # the whole file
nix = \'\'\'
{ stdenv }:

stdenv.mkDerivation {
  pname = "greet";
  version = "1.0";
  src = ./src;
  buildPhase = "$CC greet.c -o greet";
  installPhase = "install -Dm755 greet $out/bin/greet";
}
\'\'\'
'''


def build(langs: list[str], count: int) -> str:
    notes = "\n".join(f"- {LANG_NOTES[key]}" for key in langs)
    names = ", ".join(langs)
    nix_example = f"A Nix code exercise:\n\n{NIX_EXAMPLE}\n" if "nix" in langs else ""
    return f"""\
You are generating a training pack for drill, a command-line tool that serves short
coding exercises one at a time: the student solves each one in their editor and drill
checks it automatically on every save. I am attaching my course material (lecture
notes, tutorials, lab sheets). Build exercises that drill exactly the concepts,
algorithms, data structures and language features this material teaches, using its
vocabulary and its notations. Stay within the material: nothing it does not cover.

# What to produce

Reply with a single TOML file in one ```toml code block, and nothing after it. I will
save it and run `drill pack add` on it: drill parses the file and runs every reference
solution against every test, and rejects the pack if a single expected output is
wrong. So compute each expected output carefully, by running the reference solution
in your head step by step on small inputs you can verify.

Write about {count} exercises, ordered from the basics of the material to its hardest
points, in these languages: {names}.

Each exercise must make sense in every language it is written for: train what the
language is used for and how it is written idiomatically. Never translate an exercise
into a language where it would be unnatural (a Nix exercise about sorting arrays, an
OCaml exercise built around mutable indices): write it for the languages where it fits,
and give it solutions in those only (or set `langs`). An exercise shared by several
languages is fine when the task is natural in each.

Give most exercises 2 or 3 variants ([[exercises.variants]]): the same concept on other
data, or with another twist (another operation, another edge case, the question
reversed), so that the student learns the concept rather than one answer. A variant is
not the same exercise with renamed variables or other numbers. Variants share the
exercise's id, schedule and tags; each must be complete (statement, tests or checks,
solutions) and correct on its own, as drill checks every one.

Three kinds of difficulty, all needed:
- sprint (about 40%): 1 to 3 minutes, one idea, recalled and typed fast: a definition
  turned into code, a standard idiom, a classic small algorithm.
- normal (about 35%): 5 to 10 minutes, where choosing the right structure or algorithm
  is the point.
- hard (about 25%): 12 to 20 minutes: implementing a data structure or an algorithm of
  the course in full, or using the language's subtleties (classes, generics, iterators,
  memory, immutability...) as the course teaches them.
If the material deals with complexity or efficiency, also add a few optim exercises:
their starter is a correct but slow solution, which the student must make fast enough
for the performance test (they need [[exercises.perf]], complexity and scale).

Give each exercise `tags` naming the course concepts it trains (lowercase, hyphenated:
"binary-search", "linked-lists"), so that one concept can be practised on its own.

# File format

The file starts with:

[pack]
name = "Short name of the course or chapter"
description = "One sentence: the course and what the pack covers."

Then one [[exercises]] table per exercise. Its sub-tables are written
[exercises.solutions], [exercises.starter], [exercises.checks], [exercises.setup],
[exercises.files], [exercises.scale], [[exercises.perf]] and [[exercises.variants]] (whose
own sub-tables are [exercises.variants.solutions] and so on), right after their
[[exercises]].

There are two kinds of exercises.

## Function exercises (the default, preferred whenever the task is a function of data)

One signature and data tests, shared by every language: drill generates the starting
code and test harness in each language. Allowed types: int, long, bool, str, and
list[...] of these, nested as needed. Nothing else: no float, dict, tuple, set, None
or objects (except any, a JSON value, for Python and Nix only). Use long for values
beyond 2^31. Outputs must be deterministic: when
several answers would be correct, the statement says which one (sorted, the first...).
At least 5 tests per exercise, covering edge cases (empty, one element, duplicates,
negative numbers, extremes); `in` is the list of arguments.

{FUNCTION_EXAMPLE}
## Code exercises (kind = "code": classes, generators, templates, iterators...)

For what a signature cannot express. Each language gets a starter (the complete file
the student starts from), checks (test code run after the student's code) and a
reference solution (complete file). Every check is one test case:
- Python: check(label, got, expected=True); raises(label, ExceptionType, function, *args).
- C++: CHECK(condition); CHECK_EQ(got, expected); CHECK_THROWS(ExceptionType, statement).
  The checks run inside a function body; [exercises.setup] can hold file-level helpers.
- Java: check(label, condition); check(label, got, expected) (arrays compared deeply);
  checkThrows(label, ExceptionType.class, () -> statement). The checks run inside a
  static method of class Main, in the same package as the student's classes.
- OCaml and Nix: see the languages below.
In the starter, leave the bodies empty (C++ functions without a return do not compile,
which is expected). Write at least 6 checks, including edge cases.

{CODE_EXAMPLE}
{nix_example}# Languages

{notes}

# Other fields and rules

- ids: lowercase and hyphenated, unique within the pack.
- complexity, when given, is one of: {", ".join(CLASSES)}.
- Write every piece of code in TOML literal strings ('''...'''), which need no escaping.
- Statements are short and precise: inputs, output, constraints; no story.
- target is the time in seconds a student fluent in the material needs.
- Explanations (normal, hard, optim) teach the theory behind the solution, not a
  restatement of the code.
"""

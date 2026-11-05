"""`drill help`: how drill chooses what you practise. The README has the same text."""

HELP = """\
HOW DRILL WORKS

Practising
  drill                       the whole base (drill sprint|normal|hard|optim: one mode)
  drill learn [name]          a learn module
  drill run <id…>             the exercises you name, in turn (id#2: one variant)
  drill proba [query]         probability problems, answered in the terminal (3/8, 37.5%,
                              1-(5/6)^4, pi/4), with the worked solution and its trick;
                              levels and variants as for the exercises; a wrong answer
                              counts like the hint
  drill mental [optiver|zetamac]  a timed arithmetic test (80 questions in 8 min with
                              decimals and fractions, or 2 min of integers); the slowest
                              questions get their trick, the score goes to `drill stats`
  Every session serves first what is due for review, the most overdue first, then the
  exercises you have never done (in order in a learn module, at random in the base).
  When nothing is left, the session says so and ends; q ends it before.
  After an exercise, solved or skipped: enter goes on, r runs it again.
  A run is a sandbox: it records nothing, neither level nor record, so replaying an
  exercise cannot raise its score.

Levels and reviews
  Each exercise has a level from 0 to 5 in each language, and comes back for review
  after a delay that grows with its level:
    level      0                1      2      3      4       5
    review     this session     1 d    3 d    7 d    16 d    35 d
  After each attempt:
    within the target time, without the hint     up one level
    over the target (up to 2×), or with the hint  down one level (1 at least)
    skipped, or over twice the target             back to 0: again this session
  So what you know comes back less and less often, and what resists comes back until
  it no longer does. An exercise is "known" from level 3.

Variants (×N in `drill list`)
  The same concept on other data or with another twist, so that you learn the concept
  rather than one answer. They share the exercise's level; each time it comes back,
  drill serves the variant you practised least recently.

Learn modules
  The practical work of a course, apart from the base: its exercises in parts (a
  chapter, a lab, a family of algorithms), each citing the part of your course it
  trains ("cf. AUT - 01 · 5. Subset construction"), which you open yourself if needed.

Adding
  drill prompt "idea"         the request for one exercise of the base
  drill prompt learn          the request for a learn module: paste it, rewrite its
                              Behaviour paragraph if you want, attach your course
  drill prompt variant <id>   the request for more variants of an exercise
  drill add                   checks the AI's reply (from the clipboard) and files it
  drill rm <id|module>        takes it out; its history is kept
  The library is the folder $DRILL_LIBRARY points to: drill/ for the base, learn/ for
  the modules, proba/ for the probability problems, history/ for your attempts. With a
  git remote, drill pulls when it starts, and pushes after a session, an add or a rm
  ($DRILL_SYNC=0 turns this off).

Numbers
  time/target   your solve time over the target: 1.0× is on target, lower is faster
  trend         time/target over the last 14 days compared with the 14 before
"""

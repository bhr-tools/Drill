"""`drill help`: how drill chooses what you practise. The README has the same text."""

HELP = """\
HOW DRILL WORKS

The library
  Every exercise lives in your library, the folder $DRILL_LIBRARY points to:
    drill/   the base: exercises practised for good, one file each
    pack/    packs: exercises aimed at one goal (a course, an exam), from your material
    learn/   learn courses: lessons and exercises to learn a subject step by step
    history/ your attempts, one file per machine
  With a git remote, drill pulls when it starts, and commits and pushes after a
  session, `drill add` or `drill rm` ($DRILL_SYNC=0 turns this off).
  `drill prompt drill|pack|learn|variant` writes the request for an AI;
  `drill add` checks its reply (from the clipboard) and files it; `drill rm` takes it out.

Levels and reviews (the Leitner system)
  Each exercise has a level from 0 to 5 in each language, and comes back for review
  after a delay that grows with its level:
    level      0                1      2      3      4       5
    review     this session     1 d    3 d    7 d    16 d    35 d
  After each attempt:
    within the target time, without the hint     up one level
    over the target (up to 2×), or with the hint  down one level (1 at least)
    skipped, or over twice the target             back to 0: again this session
  So what you know comes back less and less often, and what resists comes back until
  it no longer does. A session serves the exercises due first (about 70% of the time),
  mixed with ones you have never done. An exercise is "known" from level 3.

Variants (×N in `drill list`)
  An exercise can have variants: the same concept on other data or with another twist,
  so that you learn the concept rather than one answer. They share the exercise's level;
  each time it comes back, drill serves the variant you practised least recently.

Sessions
  drill sprint|normal|hard|optim   the base, by size of exercise
  drill pack [name]                a pack, scheduled by levels like the base
  drill learn [name]               a course, in order: the next step unlocks once the
                                   current one is solved; a step with a new concept opens
                                   its lesson (LESSON.md) first; solved steps come back for
                                   review, up to a third of the session
  drill run <query>                the exercises you name

Numbers
  time/target   your solve time over the target: 1.0× is on target, lower is faster
  trend         time/target over the last 14 days compared with the 14 before
"""

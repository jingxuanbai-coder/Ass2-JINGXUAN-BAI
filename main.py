"""BranchLine -- run a story.

Two things you can do with a story file: check it, or play it.

`--check` loads the story, reports what the loader found in it, and then reports
what the *linter* found -- the things the author wrote that no reader will ever
see. It exits non-zero if there are any, because that is the fault this project
is arranged against and a check that cannot fail is not a check. `--play` runs
the engine and lets you walk through it from the keyboard.

**The two halves need different things installed.** Checking a story is the
*writing* tool, and STORY_FORMAT.md opens by promising that you do not need to
install anything to write one. Playing a story is the *reading* tool, and it
draws with Rich. So `rich` is imported inside `play()` and nowhere else: a bare
`import present` at the top of this file would quietly make that promise false
for the one audience it was written for.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Importing the package directly keeps `python main.py` working from the repo
# root without installing anything.
sys.path.insert(0, str(Path(__file__).parent))

from branchline import (  # noqa: E402
    ChoiceLocked,
    Engine,
    EngineError,
    NoSuchOption,
    StoryError,
    load_story,
)

# Imported at the top, unlike `present` and `save`, because it is the one
# dependency that gives nothing away by being here: `lint.py` imports the
# standard library and `model`, needs no terminal, touches no file, and is
# wanted on every single run of the default mode. Importing it inside
# `summarise` would copy the shape of a rule whose reason -- Rich is optional,
# and a save file is a side effect -- does not apply to it.
from branchline.lint import find_unseen  # noqa: E402
from branchline.model import Story  # noqa: E402

DEFAULT_STORY = Path(__file__).parent / "story" / "sample.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="branchline",
        description="Check a BranchLine story, or play it.",
    )
    parser.add_argument(
        "story",
        nargs="?",
        default=str(DEFAULT_STORY),
        help="path to a story file (default: story/sample.json)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="load the story and report what is in it (this is the default)",
    )
    mode.add_argument(
        "--play",
        action="store_true",
        help="play the story from the keyboard",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="a number that makes a run reproducible; printed at the start",
    )
    parser.add_argument(
        "--instant",
        action="store_true",
        help="play without the typewriter effect (for a recording, or a script)",
    )
    args = parser.parse_args(argv)

    try:
        story = load_story(args.story)
    except StoryError as error:
        # The whole point of the loader's error format is that this line is the
        # only thing a non-programmer ever needs to see.
        print(error, file=sys.stderr)
        return 1

    try:
        if args.play:
            return play(story, seed=args.seed, instant=args.instant)
        # A story that loads and plays can still carry rooms nobody can walk
        # into. That is the fault this project is arranged against, so finding
        # one fails the check rather than being mentioned in passing.
        return 1 if summarise(story) else 0
    except EngineError as error:
        # A problem in the story, found while playing it. Still the author's to
        # fix, so it is still a diagnosis rather than a traceback.
        print(f"\n  {error}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\n  Stopped. Leaving does not save -- type save at the prompt to keep a run.\n")
        return 130


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def summarise(story: Story) -> int:
    """Report what is in a story, and how much of it no reader will ever see.

    The return value is a *count of findings*, not a boolean, so that the caller
    decides what to do about them and the exit code lives in one place.
    """
    print()
    print(f"  {story.meta.title}")
    if story.meta.author:
        print(f"  by {story.meta.author}")
    if story.meta.subtitle:
        print(f"  {story.meta.subtitle}")
    print()

    counts = [
        plural(len(story.scenes), "scene"),
        plural(len(story.items), "item"),
        plural(len(story.endings), "ending"),
        plural(len(story.variables), "variable"),
    ]
    print("  " + " · ".join(counts))
    print()

    hud = story.hud_variables()
    if hud:
        print("  status line: " + ", ".join(f"{d.label} ({d.type})" for d in hud))
        print()

    print(f'  scene graph, from "{story.start}":')
    print()

    width = max(len(scene_id) for scene_id in story.scenes)
    for scene_id, scene in story.scenes.items():
        marker = "→" if scene_id == story.start else " "
        print(f"  {marker} {scene_id.ljust(width)}  {scene.title}")

        for choice in scene.choices:
            gate = ""
            if choice.when is not None:
                gate = "  (shown only sometimes)"
            elif choice.enabled_when is not None:
                gate = "  (can be locked)"
            if choice.once:
                gate += "  (once)"
            print(f"      · {choice.text} → {choice.to}{gate}")

        if scene.ending is not None:
            ending = story.endings[scene.ending]
            print(f"      ▸ ends: {ending.title} ({ending.kind})")

    print()
    return _report_unseen(story)


def _report_unseen(story: Story) -> int:
    """Say what the author wrote that no reader will ever see, and count it.

    The healthy case is printed rather than passed over in silence. An empty
    report and a check that never ran look exactly alike on a terminal, and the
    second is the only reason anyone ran the first.
    """
    findings = find_unseen(story)
    if not findings:
        print("  nothing written here is unseen")
        print()
        return 0

    print("  written, and never seen:")
    print()
    labels = [f'{finding.kind} "{finding.name}"' for finding in findings]
    width = max(len(label) for label in labels)
    for label, finding in zip(labels, findings):
        print(f"    {label.ljust(width)}  {finding.problem}")
    print()
    return len(findings)


# ---------------------------------------------------------------------------
# Playing
#
# The whole of the drawing lives in `branchline.present`. What is left here is
# the part about *this program* rather than about terminals: where the story is,
# where its save file goes, what to do when the reader presses something that is
# not offered, and what to say when they leave.
#
# Saving is the piece of this program that touches a file, so it is the piece
# that lives here and not in the presenter or the engine. The presenter knows the
# *words* -- it is the thing that reads them -- and the engine knows nothing at
# all, which is what keeps it playable without a terminal.
# ---------------------------------------------------------------------------


def play(story: Story, seed: int | None = None, instant: bool = False) -> int:
    # Imported here rather than at the top of the file, so that `--check` keeps
    # working for someone who has installed nothing. See the module docstring.
    from rich.console import Console

    from branchline.present import LOAD, LOOK, SAVE, Presenter

    from branchline.save import SaveFile, read_save, reconcile, shown, write_save

    # `highlight=False` because Rich will otherwise colour anything that looks
    # like a number, a path or a quotation -- and the prose in a story file is
    # full of all three, written by an author who chose none of those colours.
    presenter = Presenter(Console(highlight=False), instant=instant)
    engine = Engine.start(story, seed=seed)
    # One slot, derived from the story's own name. Computed once: it cannot
    # change while the program runs, and asking the filesystem every turn whether
    # a save exists yet is both slower and a worse question than asking it when
    # the reader types the word.
    save_path = SaveFile.path_for(story)
    presenter.opening(story.meta, engine.state.seed)

    if engine.opening is not None:
        presenter.turn(engine.opening)

    while not engine.is_over:
        reply = presenter.ask(engine, can_load=save_path.exists())
        if reply is None:
            presenter.stopped()
            return 0

        if reply.command == SAVE:
            try:
                presenter.saved(shown(write_save(save_path, engine.state)))
            except StoryError as error:
                # A folder that cannot be written to is a thing that happens to
                # a reader. It is not a reason to end their run.
                presenter.refused(error)
            continue

        if reply.command == LOAD:
            try:
                resumed = reconcile(read_save(save_path), story)
            except StoryError as error:
                # Either the file is not a save, or the story has moved on from
                # under it. Both are explained and neither touches the run in
                # progress -- see `branchline.save` for why that rule is the
                # whole point rather than a nicety.
                presenter.refused(error)
                continue
            engine = Engine.resume(story, resumed)
            presenter.loaded(engine)
            continue

        if reply.command == LOOK:
            # A question about what is on screen, answered from what is on
            # screen. No state changes and nothing to catch: this never reaches
            # the engine, so it cannot raise `EngineError`.
            presenter.looked(engine, reply.subject)
            continue

        try:
            turn = engine.take(reply.number)
        except (NoSuchOption, ChoiceLocked) as refusal:
            # Not a fault in the story: the reader pressed something that is not
            # on offer. Say why, and put the options back in front of them.
            presenter.note(str(refusal))
            continue
        presenter.turn(turn)

    ending = engine.ending()
    if ending is not None:
        presenter.ending(ending)
    return 0


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


if __name__ == "__main__":
    raise SystemExit(main())

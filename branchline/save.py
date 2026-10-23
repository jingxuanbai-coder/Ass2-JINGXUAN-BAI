"""A run, written down and picked up again.

The story lives in JSON. A save does not, and the reason is the whole design of
this module::

    the save remembers the reader; the story file remembers the story.

The obvious save file is a pickle of the whole ``Engine`` -- which holds the
``Story``, which holds every sentence. That file is self-contained and always
loads, and it is wrong here in exactly the way this project exists to argue
against. The author rewrites a sentence in ``observatory.json``, and the edit
takes effect for every reader *except* the ones who have saved: they keep being
served the old prose, from a file on disk, with nothing in the game to show it.
Prose written that never takes effect is this project's cardinal sin, and a save
file is where it would hide best.

So a save holds what the reader has *done* -- a `GameState`, which is a scene id,
an inventory, some variables, some visit counts, and a seeded generator -- and
nothing else. The story is supplied at load time by `loader.load_story`, from the
file on disk, which is to say from the version the author actually has.

**What that costs, and how it is paid.** An author who edits a story will
eventually rename a scene. A save naming a scene the story no longer declares
cannot be loaded, and the rule for telling the two kinds of mismatch apart is:

    repair what the reader would not notice;
    refuse when the reader's situation would change.

A variable the story stopped declaring is read by nothing, so dropping it is
invisible. A variable the story *started* declaring is one the reader has never
seen, so its declared initial value is not a guess. But the scene the reader is
standing in, and the things they are carrying, are the two facts their run is
*made of* -- quietly substituting a near neighbour there would hand them a save
that is not theirs. So those two are refused, all of them listed at once, and the
refusal is total: nothing is half-applied, because a half-applied save is a game
state that never existed.
"""

from __future__ import annotations

import pickle
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import StoryError
from .model import Story
from .shape import suggest
from .state import GameState

#: Stamped into every save, so that a pickle of something else -- a dict, a
#: `GameState` from someone's experiment -- is refused by name rather than
#: unpacked into a game. Read with `getattr` because a save may predate it.
FORMAT = "branchline.save"

#: The version of the *envelope*, not of the state inside it. A change to a
#: `GameState` field is absorbed by `GameState.__setstate__` and needs nothing
#: here; this number is for a change to the arrangement of the file itself.
VERSION = 1

#: Where saves are written: beside the program, in the directory `.gitignore`
#: has been reserving for them since before anything wrote one. Not beside the
#: story, because `story/` is the author's source and a save is the reader's
#: bookkeeping -- and not in the current working directory, which for a story
#: opened by double-click is anywhere at all.
SAVE_DIR = Path(__file__).parent.parent / "saves"

#: The suffix. Deliberately not `.json` and not `.pkl`: it is a file a reader may
#: need to find and delete by hand, so it should be recognisable at a glance.
SUFFIX = ".save"


@dataclass
class SaveFile:
    """The contents of a save file: the run, and what the file claims to be.

    Deliberately neither ``frozen`` nor ``slots``, for the reasons given on
    ``GameState`` -- this is the other object that outlives the code that wrote
    it. ``format`` and ``version`` have literal defaults, so a save written
    before either existed recovers on its own by reading the class attribute;
    that is the same accident ``GameState.seed`` relies on, and it is why this
    is a plain dataclass rather than a slotted one.
    """

    state: GameState
    format: str = FORMAT
    version: int = VERSION

    @staticmethod
    def path_for(story: Story, directory: Path | str = SAVE_DIR) -> Path:
        """Where this story's save goes: one slot, named after the story.

        One slot, not a list of them, because choosing a slot is a menu and this
        project has deliberately no menus. The story's own name is the slot, so
        the demo and the sample cannot overwrite each other while the reader
        still never has to decide anything.
        """
        stem = story.source.stem if story.source is not None else "branchline"
        return Path(directory) / (stem + SUFFIX)


def shown(path: Path | str) -> Path:
    """The shortest path that still finds the file, for saying out loud.

    Someone playing from the repo root should be told `saves/observatory.save`,
    which they can type, rather than the same file with their own home directory
    recited back at them. A path that is not under the working directory is left
    alone, because there the absolute one *is* the short one.
    """
    target = Path(path)
    try:
        return target.relative_to(Path.cwd())
    except ValueError:
        return target


def write_save(path: Path | str, state: GameState) -> Path:
    """Write a run to `path`, making the directory it lives in. Returns the path.

    A save that cannot be written is a diagnosis and not a traceback, the same as
    a story that cannot be read -- a full disk or a read-only folder is a thing
    that happens to a reader, not a fault in the program.
    """
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            pickle.dump(SaveFile(state=state), handle, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError as error:
        raise StoryError(
            "this save could not be written",
            path=shown(target),
            hint=f"{error.strerror or error}",
        ) from error
    return target


def read_save(path: Path | str) -> SaveFile:
    """Read a save file back. Raises `StoryError` if it is not one.

    Everything that can go wrong here is a thing a *reader* does -- deleting the
    file, pointing at the wrong one, interrupting a copy half-way -- so every
    failure has to arrive as a sentence rather than as whatever `pickle` felt
    like raising.
    """
    target = Path(path)
    if not target.exists():
        raise StoryError(
            "there is nothing saved for this story yet",
            path=shown(target),
            hint='type "save" at the prompt to write one',
        )

    try:
        with target.open("rb") as handle:
            loaded = pickle.load(handle)
    except Exception as error:
        # `Exception` and not a list of pickle's own errors, on purpose. The one
        # statement in this block is a read of bytes whose shape we do not
        # control, and the set of things those bytes can raise is not knowable in
        # advance -- a truncated copy, a JSON story file, a directory, an image.
        # Catching narrowly here would mean discovering the next case from a
        # traceback in front of a reader. `KeyboardInterrupt` and `SystemExit` do
        # not derive from `Exception`, so the escape hatches still work.
        raise StoryError(
            "this file is not a save",
            path=shown(target),
            hint='a save is a file this program writes when you type "save" while playing',
        ) from error

    if not isinstance(loaded, SaveFile) or getattr(loaded, "format", None) != FORMAT:
        raise StoryError(
            "this file is not a save",
            path=shown(target),
            hint=f"it is a {type(loaded).__name__}, and a save is a {FORMAT} file",
        )
    if loaded.version > VERSION:
        raise StoryError(
            "this save was written by a newer BranchLine than this one",
            path=shown(target),
            hint=f"it is version {loaded.version}; this program writes {VERSION}",
        )
    if getattr(loaded, "state", None) is None:
        raise StoryError(
            "this save has no run in it",
            path=shown(target),
            hint="the file is probably truncated",
        )
    return loaded


def reconcile(save: SaveFile, story: Story) -> GameState:
    """Fit a saved run to the story as it is now, or explain why it cannot be.

    Returns a **new** `GameState`; the one inside `save` is not touched, so a
    refused load cannot have already changed anything. The rules are the table in
    this module's docstring: variables and visit counts are repaired, the scene
    and the inventory are refused.
    """
    state = save.state
    problems: list[str] = []

    if state.scene_id not in story.scenes:
        problems.append(
            f'you are standing in "{state.scene_id}", which is not a scene in this '
            f"story{suggest(state.scene_id, story.scenes)}"
        )
    for item_id in state.carried_ids():
        if item_id not in story.items:
            problems.append(
                f'you are carrying "{item_id}", which is not an item this story '
                f"declares{suggest(item_id, story.items)}"
            )

    if problems:
        # Every problem at once, not the first. An author who fixed one and
        # reloaded to be told about the next would be reading the file by hand to
        # find out what is wrong with it, which is the loop this project refuses.
        listed = "\n".join(f"  · {problem}" for problem in problems)
        raise StoryError(
            f"this save is from an earlier version of the story:\n{listed}",
            path=shown(SaveFile.path_for(story)),
        )

    # The generator is copied rather than shared. Handing the loaded run the very
    # `Random` out of the save file would leave the file's contents advancing
    # underneath whoever still holds it -- invisible, and exactly the kind of
    # aliasing that is discovered a year later.
    rng = random.Random()
    rng.setstate(state.rng.getstate())

    # One comprehension does both variable repairs, which is the reason it is
    # written this way rather than in two passes: a name the story declares gets
    # the saved value if there is one and its declared initial if there is not,
    # and a name the story has stopped declaring is simply never asked for.
    variables: dict[str, Any] = {
        name: state.variables.get(name, declared.initial)
        for name, declared in story.variables.items()
    }

    return GameState(
        scene_id=state.scene_id,
        variables=variables,
        inventory=dict(state.inventory),
        visits={s: n for s, n in state.visits.items() if s in story.scenes},
        used_choices={(s, c) for s, c in state.used_choices if s in story.scenes},
        seed=state.seed,
        rng=rng,
    )

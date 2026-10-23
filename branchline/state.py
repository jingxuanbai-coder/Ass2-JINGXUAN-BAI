"""The mutable half of a run.

`model.py` holds the *story*: immutable, shared, the same object for every reader.
This holds the *run*: what has happened to this reader, so far.

Keeping them apart is what makes the rest of the project work. The story never
changes, so nothing the engine does can corrupt it; everything that varies lives
here, so a save file is a single object and a replay is a single seed. Two readers
who take the same route see the same words, and two who do not, do not.
"""

from __future__ import annotations

import random
from dataclasses import MISSING, dataclass, field, fields
from typing import Any

from .model import Story


@dataclass
class GameState:
    """Everything the engine needs to answer "what are you offered now?".

    Deliberately neither ``frozen`` nor ``slots``.

    *Not frozen* because loading a save has to put the reader back in a different
    scene.

    *Not slotted* because this is the one object in the project that outlives the
    code that wrote it. A ``__dict__`` is what lets W10 open an old save, see
    field by field what it does and does not contain, and repair it generically
    -- which is what ``__setstate__`` below does for a field the save predates.

    (Two tempting reasons for this decision are false, and it is worth saying so
    rather than letting someone rediscover them: pickle works fine with
    ``slots=True``, on 3.12 and 3.14 alike -- and a plain class does *not* fill in
    a missing ``default_factory`` field by itself either. Only a field with a
    literal default such as ``seed`` recovers on its own. Both of those were
    measured, not assumed, and the second one is why ``__setstate__`` exists:
    without it the guarantee would not actually hold.)
    """

    scene_id: str
    variables: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, None] = field(default_factory=dict)
    visits: dict[str, int] = field(default_factory=dict)
    used_choices: set[tuple[str, str]] = field(default_factory=set)
    seed: int = 0
    # `compare=False`: random.Random defines no __eq__, so it would compare by
    # identity and make every state unequal to its own unpickled twin. Comparing
    # two states is something the save tests need to do.
    rng: random.Random = field(compare=False, repr=False, default_factory=random.Random)

    @classmethod
    def new(cls, story: Story, seed: int | None = None) -> GameState:
        """A fresh run of `story`, with every declared variable at its initial value.

        The seed is resolved here rather than left as None, so that the state
        always carries the number that produced it -- a reader who hits something
        strange can be asked for it, and the run can be reproduced exactly.
        """
        resolved = seed if seed is not None else random.randrange(2**32)
        return cls(
            scene_id=story.start,
            variables={name: decl.initial for name, decl in story.variables.items()},
            seed=resolved,
            rng=random.Random(resolved),
        )

    def __setstate__(self, saved: dict[str, Any]) -> None:
        """Load a save, filling in any field that save is too old to have.

        A save file is the one thing here that can be older than the code reading
        it: a reader who left a run half-finished last week should not meet an
        ``AttributeError`` because a field was added since. Restoring what was
        saved and then defaulting the rest turns "this save is from an older
        version" from a crash into an ordinary, inspectable condition.

        Written now rather than in W10 because it is a handful of lines, and
        because the alternative is finding out mid-play, in front of a reader.
        """
        self.__dict__.update(saved)
        for declared in fields(self):
            if declared.name in self.__dict__:
                continue
            if declared.default is not MISSING:
                setattr(self, declared.name, declared.default)
            elif declared.default_factory is not MISSING:
                setattr(self, declared.name, declared.default_factory())

        # `rng` is the one field a generic default gets wrong. An unseeded
        # generator would leave the run no longer matching the seed it still
        # reports -- and that seed is the only thing that makes a strange run
        # reportable. Rebuild it from the saved seed instead.
        if "rng" not in saved:
            self.rng = random.Random(self.seed)

    # -- the inventory ------------------------------------------------------
    #
    # A dict used as an ordered set, not a `set`. This is the one collection whose
    # order the reader eventually sees (W9 prints the backpack), and a set would
    # print in hash order. Assigning to an existing key keeps its original
    # position, so taking something twice is naturally both idempotent and
    # non-reordering -- no special case needed.

    def has(self, item_id: str) -> bool:
        return item_id in self.inventory

    def take(self, item_id: str) -> None:
        self.inventory[item_id] = None

    def drop(self, item_id: str) -> None:
        self.inventory.pop(item_id, None)

    def carried_ids(self) -> tuple[str, ...]:
        return tuple(self.inventory)

    # -- visits -------------------------------------------------------------

    def visit(self, scene_id: str) -> int:
        """Count an entry and return the new total. Called by the engine, never by a condition."""
        count = self.visits.get(scene_id, 0) + 1
        self.visits[scene_id] = count
        return count

    def visit_count(self, scene_id: str) -> int:
        """An unvisited scene has been visited zero times, not an error."""
        return self.visits.get(scene_id, 0)

    # -- choices already taken ----------------------------------------------
    #
    # Keyed by (scene, choice) rather than by choice id alone, because the loader
    # only guarantees a choice id is unique *within* its scene -- two authors'
    # "look_again" in two different rooms are both legal, and must not collide.

    def mark_used(self, scene_id: str, choice_id: str) -> None:
        self.used_choices.add((scene_id, choice_id))

    def used(self, scene_id: str, choice_id: str) -> bool:
        return (scene_id, choice_id) in self.used_choices

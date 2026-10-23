"""The linter: everything an author wrote that no reader will ever see.

The loader refuses a story that is *broken* -- a scene that does not exist, a
choice with no destination, actions written after a jump that ends the list. This
module reports a different fault, and it is the one the whole project is arranged
against:

    **something written that never takes effect.**

An orphaned scene is prose nobody can read. An ending nothing reaches is an
epilogue nobody reads. An item nothing takes carries a description nobody can
look at. A variable nothing reads is computed, held and thrown away in full view
of the source and in view of nothing else. In every case the author did the work
and the reader never receives it, and -- this is the part that makes it worth a
module -- **it is invisible in play.** You cannot find these by playing the story.
You find them by holding the whole story in your head at once, which is exactly
what a person cannot do and a program can.

**Why a finding fails the check.** The loader already treats this fault as fatal
in the one place it can see it: `effects.py` refuses an action written after an
unconditional ``goto``, because it can never run. An orphaned scene is the same
fault -- prose that can never run -- and the loader is simply not looking for it,
because reachability is a property of the whole graph rather than of one file
location. So ``--check`` exits non-zero when there is anything here. A check that
prints a warning and passes is a promise the project has twice refused to make.

**What a finding is not.** It is *not* a `StoryError`. That type means the
author's file is wrong and carries the exact place in it; it stops a load. A
finding must not stop anything -- the story still loads and still plays, and every
room in it still works. The two are genuinely different things and a single type
would make "your story is broken" and "your story has an orphan" impossible to
tell apart. (`save.py` makes the opposite choice for the opposite reason: there,
one type and one rendering path is exactly right.)

**What this deliberately does not do.** It does not try to decide whether a
condition can ever be true. ``{"all": [{"has_item": "key"}, {"not": {"has_item":
"key"}}]}`` is unsatisfiable and this module will not say so, because that is a
solver's job and the loader already declines to attempt a half-version of it.
Reachability here is structural, which is the question "could anyone get here"
rather than "will they" -- the same question `Story.reached_scenes` answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .model import (
    Action,
    AllOf,
    AnyOf,
    Chance,
    Condition,
    Conditional,
    FlagSet,
    Negate,
    Story,
    TakeItems,
    VarAtLeast,
    VarIs,
)

#: Why each kind of finding matters, in one sentence each.
#:
#: Looked up from `Finding.kind` rather than stored on the finding. A `Finding`
#: that carried its own explanation could disagree with the rule that produced
#: it, and a report against which the code and the prose have drifted apart is
#: the fault this module exists to find -- it would be a poor joke to introduce
#: one in the reporting of it.
PROBLEMS: dict[str, str] = {
    "scene": "nothing links to it, so its prose is never read",
    "ending": "no scene ends here, so its epilogue is never read",
    "item": "nothing in the story takes it, so it can never be looked at",
    "variable": "nothing reads it and it is not on the status line",
}

#: The order findings are reported in, and the reason it is fixed.
#:
#: Declaration order, scene first, because that is the order the story is
#: arranged in and therefore the order the author is thinking in. A report that
#: reordered itself between runs would be one more thing to re-read rather than
#: recognise.
KINDS = ("scene", "ending", "item", "variable")


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing written that no reader will ever perceive.

    Nothing but the kind and the name, because between them they locate the
    declaration exactly: the author writes ``scenes.cellar``, and this says
    ``"scene" "cellar"``. Carrying a rendered location as well would be a second
    spelling of the same fact, free to drift from the first.
    """

    kind: str
    name: str

    @property
    def problem(self) -> str:
        """Why this matters, as a sentence. See `PROBLEMS`."""
        return PROBLEMS[self.kind]


def find_unseen(story: Story) -> tuple[Finding, ...]:
    """Everything the story declares that no reader will ever see.

    Empty is the healthy answer, and it is worth saying so out loud rather than
    by printing nothing -- an empty report and a check that did not run look
    identical on a terminal.
    """
    findings: list[Finding] = []

    # -- a scene nothing links to -------------------------------------------
    unreached = story.unreached_scenes()
    findings.extend(
        Finding("scene", scene_id)
        for scene_id in story.scenes
        if scene_id in unreached
    )

    # -- an ending no scene ends at -----------------------------------------
    used = {scene.ending for scene in story.scenes.values() if scene.ending is not None}
    findings.extend(
        Finding("ending", ending_id)
        for ending_id in story.endings
        if ending_id not in used
    )

    # -- an item nothing ever takes -----------------------------------------
    #
    # This rule only means anything because the reader can `look` at what they
    # are carrying. Before that command existed, an item's description was
    # unreadable whether or not anything took it, and reporting this would have
    # been singling out one arbitrary way of never being seen.
    taken = _taken_items(story)
    findings.extend(
        Finding("item", item_id)
        for item_id in story.items
        if item_id not in taken
    )

    # -- a variable nothing reads -------------------------------------------
    #
    # A variable on the status line is exempt: the reader watches it change, so
    # it takes effect however little reads it. A variable that is *written* by
    # something and read by nothing is the finding -- the story does arithmetic
    # the reader never receives.
    read = _read_variables(story)
    findings.extend(
        Finding("variable", name)
        for name, decl in story.variables.items()
        if name not in read and not decl.hud
    )

    return tuple(findings)


# ---------------------------------------------------------------------------
# Walking the story
#
# Deliberately recursive rather than clever. An action or a condition can sit
# inside another one -- a `conditional` guards a list, a `chance` has two of
# them, `all`/`any`/`not` nest without limit -- and a reference buried three
# levels down is read just as surely as one at the top. A walk that stopped at
# the surface would report a live variable dead, which is the one failure mode
# that would make this module worse than not having it.
# ---------------------------------------------------------------------------


def _walk_actions(actions: tuple[Action, ...]) -> Iterator[Action]:
    """Every action in a list, including the ones inside a guard or a coin."""
    for action in actions:
        yield action
        if isinstance(action, Conditional):
            yield from _walk_actions(action.actions)
        elif isinstance(action, Chance):
            yield from _walk_actions(action.then)
            yield from _walk_actions(action.otherwise)


def _walk_conditions(condition: Condition) -> Iterator[Condition]:
    """Every condition in a tree, including the ones inside `all`/`any`/`not`."""
    yield condition
    if isinstance(condition, (AllOf, AnyOf)):
        for child in condition.children:
            yield from _walk_conditions(child)
    elif isinstance(condition, Negate):
        yield from _walk_conditions(condition.child)


def _actions_of(story: Story) -> Iterator[Action]:
    """Every action written anywhere in the story."""
    for scene in story.scenes.values():
        yield from _walk_actions(scene.on_enter)
        for choice in scene.choices:
            yield from _walk_actions(choice.effects)


def _conditions_of(story: Story) -> Iterator[Condition]:
    """Every condition written anywhere in the story."""
    for scene in story.scenes.values():
        for variant in scene.variants:
            yield from _walk_conditions(variant.when)
        for choice in scene.choices:
            for condition in (choice.when, choice.enabled_when):
                if condition is not None:
                    yield from _walk_conditions(condition)
    for action in _actions_of(story):
        if isinstance(action, Conditional):
            yield from _walk_conditions(action.condition)


def _taken_items(story: Story) -> set[str]:
    """Every item the story ever hands the reader.

    Read from the whole story rather than only from its reachable part. An item
    taken solely inside an orphaned scene is never taken in play, and reporting
    it alongside the orphan is right -- two declarations, two findings, and the
    author has two things to think about rather than one.
    """
    taken: set[str] = set()
    for action in _actions_of(story):
        if isinstance(action, TakeItems):
            taken.update(action.item_ids)
    return taken


def _read_variables(story: Story) -> set[str]:
    """Every variable some condition asks about.

    Only `flag`, `var ... is` and `var ... at_least` read a variable. Being
    *written* does not count: `inc` reads a number in order to add to it, but
    nothing downstream of that addition ever looks at the result, and the reader
    certainly does not.
    """
    read: set[str] = set()
    for condition in _conditions_of(story):
        if isinstance(condition, (FlagSet, VarIs, VarAtLeast)):
            read.add(condition.name)
    return read

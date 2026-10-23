"""The shape of a story, as immutable Python objects.

Everything here is data with no behaviour. The story itself lives in JSON; these
dataclasses are only a typed *view* of it, so the rest of the engine gets
attribute access and a clear error on a typo instead of stringly-typed lookups.

Nothing in this module knows anything about any particular story. That is the
point: the engine can combine and evaluate condition nodes without ever knowing
what a given condition *means*.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# The vocabularies an author may draw on.
#
# These live here rather than in the presentation layer because they are *schema*:
# the loader rejects a word that is not in them, so they are part of what an
# author is allowed to write. How each one looks is a separate question, answered
# in `palette.py` when the Rich layer lands.
# ---------------------------------------------------------------------------

VARIABLE_TYPES = frozenset({"int", "bool", "string"})

#: Registers the author can name for a paragraph. The author writes "aside",
#: never a markup tag, so the palette stays in one place.
PARAGRAPH_STYLES = frozenset({"aside", "letter", "sign", "whisper"})

#: How quickly a paragraph or scene is revealed.
PACES = frozenset({"slow", "normal", "fast"})

#: The mood of an ending, which the palette turns into a colour.
ENDING_KINDS = frozenset({"warm", "bitter", "ambiguous", "neutral"})

# ---------------------------------------------------------------------------
# Conditions -- a declarative tree the story author writes in JSON.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Condition:
    """Base class for every node in a condition tree."""


@dataclass(frozen=True, slots=True)
class AllOf(Condition):
    children: tuple[Condition, ...]


@dataclass(frozen=True, slots=True)
class AnyOf(Condition):
    children: tuple[Condition, ...]


@dataclass(frozen=True, slots=True)
class Negate(Condition):
    child: Condition


@dataclass(frozen=True, slots=True)
class HasItem(Condition):
    """True when the inventory holds every listed item."""

    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlagSet(Condition):
    """True when a boolean variable is true."""

    name: str


@dataclass(frozen=True, slots=True)
class VarIs(Condition):
    name: str
    value: Any


@dataclass(frozen=True, slots=True)
class VarAtLeast(Condition):
    name: str
    threshold: int


@dataclass(frozen=True, slots=True)
class Visited(Condition):
    """True once the reader has entered this scene at all."""

    scene_id: str


@dataclass(frozen=True, slots=True)
class VisitCount(Condition):
    scene_id: str
    threshold: int


@dataclass(frozen=True, slots=True)
class FirstTime(Condition):
    """True only during the first entry to the scene currently being entered.

    The engine increments the visit counter *before* evaluating ``on_enter``,
    which is what makes this readable as "first time". Documented in
    STORY_FORMAT.md because it is otherwise rediscovered as a bug.
    """


# ---------------------------------------------------------------------------
# Actions -- the state changes a story may ask for.
#
# Randomness appears here and only here (see `Chance`). It is deliberately not
# expressible as a condition: a condition is evaluated more than once per turn
# (filtering choices, re-rendering), so a random one would give different
# answers on the second evaluation -- an invisible, unfixable bug.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Action:
    """Base class for every kind of state change a story can ask for."""


@dataclass(frozen=True, slots=True)
class SetVars(Action):
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class IncrementVars(Action):
    deltas: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class TakeItems(Action):
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DropItems(Action):
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Goto(Action):
    """A forced transition. Used by connective scenes that exist only to fall through."""

    scene_id: str


@dataclass(frozen=True, slots=True)
class Message(Action):
    """Prose the world offers in response, shown after the body and before the choices.

    The same `Paragraph` a scene's ``body`` is made of, register and pace
    included, so that "the room is speaking" and "the world is answering" are not
    two different languages. It was a tuple of bare strings until the presenter
    landed, which meant the world could never say anything as an aside.
    """

    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True, slots=True)
class Conditional(Action):
    """Guarded actions. One wrapper covers both on-enter and per-choice cases."""

    condition: Condition
    actions: tuple[Action, ...]


@dataclass(frozen=True, slots=True)
class Chance(Action):
    """A coin flip producing state change. The only source of randomness in the system."""

    probability: float
    then: tuple[Action, ...]
    otherwise: tuple[Action, ...]


# ---------------------------------------------------------------------------
# Presentation fragments
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paragraph:
    """One unit of prose.

    `style` is a *register* named by the author ("aside", "letter", "sign",
    "whisper") rather than a markup string, so the palette stays in one place and
    prose never has to be parsed as markup. `pace` scales the reveal speed.
    """

    text: str
    style: str | None = None
    pace: str | None = None


# ---------------------------------------------------------------------------
# The story's pieces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str
    description: str
    art: str | None = None


@dataclass(frozen=True, slots=True)
class Ending:
    id: str
    title: str
    epilogue: tuple[Paragraph, ...]
    kind: str = "neutral"  # the palette maps this to a colour


@dataclass(frozen=True, slots=True)
class VarDecl:
    """A declared variable.

    Declaring it is what lets the loader reject a `set`/`inc` aimed at a name the
    story never declared, and keeps the initial value in the data rather than
    hardcoded in the engine.
    """

    name: str
    type: str  # "int" | "bool" | "string"
    initial: Any
    label: str | None = None
    hud: bool = False


@dataclass(frozen=True, slots=True)
class Choice:
    """One option offered to the reader.

    `when` and `enabled_when` are deliberately different questions:

    * ``when``         -- does this option *exist* for you? Failing hides it entirely.
    * ``enabled_when`` -- can you *do* it? Failing still shows it, dimmed, with
      ``locked_hint`` beneath. Whether a locked door is visible is an authorial
      decision, so it is expressed in the author's data rather than decided in
      Python.
    """

    text: str
    to: str
    id: str | None = None
    once: bool = False
    when: Condition | None = None
    enabled_when: Condition | None = None
    locked_hint: str | None = None
    effects: tuple[Action, ...] = ()


@dataclass(frozen=True, slots=True)
class Variant:
    """A presentation-only override of a scene. First match wins; never touches logic."""

    when: Condition
    title: str | None = None
    body: tuple[Paragraph, ...] | None = None
    pace: str | None = None


@dataclass(frozen=True, slots=True)
class Scene:
    id: str
    title: str
    body: tuple[Paragraph, ...]
    choices: tuple[Choice, ...]
    variants: tuple[Variant, ...] = ()
    on_enter: tuple[Action, ...] = ()
    ending: str | None = None
    pace: str | None = None


@dataclass(frozen=True, slots=True)
class Meta:
    title: str
    author: str | None = None
    subtitle: str | None = None
    title_card: tuple[Paragraph, ...] = ()


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The ids a story has declared.

    Parsing uses this to reject references to things that do not exist. It is the
    closed vocabulary that a string mini-language could never offer -- a typo'd
    item id is caught at load time rather than silently doing nothing.
    """

    scenes: frozenset[str]
    items: frozenset[str]
    variables: Mapping[str, VarDecl]

    def variable(self, name: str) -> VarDecl | None:
        return self.variables.get(name)

    def declared_names(self, kind: str) -> str:
        """A sorted, comma-separated list for use in error hints."""
        if kind == "scene":
            names = sorted(self.scenes)
        elif kind == "item":
            names = sorted(self.items)
        else:
            names = sorted(self.variables)
        return ", ".join(names) if names else "(none declared)"


# ---------------------------------------------------------------------------
# The story
# ---------------------------------------------------------------------------


def _jump_targets(action: Action) -> list[str]:
    """Scenes this action can send the reader to, including nested ones."""
    if isinstance(action, Goto):
        return [action.scene_id]
    if isinstance(action, Conditional):
        return [t for nested in action.actions for t in _jump_targets(nested)]
    if isinstance(action, Chance):
        return [
            t
            for nested in (*action.then, *action.otherwise)
            for t in _jump_targets(nested)
        ]
    return []


@dataclass(frozen=True, slots=True)
class Story:
    start: str
    scenes: Mapping[str, Scene]
    variables: Mapping[str, VarDecl]
    items: Mapping[str, Item]
    endings: Mapping[str, Ending]
    meta: Meta
    format_version: int = 1
    source: Path | None = None

    def scene(self, scene_id: str) -> Scene:
        return self.scenes[scene_id]

    def vocabulary(self) -> Vocabulary:
        return Vocabulary(
            scenes=frozenset(self.scenes),
            items=frozenset(self.items),
            variables=self.variables,
        )

    def hud_variables(self) -> tuple[VarDecl, ...]:
        """Variables the author nominated for the status line, in declaration order.

        Dicts preserve insertion order, so the author controls the order by the
        order they wrote the JSON. Deliberately capped by the validator -- more
        than a couple of facts turns a piece of art into a dashboard.
        """
        return tuple(decl for decl in self.variables.values() if decl.hud)

    def reached_scenes(self) -> set[str]:
        """Every scene a reader could arrive at, following choices and jumps.

        Conditions are deliberately not evaluated: this answers "could anyone get
        here", which is the question a dead-link check asks, not "will they". A
        scene nothing links to is usually one the author wrote and then orphaned
        while rearranging -- and it is completely invisible in play, which is
        exactly why it is worth being able to ask.

        **Both of a choice's destinations are followed.** A choice has an
        ordinary `to`, and it may also carry a `goto` inside its `effects` -- and
        `Engine.take` takes that one when it is there, because it is the more
        specific instruction. Following only `to` would make a scene reachable
        *solely* by such a detour look orphaned, and a report that names a room
        the reader can walk straight into is worse than no report at all.
        """
        seen = {self.start}
        frontier = [self.start]
        while frontier:
            current = self.scenes.get(frontier.pop())
            if current is None:
                continue
            targets: list[str] = []
            for choice in current.choices:
                targets.append(choice.to)
                for action in choice.effects:
                    targets.extend(_jump_targets(action))
            for action in current.on_enter:
                targets.extend(_jump_targets(action))
            for target in targets:
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)
        return seen

    def unreached_scenes(self) -> set[str]:
        """Scenes written but never linked to. Empty is the healthy answer."""
        return set(self.scenes) - self.reached_scenes()

"""The engine: what a reader is offered now, and what happens when they choose.

This module is the whole of the game. It takes a story, which never changes, and
a state, which is everything that has happened so far, and answers two questions:
*where are you, and what can you do?* and *now that you have chosen, what then?*

**It knows nothing about terminals.** There is no `rich` here and no `input()`.
The engine is a state machine driven from outside: something renders
`view()`/`options()`, waits for a keypress, and calls `take()`. That line is what
lets the presentation be replaced wholesale without touching the game, and it is
asserted mechanically in the tests rather than merely intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .conditions import evaluate
from .effects import apply_actions
from .model import Choice, Ending, Item, Paragraph, Scene, Story, VarDecl
from .state import GameState

#: How many forced jumps one turn may chain through before the engine gives up.
#: Two connective scenes pointing at each other would otherwise spin forever,
#: and an infinite loop is a mistake in the story rather than in the reader.
MAX_JUMPS_PER_TURN = 32


class EngineError(Exception):
    """Something the reader did, or something the story does, that cannot proceed.

    Deliberately *not* a `StoryError`. That type means "the author's file is
    wrong, and here is the file and the exact place in it" -- a diagnosis aimed
    at whoever wrote the story. A reader pressing 9 is not a fault in the story
    and should not be shown a JSON pointer.
    """


class NoSuchOption(EngineError):
    """There is no option with that number."""


class ChoiceLocked(EngineError):
    """The option exists and is visible, but its `enabled_when` is not satisfied."""


# ---------------------------------------------------------------------------
# What the outside world is handed
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SceneView:
    """The scene as it should be shown, with any variant already applied.

    `scene`, `title`, `body` and `pace` are merged into one object on purpose. A
    `Variant` may override any of the last three, so handing them out separately
    -- a `scene()` here, a `body()` there -- means a caller that reads
    `view.scene.pace` gets the un-overridden value and never finds out.
    """

    scene: Scene
    title: str
    body: tuple[Paragraph, ...]
    pace: str | None


@dataclass(frozen=True, slots=True)
class Option:
    """One pressable choice, as offered."""

    number: int  # 1-based, counting only the options that are visible
    text: str
    locked: bool
    locked_hint: str
    choice: Choice


@dataclass(frozen=True, slots=True)
class Turn:
    """Everything that should be shown after a choice is taken.

    A turn produces prose -- the choice's own `effects` messages, then the whole
    `on_enter` chain of wherever it led. It is returned rather than queued on the
    engine because a turn is one thing that gets drawn: a queue the caller drains
    later is a second channel, free to drift out of step with what is on screen.
    """

    messages: tuple[Paragraph, ...]
    entered: SceneView


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class Engine:
    def __init__(self, story: Story, state: GameState) -> None:
        self.story = story
        self.state = state
        self.opening: Turn | None = None

    @classmethod
    def start(cls, story: Story, seed: int | None = None) -> Engine:
        """Begin a new run, entering the start scene.

        Entering happens here rather than in `__init__` so that `resume` can
        exist. An engine that walked into the start scene on construction could
        not be rebuilt from a save: constructing it would count the visit again,
        re-roll any chance on entry, and show the opening prose a second time.
        """
        engine = cls(story, GameState.new(story, seed))
        engine.opening = engine._enter(story.start)
        return engine

    @classmethod
    def resume(cls, story: Story, state: GameState) -> Engine:
        """Continue from a saved state, entering nothing.

        There is no `opening` here, because nothing was opened -- the reader is
        already mid-story, and the scene they were in is the one they are in.
        """
        return cls(story, state)

    # -- what is on screen now ----------------------------------------------

    @property
    def current(self) -> Scene:
        return self.story.scenes[self.state.scene_id]

    def view(self) -> SceneView:
        """The current scene, with the first matching variant applied."""
        scene = self.current
        title, body, pace = scene.title, scene.body, scene.pace

        for variant in scene.variants:
            if not evaluate(variant.when, self.state):
                continue
            # `is not None` rather than truthiness, because for a `pace` the two
            # are not the same question -- this is the one place in the project
            # where writing `null` and leaving the key out would differ, and
            # neither is distinguishable from the other once it is parsed.
            if variant.title is not None:
                title = variant.title
            if variant.body is not None:
                body = variant.body
            if variant.pace is not None:
                pace = variant.pace
            break  # first match wins; a variant is not a patch to be layered

        return SceneView(scene=scene, title=title, body=body, pace=pace)

    def options(self) -> tuple[Option, ...]:
        """The choices currently on offer, numbered from one.

        Numbering happens *after* filtering, so the numbers are always 1..N with
        no gaps. A gap would mean a key that does nothing when pressed, which in
        a terminal is indistinguishable from a broken program.

        Locked options keep their number: they are visible and pressable, they
        just refuse. And because the loader requires every scene to have either
        choices, an ending, or a forced jump, an empty result here means exactly
        one thing -- the story has ended.
        """
        scene = self.current
        offered: list[Option] = []
        for choice in scene.choices:
            if choice.when is not None and not evaluate(choice.when, self.state):
                continue
            if choice.once and self.state.used(scene.id, choice.id or ""):
                continue
            locked = choice.enabled_when is not None and not evaluate(
                choice.enabled_when, self.state
            )
            offered.append(
                Option(
                    number=len(offered) + 1,
                    text=choice.text,
                    locked=locked,
                    # The loader requires a `locked_hint` beside every
                    # `enabled_when`, so this is only empty for a story that has
                    # not been through the loader -- a hand-built one, in a test.
                    locked_hint=choice.locked_hint or "",
                    choice=choice,
                )
            )
        return tuple(offered)

    def hud(self) -> tuple[tuple[VarDecl, Any], ...]:
        """The status-line variables and their current values, in declared order.

        Values are handed over raw; turning `True` into "yes" is a presentation
        decision and belongs to whoever is drawing the screen.
        """
        return tuple(
            (decl, self.state.variables[decl.name])
            for decl in self.story.hud_variables()
        )

    def carried(self) -> tuple[Item, ...]:
        """What is in the reader's pockets, in the order they were picked up."""
        return tuple(self.story.items[item_id] for item_id in self.state.carried_ids())

    # -- endings ------------------------------------------------------------

    @property
    def is_over(self) -> bool:
        return self.current.ending is not None

    def ending(self) -> Ending | None:
        """The ending the reader has arrived at, or None if the story goes on."""
        scene = self.current
        if scene.ending is None:
            return None
        return self.story.endings[scene.ending]

    # -- the one thing the reader can do ------------------------------------

    def take(self, number: int) -> Turn:
        """Take the option with this number, and report what the reader now sees."""
        chosen = next((o for o in self.options() if o.number == number), None)
        if chosen is None:
            raise NoSuchOption(self._no_such_option(number))
        if chosen.locked:
            raise ChoiceLocked(chosen.locked_hint)

        choice = chosen.choice
        # Recorded against the scene being *left*, and before anything moves.
        # Updating `scene_id` first is the natural mistake, and it would key the
        # memory to the destination instead -- nothing would ever match it again,
        # and "once" would quietly stop meaning once.
        if choice.id is not None:
            self.state.mark_used(self.state.scene_id, choice.id)

        effects = apply_actions(choice.effects, self.state)
        # A `goto` inside the effects is the more specific instruction, so it
        # wins; `to` is the ordinary destination. This is what lets a choice
        # detour conditionally without needing a scene of its own to do it in.
        destination = effects.goto if effects.goto is not None else choice.to

        arrived = self._enter(destination)
        return Turn(
            messages=effects.messages + arrived.messages,
            entered=arrived.entered,
        )

    # -- the transition, which is where the subtle rules live ----------------

    def _enter(self, scene_id: str) -> Turn:
        """Move the reader into a scene, play it out, and follow any jumps.

        The order is the one written down in STORY_FORMAT.md, and it is not
        arbitrary:

            1. the reader is moved
            2. the visit is counted
            3. the whole of `on_enter` runs
            4. only then is a jump followed

        Steps 3 and 4 are kept apart so that `scene_id` is still the scene being
        entered for the whole of its own `on_enter`. Follow the jump immediately
        and a `first_time` inside `on_enter` would be asking about somewhere the
        reader has not been yet, while the author who wrote it believed they were
        asking about here.
        """
        messages: list[Paragraph] = []
        trail: list[str] = []

        for _ in range(MAX_JUMPS_PER_TURN + 1):
            self.state.scene_id = scene_id
            self.state.visit(scene_id)  # counted before `on_enter`, so first_time works
            trail.append(scene_id)

            effects = apply_actions(self.story.scenes[scene_id].on_enter, self.state)
            messages.extend(effects.messages)

            if effects.goto is None:
                return Turn(messages=tuple(messages), entered=self.view())
            scene_id = effects.goto

        raise EngineError(
            f"this turn jumped through more than {MAX_JUMPS_PER_TURN} scenes "
            f"without stopping:\n  {' -> '.join(trail)}\n"
            "Somewhere in there is a loop of scenes that always jump away."
        )

    def _no_such_option(self, number: int) -> str:
        if self.is_over:
            return (
                f"there is no option {number}: the story has ended.\n"
                "The ending above is where this run finishes."
            )
        available = ", ".join(str(o.number) for o in self.options())
        return f"there is no option {number} here. Available: {available}."

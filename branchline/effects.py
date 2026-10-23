"""Actions: JSON in the story file -> typed action lists, and applying them.

Like `conditions.py`, this module both *parses* an action and *carries it out*,
so the parser and the interpreter share one list of verbs and cannot drift apart.
`engine.py` decides when a list of actions runs; this module decides what running
means.

The action vocabulary is deliberately small. It is the entire set of things a
story can do to the world, which means an author can hold it in their head -- and
means the engine never needs a special case for one particular story.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from .conditions import evaluate, parse_condition
from .errors import Pointer, StoryError
from .model import (
    Action,
    Chance,
    Conditional,
    DropItems,
    Goto,
    IncrementVars,
    Message,
    Paragraph,
    SetVars,
    TakeItems,
    Vocabulary,
)
from .prose import parse_paragraph
from .shape import (
    reject_unknown_keys,
    require_declared,
    require_id_or_list,
    require_integer,
    require_list,
    require_matches_type,
    require_number,
    require_object,
    require_text,
    suggest,
    user_keys,
)

if TYPE_CHECKING:
    from .state import GameState

ACTION_KEYS = frozenset(
    {"set", "inc", "take", "drop", "goto", "message", "when", "chance"}
)

_CONDITIONAL_KEYS = {"when", "do"}


def parse_actions(raw: Any, pointer: Pointer, vocab: Vocabulary) -> tuple[Action, ...]:
    """Parse a list of actions, e.g. a scene's ``on_enter`` or a choice's ``effects``."""
    items = require_list(raw, pointer, "a list of actions")
    actions = tuple(
        parse_action(item, pointer.index(i), vocab) for i, item in enumerate(items)
    )
    _reject_actions_after_a_jump(actions, pointer)
    return actions


def _reject_actions_after_a_jump(actions: tuple[Action, ...], pointer: Pointer) -> None:
    """Nothing written after an unconditional ``goto`` can ever run.

    The first jump that happens wins and ends the list (see `_apply`), so
    everything below it is unreachable -- a `take` that never takes anything, a
    `message` nobody reads. It is dead code the author cannot see, which is the
    failure this whole project is arranged against, and it is cheap to catch
    here because every action list in the story goes through this function:
    a scene's ``on_enter``, a choice's ``effects``, and the ``do``/``then``/
    ``else`` of anything nested.

    Only a *top-level* goto counts. Nested inside a ``when`` or a ``chance`` it
    fires conditionally, and the list carries on -- that is the idiom the loader
    itself recommends for a scene that only sometimes jumps away.
    """
    for index, action in enumerate(actions):
        if not isinstance(action, Goto):
            continue
        if index + 1 < len(actions):
            remaining = len(actions) - index - 1
            raise StoryError(
                f'{remaining} action{"s" if remaining > 1 else ""} follow an '
                'unconditional "goto", which ends the list, so they can never run',
                pointer=pointer.index(index),
                hint=(
                    "move them into the scene being jumped to, or guard the jump "
                    'with { "when": ..., "do": [ { "goto": ... } ] } so the list '
                    "carries on when it does not fire"
                ),
            )
        return  # it is the last thing in the list, which is the ordinary case


def parse_action(raw: Any, pointer: Pointer, vocab: Vocabulary) -> Action:
    obj = require_object(raw, pointer, "an action")
    keys = user_keys(obj)

    if not keys:
        raise StoryError(
            "this action is empty",
            pointer=pointer,
            hint='an action names one verb, e.g. { "take": "brass_key" }',
        )

    if _CONDITIONAL_KEYS & set(keys):
        return _build_conditional(obj, pointer, vocab)

    if len(keys) > 1:
        raise StoryError(
            f"an action holds exactly one verb, but this has {len(keys)}: {', '.join(keys)}",
            pointer=pointer,
            hint='split them into separate list entries, e.g. [ { "take": "key" }, { "set": { ... } } ]',
        )

    op = keys[0]
    if op not in ACTION_KEYS:
        raise StoryError(
            f'"{op}" is not an action this engine knows{suggest(op, ACTION_KEYS)}',
            pointer=pointer.key(op),
            hint=f"available: {', '.join(sorted(ACTION_KEYS))}",
        )

    return _build(op, obj, pointer, vocab)


def _build(op: str, obj: Mapping[str, Any], pointer: Pointer, vocab: Vocabulary) -> Action:
    value = obj[op]
    here = pointer.key(op)

    if op == "set":
        pairs = require_object(value, here, '"set"')
        _reject_empty(pairs, here, '"set"')
        values: dict[str, Any] = {}
        for name in user_keys(pairs):
            decl = require_declared(name, here.key(name), vocab, "variable")
            require_matches_type(pairs[name], decl.type, here.key(name), name, "be set to")
            values[name] = pairs[name]
        return SetVars(values)

    if op == "inc":
        pairs = require_object(value, here, '"inc"')
        _reject_empty(pairs, here, '"inc"')
        deltas: dict[str, int] = {}
        for name in user_keys(pairs):
            decl = require_declared(name, here.key(name), vocab, "variable")
            if decl.type != "int":
                raise StoryError(
                    f'"{name}" is declared as {decl.type}, so it cannot be incremented',
                    pointer=here.key(name),
                    hint='"inc" counts; it only means something for an int variable',
                )
            deltas[name] = require_integer(pairs[name], here.key(name), f'the amount added to "{name}"')
        return IncrementVars(deltas)

    if op in ("take", "drop"):
        wanted = require_id_or_list(value, here, f'the items listed in "{op}"')
        for item_id in wanted:
            require_declared(item_id, here, vocab, "item")
        return TakeItems(wanted) if op == "take" else DropItems(wanted)

    if op == "goto":
        scene_id = require_text(value, here, '"goto"')
        require_declared(scene_id, here, vocab, "scene")
        return Goto(scene_id)

    if op == "message":
        # A message is a list of paragraphs, exactly as a scene's `body` is --
        # same parser, same registers, same paces. Both guards stay here rather
        # than moving into `prose.py`.
        #
        # The outer one, so that a `message` that is not a list still says
        # `expected a list for "message"` and not `... for prose`: an author who
        # wrote `"message"` has never heard of prose, and naming a key they did
        # not write sends them looking for it.
        items = require_list(value, here, '"message"')
        # And the empty-list one, because `parse_paragraphs([])` is `()`. An
        # empty message would load cleanly as an action that does nothing --
        # written, unreadable, and invisible in play, which is the failure this
        # project refuses everywhere else.
        if not items:
            raise StoryError('"message" is an empty list', pointer=here)
        return Message(
            tuple(
                parse_paragraph(item, here.index(i), f'"message" paragraph {i}')
                for i, item in enumerate(items)
            )
        )

    # op == "chance"
    return _build_chance(value, here, vocab)


def _build_chance(value: Any, here: Pointer, vocab: Vocabulary) -> Chance:
    """``{"chance": {"p": 0.4, "then": [...], "else": [...]}}``.

    This is the system's only source of randomness, and it is an *action*, never a
    condition. A condition is evaluated several times per turn (filtering choices,
    re-rendering); a random one would answer differently the second time it was
    asked. Rolling here, once, and writing the result into state keeps the whole
    system deterministic given a seed.
    """
    inner = require_object(value, here, '"chance"')
    reject_unknown_keys(inner, here, {"p", "then", "else"}, '"chance"')

    if "p" not in inner:
        raise StoryError(
            '"chance" is missing "p"',
            pointer=here,
            hint='e.g. { "chance": { "p": 0.4, "then": [ ... ] } }',
        )
    if "then" not in inner:
        raise StoryError(
            '"chance" is missing "then"',
            pointer=here,
            hint='"then" is what happens when the coin comes up; "else" is optional',
        )

    probability = require_number(inner["p"], here.key("p"), '"p"')
    if not 0.0 < probability <= 1.0:
        raise StoryError(
            f'"p" must be greater than 0 and at most 1, but is {probability}',
            pointer=here.key("p"),
            hint='p is the chance of "then": 0.25 means one time in four',
        )

    then = parse_actions(inner["then"], here.key("then"), vocab)
    if not then:
        raise StoryError('"then" is an empty list', pointer=here.key("then"))

    otherwise = (
        parse_actions(inner["else"], here.key("else"), vocab) if "else" in inner else ()
    )
    return Chance(probability, then, otherwise)


def _build_conditional(
    obj: Mapping[str, Any], pointer: Pointer, vocab: Vocabulary
) -> Conditional:
    """``{"when": <condition>, "do": [<actions>]}``.

    One wrapper covers "only do this on a first visit", "only do this if they
    helped him" and everything like it, so the schema needs no special-purpose
    fields such as `on_first_enter`.
    """
    missing = _CONDITIONAL_KEYS - set(user_keys(obj))
    if missing:
        present = sorted(_CONDITIONAL_KEYS & set(user_keys(obj)))[0]
        absent = sorted(missing)[0]
        raise StoryError(
            f'"{present}" needs its partner "{absent}"',
            pointer=pointer,
            hint='a guarded action is { "when": <condition>, "do": [ <actions> ] }',
        )

    reject_unknown_keys(obj, pointer, _CONDITIONAL_KEYS, "a guarded action")
    condition = parse_condition(obj["when"], pointer.key("when"), vocab)
    actions = parse_actions(obj["do"], pointer.key("do"), vocab)
    if not actions:
        raise StoryError('"do" is an empty list', pointer=pointer.key("do"))
    return Conditional(condition, actions)


def _reject_empty(obj: Mapping[str, Any], pointer: Pointer, what: str) -> None:
    if not user_keys(obj):
        raise StoryError(f"{what} is empty", pointer=pointer)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Effects:
    """What running a list of actions produced for the reader to see.

    Only two things can come out of an action list: prose, and somewhere to go.
    Both are handed back rather than stashed on the engine, because a turn is one
    thing the presenter draws -- an engine-side queue that the presenter drains
    later would be a second channel, free to disagree with what is on screen and
    awkward to save.
    """

    messages: tuple[Paragraph, ...] = ()
    goto: str | None = None


def apply_actions(actions: tuple[Action, ...], state: GameState) -> Effects:
    """Run a list of actions against `state` and report what the reader sees."""
    messages: list[Paragraph] = []
    # Run first, then build the result. Written as one expression this silently
    # produces no messages at all: keyword arguments evaluate left to right, so
    # `tuple(messages)` would snapshot the list while it is still empty.
    goto = _apply(actions, state, messages)
    return Effects(messages=tuple(messages), goto=goto)


def _apply(
    actions: tuple[Action, ...], state: GameState, messages: list[Paragraph]
) -> str | None:
    """Run actions in order, stopping at the first one that sends the reader away.

    "First wins, then stop" rather than "last wins", and the difference is a dead
    branch. The loader's own advice for a scene that only sometimes jumps away is
    to guard the jump::

        [ { "when": { "has_item": "brass_key" }, "do": [ { "goto": "vestibule" } ] },
          { "goto": "gate" } ]

    -- "if you have the key, go inside; otherwise back to the gate". Under "last
    wins" the destination is always "gate" and that condition can never change
    anything: dead code in the author's file, invisible in play. Stopping also
    means prose written after a jump is not shown, which is right, because the
    reader has already left.
    """
    for action in actions:
        goto = _apply_one(action, state, messages)
        if goto is not None:
            return goto
    return None


def _apply_one(action: Action, state: GameState, messages: list[Paragraph]) -> str | None:
    if isinstance(action, SetVars):
        for name, value in action.values.items():
            state.variables[name] = value
        return None

    if isinstance(action, IncrementVars):
        for name, delta in action.deltas.items():
            state.variables[name] += delta
        return None

    if isinstance(action, TakeItems):
        for item_id in action.item_ids:
            state.take(item_id)
        return None

    if isinstance(action, DropItems):
        for item_id in action.item_ids:
            state.drop(item_id)
        return None

    if isinstance(action, Goto):
        return action.scene_id

    if isinstance(action, Message):
        messages.extend(action.paragraphs)
        return None

    if isinstance(action, Conditional):
        if evaluate(action.condition, state):
            return _apply(action.actions, state, messages)
        return None

    if isinstance(action, Chance):
        # The only draw in the system, and it happens once, here, at the moment
        # the action runs. The result is written into state by whichever branch
        # follows, so a replayed seed replays identically.
        branch = (
            action.then
            if state.rng.random() < action.probability
            else action.otherwise
        )
        return _apply(branch, state, messages)

    raise TypeError(
        f"no rule for applying {type(action).__name__}; "
        "this verb was added to model.py without an interpreter here"
    )

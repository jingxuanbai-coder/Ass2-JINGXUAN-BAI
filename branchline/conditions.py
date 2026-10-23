"""Conditions: JSON in the story file -> typed trees, and answering them.

This module both *parses* a condition and *evaluates* it against a live state.
The two are halves of one job -- the vocabulary of operators is the same list in
both directions -- so splitting them across modules would mean the parser and the
interpreter could drift apart without anything noticing. `engine.py` decides
*when* to ask a question; it never decides what an answer means.

A note on why unknown operators raise rather than returning a default: an
evaluator that answers "true" for something it does not understand fails *open*,
leaking gated content, and its author never learns about the typo. There is no
safe default here, so there is no default. The same reasoning is why
`evaluate()` ends in a bare `TypeError` rather than `return False`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from .errors import Pointer, StoryError
from .model import (
    AllOf,
    AnyOf,
    Condition,
    FirstTime,
    FlagSet,
    HasItem,
    Negate,
    VarAtLeast,
    VarIs,
    VisitCount,
    Visited,
    Vocabulary,
)
from .shape import (
    reject_unknown_keys,
    require_bool,
    require_declared,
    require_id_or_list,
    require_integer,
    require_list,
    require_matches_type,
    require_object,
    require_text,
    suggest,
    user_keys,
)

if TYPE_CHECKING:
    # Imported for typing only. `state.py` must never import this module, or the
    # two become a cycle -- the state is deliberately ignorant of what a
    # condition is.
    from .state import GameState

OPERATORS = frozenset(
    {"all", "any", "not", "has_item", "flag", "var", "visited", "visits", "first_time"}
)

#: Deep enough for anything a person would write, shallow enough that a
#: pathological file reports a nice error instead of a RecursionError.
MAX_DEPTH = 32


def parse_condition(raw: Any, pointer: Pointer, vocab: Vocabulary, depth: int = 0) -> Condition:
    """Turn one JSON condition object into a `Condition` node, or explain why not."""
    if depth > MAX_DEPTH:
        raise StoryError(
            f"conditions nested more than {MAX_DEPTH} deep",
            pointer=pointer,
            hint="this is almost certainly a mistake rather than a choice",
        )

    obj = require_object(raw, pointer, "a condition")
    keys = user_keys(obj)

    if not keys:
        raise StoryError(
            "this condition is empty",
            pointer=pointer,
            hint="a condition holds one operator, e.g. { \"has_item\": \"brass_key\" }",
        )
    # `var` is the single operator that carries a companion key ("is" or
    # "at_least"), so it is dispatched before the one-operator rule below.
    if "var" in keys:
        return _build_var(obj, pointer, vocab)

    if len(keys) > 1:
        raise StoryError(
            f"a condition holds exactly one operator, but this has {len(keys)}: {', '.join(keys)}",
            pointer=pointer,
            hint='combine them explicitly: { "all": [ { ... }, { ... } ] }',
        )

    op = keys[0]
    if op not in OPERATORS:
        raise StoryError(
            f'"{op}" is not a condition this engine knows{suggest(op, OPERATORS)}',
            pointer=pointer.key(op),
            hint=f"available: {', '.join(sorted(OPERATORS))}",
        )

    return _build(op, obj, pointer, vocab, depth)


def _build(
    op: str, obj: Mapping[str, Any], pointer: Pointer, vocab: Vocabulary, depth: int
) -> Condition:
    value = obj[op]
    here = pointer.key(op)

    if op in ("all", "any"):
        items = require_list(value, here, f"the operands of \"{op}\"")
        if not items:
            raise StoryError(
                f'"{op}" has no operands',
                pointer=here,
                hint=(
                    'an empty "all" is vacuously true and an empty "any" is vacuously '
                    "false; neither is ever what an author means"
                ),
            )
        children = tuple(
            parse_condition(item, here.index(i), vocab, depth + 1)
            for i, item in enumerate(items)
        )
        return AllOf(children) if op == "all" else AnyOf(children)

    if op == "not":
        return Negate(parse_condition(value, here, vocab, depth + 1))

    if op == "has_item":
        wanted = require_id_or_list(value, here, "the items listed in \"has_item\"")
        for item_id in wanted:
            require_declared(item_id, here, vocab, "item")
        return HasItem(wanted)

    if op == "flag":
        name = require_text(value, here, '"flag"')
        decl = require_declared(name, here, vocab, "variable")
        if decl.type != "bool":
            raise StoryError(
                f'"{name}" is declared as {decl.type}, so it cannot be used with "flag"',
                pointer=here,
                hint=(
                    f'"flag" asks whether something is true. For a {decl.type} variable '
                    f'use {{ "var": "{name}", "is": ... }} instead'
                ),
            )
        return FlagSet(name)

    if op == "visited":
        scene_id = require_text(value, here, '"visited"')
        require_declared(scene_id, here, vocab, "scene")
        return Visited(scene_id)

    if op == "visits":
        inner = require_object(value, here, '"visits"')
        reject_unknown_keys(inner, here, {"scene", "at_least"}, '"visits"')
        if "scene" not in inner or "at_least" not in inner:
            raise StoryError(
                '"visits" needs both "scene" and "at_least"',
                pointer=here,
                hint='e.g. { "visits": { "scene": "quay", "at_least": 2 } }',
            )
        scene_id = require_text(inner["scene"], here.key("scene"), '"visits" scene')
        require_declared(scene_id, here, vocab, "scene")
        threshold = require_integer(inner["at_least"], here.key("at_least"), '"at_least"')
        return VisitCount(scene_id, threshold)

    # op == "first_time"
    require_bool(value, here, '"first_time"')
    return FirstTime()


def _build_var(obj: Mapping[str, Any], pointer: Pointer, vocab: Vocabulary) -> Condition:
    """``{"var": "name", "is": value}`` or ``{"var": "name", "at_least": n}``.

    `var` is the one operator whose name and comparison live as sibling keys, so
    it is handled apart from the single-operator rule above.
    """
    keys = user_keys(obj)
    comparisons = [key for key in keys if key != "var"]
    here = pointer.key("var")

    if len(comparisons) != 1:
        raise StoryError(
            f'"var" needs exactly one comparison, found {len(comparisons) or "none"}',
            pointer=pointer,
            hint='"is" checks equality, "at_least" checks a minimum -- use one',
        )

    name = require_text(obj["var"], here, '"var"')
    decl = require_declared(name, here, vocab, "variable")
    comparison = comparisons[0]
    cptr = pointer.key(comparison)

    if comparison == "is":
        value = obj[comparison]
        require_matches_type(value, decl.type, cptr, name, "be compared to")
        return VarIs(name, value)

    if comparison == "at_least":
        if decl.type != "int":
            raise StoryError(
                f'"at_least" needs an int variable, but "{name}" is {decl.type}',
                pointer=cptr,
                hint='"at_least" compares sizes; it only means something for numbers',
            )
        threshold = require_integer(obj[comparison], cptr, '"at_least"')
        return VarAtLeast(name, threshold)

    raise StoryError(
        f'"{comparison}" is not a comparison this engine knows{suggest(comparison, {"is", "at_least"})}',
        pointer=cptr,
        hint='use "is" or "at_least"',
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate(condition: Condition, state: GameState) -> bool:
    """Answer one condition against the state of a run.

    Pure, and deliberately free of side effects: the same condition asked twice
    about the same state gives the same answer. This is what lets `engine.take()`
    re-derive the options after a reader has been staring at them for a while,
    and it is the reason randomness is an action and never a condition -- the
    second evaluation may be minutes after the first, and a coin flip would have
    no way to remember what it said.
    """
    if isinstance(condition, AllOf):
        return all(evaluate(child, state) for child in condition.children)
    if isinstance(condition, AnyOf):
        return any(evaluate(child, state) for child in condition.children)
    if isinstance(condition, Negate):
        return not evaluate(condition.child, state)

    if isinstance(condition, HasItem):
        return all(state.has(item_id) for item_id in condition.item_ids)

    if isinstance(condition, FlagSet):
        return state.variables[condition.name] is True
    if isinstance(condition, VarIs):
        return state.variables[condition.name] == condition.value
    if isinstance(condition, VarAtLeast):
        return state.variables[condition.name] >= condition.threshold

    if isinstance(condition, Visited):
        return state.visit_count(condition.scene_id) > 0
    if isinstance(condition, VisitCount):
        return state.visit_count(condition.scene_id) >= condition.threshold

    if isinstance(condition, FirstTime):
        # Asked about the scene the reader is in *now*, which the engine has
        # already counted -- so this is true for the whole of a first visit,
        # including while that scene's choices are being shown. Reading it as
        # "was the count 1" rather than "has it been counted yet" is what makes
        # a choice guarded on `first_time` behave the way its author expects:
        # offered on the first visit, and not after.
        return state.visit_count(state.scene_id) == 1

    raise TypeError(
        f"no rule for evaluating {type(condition).__name__}; "
        "this node was added to model.py without an evaluator here"
    )

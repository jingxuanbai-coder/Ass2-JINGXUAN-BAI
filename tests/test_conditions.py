"""Tests for conditions: parsing them, and answering them.

The most important test in this file is `test_an_unknown_operator_raises`. An
evaluator that answered "true" for something it did not recognise would fail
*open* -- leaking gated content -- and its author would never learn about the
typo. There is no safe default, so there is no default.

The second half of the file asks the same question of evaluation, which is why
it ends in a bare `TypeError` rather than `return False`.
"""

from __future__ import annotations

import pickle
import unittest
from dataclasses import dataclass

from branchline.conditions import MAX_DEPTH, evaluate, parse_condition
from branchline.model import (
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
)
from branchline.state import GameState
from tests.fixtures import (
    StoryTestCase,
    minimal_story,
    minimal_vocabulary,
    root_pointer,
)


def parse(raw):
    return parse_condition(raw, root_pointer(), minimal_vocabulary())


def state():
    return GameState.new(minimal_story(), seed=1)


class OperatorTests(unittest.TestCase):
    def test_all(self) -> None:
        node = parse({"all": [{"has_item": "brass_key"}, {"flag": "trusted"}]})
        self.assertIsInstance(node, AllOf)
        self.assertEqual(len(node.children), 2)
        self.assertIsInstance(node.children[0], HasItem)
        self.assertIsInstance(node.children[1], FlagSet)

    def test_any(self) -> None:
        node = parse({"any": [{"has_item": "oil_can"}, {"has_item": "brass_key"}]})
        self.assertIsInstance(node, AnyOf)
        self.assertEqual(len(node.children), 2)

    def test_not(self) -> None:
        node = parse({"not": {"visited": "cellar"}})
        self.assertIsInstance(node, Negate)
        self.assertIsInstance(node.child, Visited)

    def test_has_item_with_one_id(self) -> None:
        self.assertEqual(parse({"has_item": "brass_key"}), HasItem(("brass_key",)))

    def test_has_item_with_several_ids(self) -> None:
        self.assertEqual(
            parse({"has_item": ["brass_key", "oil_can"]}),
            HasItem(("brass_key", "oil_can")),
        )

    def test_flag(self) -> None:
        self.assertEqual(parse({"flag": "trusted"}), FlagSet("trusted"))

    def test_var_is(self) -> None:
        self.assertEqual(parse({"var": "mood", "is": "wary"}), VarIs("mood", "wary"))

    def test_var_at_least(self) -> None:
        self.assertEqual(
            parse({"var": "lamps_lit", "at_least": 3}), VarAtLeast("lamps_lit", 3)
        )

    def test_visited(self) -> None:
        self.assertEqual(parse({"visited": "tide_table"}), Visited("tide_table"))

    def test_visits(self) -> None:
        self.assertEqual(
            parse({"visits": {"scene": "hall", "at_least": 2}}),
            VisitCount("hall", 2),
        )

    def test_first_time(self) -> None:
        self.assertEqual(parse({"first_time": True}), FirstTime())

    def test_nesting(self) -> None:
        node = parse(
            {
                "all": [
                    {"any": [{"has_item": "brass_key"}, {"flag": "trusted"}]},
                    {"not": {"var": "lamps_lit", "at_least": 5}},
                ]
            }
        )
        self.assertIsInstance(node.children[1].child, VarAtLeast)

    def test_annotations_inside_a_condition_are_ignored(self) -> None:
        self.assertEqual(
            parse({"has_item": "brass_key", "_why": "she gave it to him"}),
            HasItem(("brass_key",)),
        )


class MissingOperatorTests(StoryTestCase):
    def test_an_unknown_operator_raises(self) -> None:
        self.assertRejectsCondition(
            {"has_itm": "brass_key"},
            mentions=("has_itm", "not a condition", 'did you mean "has_item"'),
            pointer="has_itm",
        )

    def test_a_string_is_not_a_condition(self) -> None:
        """A mini-language in a string would be code wearing prose clothing, and
        the validator could never walk it to check the ids inside."""
        self.assertRejectsCondition(
            "has_item('brass_key')", mentions=("expected an object",)
        )

    def test_an_empty_condition(self) -> None:
        self.assertRejectsCondition({}, mentions=("empty",))

    def test_two_operators_in_one_condition(self) -> None:
        self.assertRejectsCondition(
            {"has_item": "brass_key", "flag": "trusted"},
            mentions=("exactly one operator", "has_item", "flag"),
        )

    def test_all_with_no_operands(self) -> None:
        self.assertRejectsCondition(
            {"all": []}, mentions=("no operands", "vacuously"), pointer="all"
        )

    def test_any_with_no_operands(self) -> None:
        self.assertRejectsCondition({"any": []}, mentions=("no operands",))

    def test_operands_must_be_a_list(self) -> None:
        self.assertRejectsCondition(
            {"all": {"has_item": "brass_key"}}, mentions=("expected a list",)
        )

    def test_conditions_cannot_nest_without_limit(self) -> None:
        raw: object = {"has_item": "brass_key"}
        for _ in range(MAX_DEPTH + 2):
            raw = {"not": raw}
        self.assertRejectsCondition(raw, mentions=("nested",))


class VocabularyTests(StoryTestCase):
    def test_has_item_must_name_a_declared_item(self) -> None:
        self.assertRejectsCondition(
            {"has_item": "iron_key"}, mentions=("iron_key", "not an item")
        )

    def test_visited_must_name_a_declared_scene(self) -> None:
        self.assertRejectsCondition(
            {"visited": "attic"}, mentions=("attic", "not a scene")
        )

    def test_visits_must_name_a_declared_scene(self) -> None:
        self.assertRejectsCondition(
            {"visits": {"scene": "attic", "at_least": 1}}, mentions=("attic",)
        )

    def test_visits_needs_both_keys(self) -> None:
        self.assertRejectsCondition(
            {"visits": {"scene": "hall"}}, mentions=("scene", "at_least")
        )

    def test_visits_rejects_a_key_it_does_not_know(self) -> None:
        self.assertRejectsCondition(
            {"visits": {"scene": "hall", "atleast": 1}},
            mentions=("atleast", 'did you mean "at_least"'),
        )

    def test_flag_on_a_string_variable(self) -> None:
        self.assertRejectsCondition(
            {"flag": "mood"}, mentions=("mood", "declared as string", '"var"')
        )


class VariableComparisonTests(StoryTestCase):
    def test_at_least_on_a_string_variable(self) -> None:
        self.assertRejectsCondition(
            {"var": "mood", "at_least": 2}, mentions=("mood", "int")
        )

    def test_is_against_the_wrong_type(self) -> None:
        self.assertRejectsCondition(
            {"var": "lamps_lit", "is": "three"},
            mentions=("lamps_lit", "declared as int", "a piece of text"),
        )

    def test_var_without_a_comparison(self) -> None:
        self.assertRejectsCondition(
            {"var": "mood"}, mentions=("exactly one comparison", "none")
        )

    def test_var_with_two_comparisons(self) -> None:
        self.assertRejectsCondition(
            {"var": "lamps_lit", "is": 3, "at_least": 2},
            mentions=("exactly one comparison", "found 2"),
        )

    def test_var_with_an_unknown_comparison(self) -> None:
        self.assertRejectsCondition(
            {"var": "lamps_lit", "at_most": 3},
            mentions=("at_most", 'did you mean "at_least"'),
        )

    def test_var_must_name_a_declared_variable(self) -> None:
        self.assertRejectsCondition(
            {"var": "luck", "is": 1}, mentions=("luck", "not a variable")
        )

    def test_first_time_must_be_true_or_false(self) -> None:
        self.assertRejectsCondition({"first_time": "yes"}, mentions=("true or false",))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unhandled(Condition):
    """A node from a future version of the schema, as far as `evaluate` knows."""


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = state()

    def answered(self, raw) -> bool:
        return evaluate(parse(raw), self.state)

    # -- combinators --------------------------------------------------------

    def test_all_needs_every_operand(self) -> None:
        self.state.take("brass_key")
        self.assertFalse(
            self.answered({"all": [{"has_item": "brass_key"}, {"has_item": "oil_can"}]})
        )
        self.state.take("oil_can")
        self.assertTrue(
            self.answered({"all": [{"has_item": "brass_key"}, {"has_item": "oil_can"}]})
        )

    def test_any_needs_one(self) -> None:
        self.state.take("oil_can")
        self.assertTrue(
            self.answered({"any": [{"has_item": "brass_key"}, {"has_item": "oil_can"}]})
        )
        self.state.drop("oil_can")
        self.assertFalse(
            self.answered({"any": [{"has_item": "brass_key"}, {"has_item": "oil_can"}]})
        )

    def test_not_inverts(self) -> None:
        self.assertTrue(self.answered({"not": {"has_item": "brass_key"}}))
        self.state.take("brass_key")
        self.assertFalse(self.answered({"not": {"has_item": "brass_key"}}))

    # -- what you are carrying ----------------------------------------------

    def test_has_item_with_several_ids_means_all_of_them(self) -> None:
        """`has_item` taking a list reads as "and", not "or".

        Worth pinning down because `any` is the operator for "or", and an author
        who wanted one of two things has a way to say so -- so this list form
        would otherwise be ambiguous at exactly the wrong moment.
        """
        self.state.take("brass_key")
        self.assertFalse(self.answered({"has_item": ["brass_key", "oil_can"]}))
        self.state.take("oil_can")
        self.assertTrue(self.answered({"has_item": ["brass_key", "oil_can"]}))

    # -- variables ----------------------------------------------------------

    def test_flag_reads_a_boolean_variable(self) -> None:
        self.assertFalse(self.answered({"flag": "trusted"}))
        self.state.variables["trusted"] = True
        self.assertTrue(self.answered({"flag": "trusted"}))

    def test_var_is_compares(self) -> None:
        self.assertFalse(self.answered({"var": "mood", "is": "settled"}))
        self.state.variables["mood"] = "settled"
        self.assertTrue(self.answered({"var": "mood", "is": "settled"}))

    def test_var_at_least_is_a_minimum_not_an_equality(self) -> None:
        self.assertFalse(self.answered({"var": "lamps_lit", "at_least": 3}))
        self.state.variables["lamps_lit"] = 3
        self.assertTrue(self.answered({"var": "lamps_lit", "at_least": 3}))
        self.state.variables["lamps_lit"] = 9
        self.assertTrue(self.answered({"var": "lamps_lit", "at_least": 3}))

    # -- where you have been ------------------------------------------------

    def test_visited_is_false_for_a_scene_never_entered(self) -> None:
        self.assertFalse(self.answered({"visited": "hall"}))

    def test_visited_is_true_once_the_scene_has_been_entered(self) -> None:
        self.state.visit("hall")
        self.assertTrue(self.answered({"visited": "hall"}))

    def test_visits_counts_entries(self) -> None:
        self.state.visit("hall")
        self.assertFalse(self.answered({"visits": {"scene": "hall", "at_least": 2}}))
        self.state.visit("hall")
        self.assertTrue(self.answered({"visits": {"scene": "hall", "at_least": 2}}))

    def test_visits_is_about_the_scene_named_not_the_one_you_are_in(self) -> None:
        """The whole reason `visited` and `visits` take a scene id at all."""
        self.state.scene_id = "cellar"
        self.state.visit("hall")
        self.state.visit("hall")
        self.assertTrue(self.answered({"visits": {"scene": "hall", "at_least": 2}}))
        self.assertFalse(self.answered({"visited": "cellar"}))

    # -- first_time, which is the one with a rule worth remembering ----------

    def test_first_time_is_true_during_the_first_entry(self) -> None:
        self.state.scene_id = "hall"
        self.state.visit("hall")  # the engine counts the entry before asking
        self.assertTrue(self.answered({"first_time": True}))

    def test_first_time_is_false_on_every_later_entry(self) -> None:
        self.state.scene_id = "hall"
        self.state.visit("hall")
        self.state.visit("hall")
        self.assertFalse(self.answered({"first_time": True}))

    def test_first_time_stays_true_while_the_choices_are_being_shown(self) -> None:
        """The subtle half of the rule, and the one that decides whether
        `first_time` is useful on a *choice*.

        Nothing else happens between entering a scene and the reader pressing a
        key, so a choice guarded on `first_time` is offered on the first visit
        and not afterwards -- which is what an author writing it means. It would
        silently never be offered if `first_time` asked "has this been counted
        yet" instead of "is this the first count".
        """
        self.state.scene_id = "hall"
        self.state.visit("hall")
        # ...time passes, the reader reads the prose, then:
        self.assertTrue(self.answered({"first_time": True}))

    def test_first_time_is_about_the_scene_you_are_in(self) -> None:
        """Not the last scene counted, and not every scene at once.

        Somewhere else has been visited twice; this is the first time here. Both
        readings of "first time" that get this wrong -- the last scene counted,
        or any scene being new -- would answer differently.
        """
        self.state.visit("cellar")
        self.state.visit("cellar")
        self.state.scene_id = "hall"
        self.state.visit("hall")
        self.assertTrue(self.answered({"first_time": True}))

    # -- the property the whole design rests on -----------------------------

    def test_asking_twice_gives_the_same_answer(self) -> None:
        """Determinism, which is what lets `take()` re-derive the options.

        A condition is evaluated more than once per turn -- once to filter the
        choices, again when one is taken, again if the scene is redrawn. If any
        condition could answer differently the second time, an option could
        vanish between being printed and being pressed. This is the test that
        would fail if randomness were ever allowed into a condition.
        """
        self.state.take("brass_key")
        self.state.visit("hall")
        self.state.scene_id = "hall"
        raw = {
            "all": [
                {"has_item": "brass_key"},
                {"visited": "hall"},
                {"first_time": True},
                {"any": [{"flag": "trusted"}, {"has_item": "oil_can"}]},
            ]
        }
        answers = {self.answered(raw) for _ in range(20)}
        self.assertEqual(len(answers), 1, "a condition changed its mind")

    def test_asking_does_not_change_anything(self) -> None:
        """Evaluating observes; it never counts a visit or spends a draw.

        The matching mistake to the one above: a condition with a side effect
        would make merely *rendering* a scene alter the run.
        """
        self.state.take("brass_key")
        # Pickled rather than printed: `repr` skips the generator, and spending
        # a draw would be the likeliest side effect of all.
        before = pickle.dumps(self.state)
        self.answered({"all": [{"has_item": "brass_key"}, {"first_time": True}]})
        self.assertEqual(pickle.dumps(self.state), before)

    # -- failing closed -----------------------------------------------------

    def test_a_node_with_no_evaluator_raises_rather_than_answering(self) -> None:
        """The same argument as the unknown operator, one level down.

        `return False` here would be the safe-looking choice and the dangerous
        one: a forgotten node would quietly close every gate that used it, and a
        schema addition would look like it worked.
        """
        with self.assertRaises(TypeError) as caught:
            evaluate(Unhandled(), self.state)
        self.assertIn("Unhandled", str(caught.exception))

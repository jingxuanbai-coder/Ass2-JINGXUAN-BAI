"""Tests for actions: parsing them, and running them.

The action vocabulary is the entire set of things a story can do to the world.
These tests pin it down exactly, including the rule that makes the whole system
deterministic: randomness lives in `Chance`, an action, and nowhere else.

The second half covers applying a list, where the rule with teeth is that the
first `goto` reached wins and ends the list.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from branchline import StoryError
from branchline.effects import apply_actions, parse_action, parse_actions
from branchline.model import (
    Action,
    AllOf,
    Chance,
    Conditional,
    DropItems,
    Goto,
    IncrementVars,
    Message,
    Paragraph,
    SetVars,
    TakeItems,
    VarAtLeast,
)
from branchline.state import GameState
from tests.fixtures import (
    StoryTestCase,
    minimal_story,
    minimal_vocabulary,
    root_pointer,
    said,
)


def parse(raw):
    return parse_action(raw, root_pointer(), minimal_vocabulary())


def parse_many(raw):
    return parse_actions(raw, root_pointer(), minimal_vocabulary())


def state():
    return GameState.new(minimal_story(), seed=1)


class VerbTests(unittest.TestCase):
    def test_set(self) -> None:
        self.assertEqual(parse({"set": {"trusted": True}}), SetVars({"trusted": True}))

    def test_set_a_string(self) -> None:
        self.assertEqual(parse({"set": {"mood": "settled"}}), SetVars({"mood": "settled"}))

    def test_set_several_at_once(self) -> None:
        node = parse({"set": {"trusted": True, "lamps_lit": 6}})
        self.assertEqual(node.values, {"trusted": True, "lamps_lit": 6})

    def test_inc(self) -> None:
        self.assertEqual(parse({"inc": {"lamps_lit": 1}}), IncrementVars({"lamps_lit": 1}))

    def test_inc_backwards(self) -> None:
        self.assertEqual(parse({"inc": {"lamps_lit": -1}}), IncrementVars({"lamps_lit": -1}))

    def test_take_one_item(self) -> None:
        self.assertEqual(parse({"take": "brass_key"}), TakeItems(("brass_key",)))

    def test_take_several_items(self) -> None:
        self.assertEqual(
            parse({"take": ["brass_key", "oil_can"]}),
            TakeItems(("brass_key", "oil_can")),
        )

    def test_drop(self) -> None:
        self.assertEqual(parse({"drop": "oil_can"}), DropItems(("oil_can",)))

    def test_goto(self) -> None:
        self.assertEqual(parse({"goto": "cellar"}), Goto("cellar"))

    def test_message(self) -> None:
        self.assertEqual(
            parse({"message": ["He holds it out.", "You take it."]}),
            Message(said("He holds it out.", "You take it.")),
        )

    def test_a_message_can_carry_a_register(self) -> None:
        """The world's reply is prose like any other, and can be an aside.

        Writing the same sentence as a scene's body and as a message used to
        mean writing it two different ways, and only one of the two could be an
        aside. There is one paragraph vocabulary now, so there is nothing to
        keep in step.
        """
        self.assertEqual(
            parse({"message": [{"text": "Not yet.", "style": "aside"}]}),
            Message((Paragraph("Not yet.", style="aside"),)),
        )

    def test_a_message_keeps_the_pace_it_was_given(self) -> None:
        self.assertEqual(
            parse({"message": [{"text": "Slowly.", "pace": "slow"}]}),
            Message((Paragraph("Slowly.", pace="slow"),)),
        )

    def test_annotation_keys_are_ignored(self) -> None:
        self.assertEqual(parse({"take": "brass_key", "_why": "he gives it"}), TakeItems(("brass_key",)))


class ConditionalTests(unittest.TestCase):
    def test_guarded_actions(self) -> None:
        node = parse({"when": {"first_time": True}, "do": [{"inc": {"lamps_lit": 1}}]})
        self.assertIsInstance(node, Conditional)
        self.assertIsInstance(node.actions[0], IncrementVars)

    def test_guard_can_hold_several_actions(self) -> None:
        node = parse(
            {
                "when": {"flag": "trusted"},
                "do": [{"take": "brass_key"}, {"set": {"mood": "settled"}}],
            }
        )
        self.assertEqual(len(node.actions), 2)

    def test_guards_can_nest(self) -> None:
        node = parse(
            {
                "when": {"flag": "trusted"},
                "do": [
                    {"when": {"var": "lamps_lit", "at_least": 3}, "do": [{"goto": "cellar"}]}
                ],
            }
        )
        self.assertIsInstance(node.actions[0], Conditional)
        self.assertIsInstance(node.actions[0].condition, VarAtLeast)

    def test_a_guard_may_hold_a_condition(self) -> None:
        node = parse({"when": {"all": [{"flag": "trusted"}]}, "do": [{"goto": "cellar"}]})
        self.assertIsNotNone(node.condition)


class ChanceTests(unittest.TestCase):
    def test_a_coin_flip(self) -> None:
        node = parse({"chance": {"p": 0.4, "then": [{"take": "brass_key"}]}})
        self.assertIsInstance(node, Chance)
        self.assertEqual(node.probability, 0.4)
        self.assertEqual(node.otherwise, ())

    def test_else_is_optional_but_understood(self) -> None:
        node = parse(
            {
                "chance": {
                    "p": 0.5,
                    "then": [{"take": "oil_can"}],
                    "else": [{"message": ["Nothing here."]}],
                }
            }
        )
        self.assertEqual(len(node.otherwise), 1)

    def test_certainty_is_allowed(self) -> None:
        self.assertEqual(parse({"chance": {"p": 1.0, "then": [{"goto": "cellar"}]}}).probability, 1.0)

    def test_zero_is_not_a_chance(self) -> None:
        self.assertRejectsChance({"p": 0, "then": [{"goto": "cellar"}]}, "0.0")

    def test_more_than_certain_is_not_a_chance(self) -> None:
        self.assertRejectsChance({"p": 1.5, "then": [{"goto": "cellar"}]}, "1.5")

    def test_needs_then(self) -> None:
        self.assertRejectsChance({"p": 0.5}, 'missing "then"')

    def test_needs_p(self) -> None:
        self.assertRejectsChance({"then": [{"goto": "cellar"}]}, 'missing "p"')

    def test_then_cannot_be_empty(self) -> None:
        self.assertRejectsChance({"p": 0.5, "then": []}, "empty")

    def test_rejects_a_key_it_does_not_know(self) -> None:
        self.assertRejectsChance(
            {"p": 0.5, "then": [{"goto": "cellar"}], "otherwise": []}, "otherwise"
        )

    def assertRejectsChance(self, chance, fragment: str) -> None:
        with self.assertRaises(StoryError) as caught:
            parse({"chance": chance})
        self.assertIn(fragment, str(caught.exception))


class MalformedActionTests(StoryTestCase):
    def test_an_unknown_verb(self) -> None:
        self.assertRejectsAction(
            {"tkae": "brass_key"}, mentions=("tkae", 'did you mean "take"')
        )

    def test_two_verbs_in_one_action(self) -> None:
        self.assertRejectsAction(
            {"take": "brass_key", "set": {"trusted": True}},
            mentions=("exactly one verb", "take", "set"),
        )

    def test_an_empty_action(self) -> None:
        self.assertRejectsAction({}, mentions=("empty",))

    def test_an_action_given_as_text(self) -> None:
        self.assertRejectsAction("take brass_key", mentions=("expected an object",))

    def test_a_guard_missing_its_do(self) -> None:
        self.assertRejectsAction(
            {"when": {"flag": "trusted"}}, mentions=("when", "do")
        )

    def test_a_guard_missing_its_when(self) -> None:
        self.assertRejectsAction({"do": [{"goto": "cellar"}]}, mentions=("do", "when"))

    def test_a_guard_with_an_empty_do(self) -> None:
        self.assertRejectsAction(
            {"when": {"flag": "trusted"}, "do": []}, mentions=("empty",)
        )

    def test_the_action_list_must_be_a_list(self) -> None:
        with self.assertRaises(StoryError) as caught:
            parse_many({"take": "brass_key"})
        self.assertIn("expected a list", str(caught.exception))


class VocabularyTests(StoryTestCase):
    def test_taking_an_item_the_story_never_declared(self) -> None:
        self.assertRejectsAction(
            {"take": "iron_key"}, mentions=("iron_key", "not an item")
        )

    def test_dropping_an_item_the_story_never_declared(self) -> None:
        self.assertRejectsAction({"drop": "iron_key"}, mentions=("iron_key",))

    def test_goto_a_scene_that_does_not_exist(self) -> None:
        self.assertRejectsAction(
            {"goto": "cellers"}, mentions=("cellers", 'did you mean "cellar"')
        )

    def test_setting_a_variable_the_story_never_declared(self) -> None:
        self.assertRejectsAction(
            {"set": {"trused": True}}, mentions=("trused", "not a variable")
        )

    def test_setting_an_empty_object(self) -> None:
        self.assertRejectsAction({"set": {}}, mentions=("empty",))

    def test_setting_a_variable_to_the_wrong_type(self) -> None:
        self.assertRejectsAction(
            {"set": {"lamps_lit": "six"}}, mentions=("lamps_lit", "declared as int")
        )

    def test_incrementing_a_boolean(self) -> None:
        self.assertRejectsAction(
            {"inc": {"trusted": 1}}, mentions=("trusted", "declared as bool")
        )

    def test_incrementing_by_something_that_is_not_a_number(self) -> None:
        self.assertRejectsAction(
            {"inc": {"lamps_lit": "one"}}, mentions=("whole number",)
        )

    def test_an_empty_message(self) -> None:
        self.assertRejectsAction({"message": []}, mentions=("empty",))

    def test_a_message_that_is_not_text(self) -> None:
        # Both the wording and the locator changed when a message became a list
        # of paragraphs -- a paragraph is now either text or an object, so the
        # diagnosis has to say so. Pinned here because it is exactly the kind of
        # diagnostic that gets quietly reworded by a change like that one, and
        # nobody notices until an author is confused by it.
        self.assertRejectsAction(
            {"message": [7]},
            pointer="message[0]",
            mentions=('"message" paragraph 0', "should be text"),
        )

    def test_a_message_pointing_at_a_register_that_does_not_exist(self) -> None:
        """The register vocabulary reaches messages, typo and all.

        Worth pinning because it is the whole of what delegating buys: a message
        gets the four registers, and gets told which four, without `effects.py`
        knowing they exist.
        """
        self.assertRejectsAction(
            {"message": [{"text": "Hush.", "style": "whisperr"}]},
            pointer="message[0].style",
            mentions=("whisperr", "aside, letter, sign, whisper"),
        )

    def test_a_message_that_is_not_a_list_at_all(self) -> None:
        # Still says "message", not "prose". An author who wrote a `message` has
        # never heard of prose, and being told about a key they did not write
        # sends them looking for one that is not in their file.
        self.assertRejectsAction(
            {"message": "Too late."},
            pointer="message",
            mentions=('"message"', "expected a list"),
        )


class ListTests(unittest.TestCase):
    def test_a_list_of_actions(self) -> None:
        actions = parse_many(
            [
                {"take": "brass_key"},
                {"set": {"trusted": True}},
                {"message": ["The room relaxes."]},
            ]
        )
        self.assertEqual(len(actions), 3)
        self.assertIsInstance(actions[2], Message)

    def test_an_empty_list_is_allowed(self) -> None:
        """A scene with an empty `on_enter` is the same as a scene with none."""
        self.assertEqual(parse_many([]), ())

    def test_the_condition_inside_a_guard_is_fully_parsed(self) -> None:
        node = parse(
            {
                "when": {"all": [{"has_item": "brass_key"}, {"flag": "trusted"}]},
                "do": [{"goto": "cellar"}],
            }
        )
        self.assertIsInstance(node.condition, AllOf)
        self.assertEqual(len(node.condition.children), 2)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unhandled(Action):
    """A verb from a future version of the schema, as far as `apply_actions` knows."""


class ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = state()

    def run_actions(self, raw):
        return apply_actions(parse_many(raw), self.state)

    # -- the verbs ----------------------------------------------------------

    def test_set_writes_a_variable(self) -> None:
        self.run_actions([{"set": {"mood": "settled"}}])
        self.assertEqual(self.state.variables["mood"], "settled")

    def test_inc_adds_to_a_variable(self) -> None:
        # Counted from the declared initial rather than from zero, so that
        # editing the fixture's numbers cannot quietly turn this into a test of
        # nothing at all.
        start = self.state.variables["lamps_lit"]
        self.run_actions([{"inc": {"lamps_lit": 3}}, {"inc": {"lamps_lit": 1}}])
        self.assertEqual(self.state.variables["lamps_lit"], start + 4)

    def test_take_and_drop(self) -> None:
        self.run_actions([{"take": ["brass_key", "oil_can"]}])
        self.assertEqual(self.state.carried_ids(), ("brass_key", "oil_can"))
        self.run_actions([{"drop": "brass_key"}])
        self.assertEqual(self.state.carried_ids(), ("oil_can",))

    def test_a_later_action_sees_an_earlier_one(self) -> None:
        """Actions within a list run in order, and the state is live between them.

        This is what makes `[{"take": "brass_key"}, {"goto": "gate"}]` work, and
        it is not free -- batching the changes and applying them at the end would
        pass every test above and fail this one.
        """
        effects = self.run_actions(
            [
                {"take": "brass_key"},
                {
                    "when": {"has_item": "brass_key"},
                    "do": [{"message": ["It is in your pocket."]}],
                },
            ]
        )
        self.assertEqual(effects.messages, said("It is in your pocket."))

    # -- prose --------------------------------------------------------------

    def test_messages_are_collected_in_order(self) -> None:
        """Asserted on content, not just on count.

        A version of `apply_actions` that built its result before running the
        actions returned no messages at all -- this is the test that catches it.
        """
        effects = self.run_actions(
            [
                {"message": ["One."]},
                {"message": ["Two.", "Three."]},
            ]
        )
        self.assertEqual(effects.messages, said("One.", "Two.", "Three."))

    def test_a_list_can_be_silent(self) -> None:
        self.assertEqual(self.run_actions([{"take": "brass_key"}]).messages, ())

    def test_a_nested_message_still_arrives(self) -> None:
        effects = self.run_actions(
            [
                {
                    "when": {"not": {"has_item": "brass_key"}},
                    "do": [{"message": ["He looks at your hands."]}],
                }
            ]
        )
        self.assertEqual(effects.messages, said("He looks at your hands."))

    # -- going somewhere ----------------------------------------------------

    def test_goto_is_reported(self) -> None:
        self.assertEqual(self.run_actions([{"goto": "cellar"}]).goto, "cellar")

    def test_nothing_to_go_to_is_none(self) -> None:
        self.assertIsNone(self.run_actions([{"set": {"mood": "calm"}}]).goto)

    def test_the_first_goto_wins_and_ends_the_list(self) -> None:
        """The rule, stated as plainly as it can be.

        "Last wins" would be just as easy to implement and would silently break
        the idiom the loader itself recommends for a scene that only sometimes
        jumps away -- the guarded first jump would become dead code.

        Built from model objects rather than JSON, because the loader now
        refuses this list outright (`_reject_actions_after_a_jump`). The runtime
        rule still has to hold, because a *nested* jump reaches it every time.
        """
        effects = apply_actions((Goto("cellar"), Goto("hall")), self.state)
        self.assertEqual(effects.goto, "cellar")

    def test_actions_after_a_goto_do_not_run(self) -> None:
        effects = apply_actions(
            (Goto("cellar"), TakeItems(("brass_key",)), Message(said("Too late."))),
            self.state,
        )
        self.assertEqual(effects.goto, "cellar")
        self.assertEqual(self.state.carried_ids(), ())
        self.assertEqual(effects.messages, ())

    def test_a_goto_inside_a_guard_ends_the_whole_list(self) -> None:
        """The stop propagates outward, or the guard is decorative.

        This is the exact shape of the loader's suggested idiom, so if the stop
        did not escape the `do` list, the recommended way to write a conditional
        jump would do the wrong thing in the one case it exists for.
        """
        self.state.take("brass_key")
        effects = self.run_actions(
            [
                {
                    "when": {"has_item": "brass_key"},
                    "do": [{"goto": "cellar"}],
                },
                {"goto": "hall"},
            ]
        )
        self.assertEqual(effects.goto, "cellar")

    def test_a_guard_that_does_not_fire_lets_the_list_carry_on(self) -> None:
        """The other half of the same idiom: without the key, fall through."""
        effects = self.run_actions(
            [
                {
                    "when": {"has_item": "brass_key"},
                    "do": [{"goto": "cellar"}],
                },
                {"goto": "hall"},
            ]
        )
        self.assertEqual(effects.goto, "hall")

    def test_a_guard_that_does_not_fire_does_nothing_at_all(self) -> None:
        start = self.state.variables["lamps_lit"]
        effects = self.run_actions(
            [
                {
                    "when": {"flag": "trusted"},
                    "do": [{"take": "brass_key"}, {"inc": {"lamps_lit": 5}}],
                }
            ]
        )
        self.assertEqual(self.state.carried_ids(), ())
        self.assertEqual(self.state.variables["lamps_lit"], start)
        self.assertEqual(effects, type(effects)())

    def test_a_goto_inside_a_coin_flip_still_ends_the_list(self) -> None:
        effects = self.run_actions(
            [
                {"chance": {"p": 1.0, "then": [{"goto": "cellar"}]}},
                {"goto": "hall"},
            ]
        )
        self.assertEqual(effects.goto, "cellar")

    # -- chance -------------------------------------------------------------

    def test_certainty_always_takes_the_same_branch(self) -> None:
        effects = self.run_actions(
            [
                {
                    "chance": {
                        "p": 1.0,
                        "then": [{"message": ["It holds."]}],
                        "else": [{"message": ["It gives."]}],
                    }
                }
            ]
        )
        self.assertEqual(effects.messages, said("It holds."))

    def test_the_seed_decides_the_branch(self) -> None:
        """Same seed, same branch -- over many rolls, not just one.

        A single roll matching proves very little, so this asserts the two runs
        agree on all forty. That agreement is the entire basis for "your run can
        be reproduced"; without it the seed printed at the start of a run would
        be a decoration.
        """
        def branches(seed: int) -> list[str]:
            taken = state()
            taken.seed = seed
            taken.rng.seed(seed)
            outcomes = []
            for _ in range(40):
                effects = apply_actions(
                    parse_many([{"chance": {"p": 0.5, "then": [{"message": ["A"]}], "else": [{"message": ["B"]}]}}]),
                    taken,
                )
                outcomes.append(effects.messages[0].text)
            return outcomes

        self.assertEqual(branches(7), branches(7))

    def test_both_branches_are_reachable(self) -> None:
        """A coin that always lands the same way is not a coin.

        Checked across several seeds rather than one, so that a `Chance` wired to
        ignore its own probability cannot pass by luck.
        """
        seen = set()
        for seed in range(12):
            taken = state()
            taken.rng.seed(seed)
            effects = apply_actions(
                parse_many([{"chance": {"p": 0.5, "then": [{"message": ["A"]}], "else": [{"message": ["B"]}]}}]),
                taken,
            )
            seen.add(effects.messages[0].text)
        self.assertEqual(seen, {"A", "B"})

    # -- failing closed -----------------------------------------------------

    def test_a_verb_with_no_interpreter_raises_rather_than_doing_nothing(self) -> None:
        """Ignoring an unknown verb would be the quietest possible failure: the
        author writes an action, the file loads, and nothing ever happens."""
        with self.assertRaises(TypeError) as caught:
            apply_actions((Unhandled(),), self.state)
        self.assertIn("Unhandled", str(caught.exception))

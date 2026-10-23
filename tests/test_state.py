"""Tests for the run state.

`GameState` looks like a bag of dictionaries and is easy to "tidy up" into
something broken -- a `set` for the inventory, a slotted dataclass, a default
comparison on the random generator. Each of those changes is smaller than the
test that would notice it, so the tests are here, next to the reasons.
"""

from __future__ import annotations

import pickle
import unittest

from branchline import parse_story
from branchline.state import GameState
from tests.fixtures import minimal_story


def _as_saved_before(state: GameState, missing: str) -> GameState:
    """A state as an earlier version of the code would have pickled it.

    `__setstate__` is called directly here because that is exactly what
    unpickling does with it -- the point is to hand it a `__dict__` that
    predates a field, which is otherwise awkward to produce honestly.
    """
    saved = {key: value for key, value in state.__dict__.items() if key != missing}
    stale = GameState.__new__(GameState)
    stale.__setstate__(saved)
    return stale


class FreshStateTests(unittest.TestCase):
    def test_a_new_run_starts_at_the_start_scene(self) -> None:
        story = minimal_story()
        self.assertEqual(GameState.new(story, seed=1).scene_id, story.start)

    def test_variables_begin_at_their_declared_initial_values(self) -> None:
        story = minimal_story()
        state = GameState.new(story, seed=1)
        expected = {name: decl.initial for name, decl in story.variables.items()}
        self.assertEqual(state.variables, expected)

    def test_a_story_with_no_variables_block_still_starts(self) -> None:
        """A story that counts nothing must still be playable.

        It is the difference between iterating `story.variables` and indexing
        into something that may not be there, and the failure would land on the
        very first scene of a story that simply had nothing to count -- which is
        most stories, before they need one.
        """
        story = parse_story(
            {
                "format": "branchline.story",
                "format_version": 1,
                "start": "a",
                "meta": {"title": "Nothing to Count"},
                "endings": {"done": {"title": "Done", "epilogue": ["That is all."]}},
                "scenes": {
                    "a": {
                        "title": "A",
                        "body": ["Nothing here."],
                        "choices": [{"text": "On", "to": "b"}],
                    },
                    "b": {"title": "B", "body": ["The end."], "ending": "done"},
                },
            }
        )
        self.assertEqual(dict(story.variables), {})

        state = GameState.new(story, seed=1)

        self.assertEqual(state.variables, {})
        self.assertEqual(state.scene_id, story.start)

    def test_a_run_remembers_the_seed_that_produced_it(self) -> None:
        """So that "it did something strange" is answerable with a number."""
        state = GameState.new(minimal_story())
        self.assertIsInstance(state.seed, int)
        self.assertEqual(GameState.new(minimal_story(), seed=99).seed, 99)

    def test_the_same_seed_gives_the_same_draws(self) -> None:
        story = minimal_story()
        first = GameState.new(story, seed=4)
        second = GameState.new(story, seed=4)
        self.assertEqual(
            [first.rng.random() for _ in range(5)],
            [second.rng.random() for _ in range(5)],
        )

    def test_different_seeds_give_different_draws(self) -> None:
        story = minimal_story()
        first = GameState.new(story, seed=4)
        second = GameState.new(story, seed=5)
        self.assertNotEqual(
            [first.rng.random() for _ in range(5)],
            [second.rng.random() for _ in range(5)],
        )


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState.new(minimal_story(), seed=1)

    def test_nothing_is_carried_at_the_start(self) -> None:
        self.assertFalse(self.state.has("brass_key"))
        self.assertEqual(self.state.carried_ids(), ())

    def test_items_are_carried_in_the_order_they_were_picked_up(self) -> None:
        """The one ordering the reader eventually sees.

        W9 prints the backpack, and a `set` would print in hash order -- which
        looks like a bug in the presentation and is really a bug in the state.
        Take A then B and the answer must be A, B; not sorted, not shuffled.
        """
        self.state.take("oil_can")
        self.state.take("brass_key")
        self.assertEqual(self.state.carried_ids(), ("oil_can", "brass_key"))

    def test_taking_something_twice_does_not_reorder_it(self) -> None:
        """Idempotent, and without a special case: assigning an existing key
        keeps its position, which is the reason this is a dict and not a list."""
        self.state.take("brass_key")
        self.state.take("oil_can")
        self.state.take("brass_key")
        self.assertEqual(self.state.carried_ids(), ("brass_key", "oil_can"))

    def test_dropping_removes_it_and_dropping_nothing_is_harmless(self) -> None:
        self.state.take("brass_key")
        self.state.drop("brass_key")
        self.assertFalse(self.state.has("brass_key"))
        self.state.drop("brass_key")  # again, for free
        self.assertEqual(self.state.carried_ids(), ())


class VisitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState.new(minimal_story(), seed=1)

    def test_an_unvisited_scene_has_been_visited_zero_times(self) -> None:
        """Zero, not an error: conditions ask about scenes the reader has never
        been near, and that is an ordinary question with an ordinary answer."""
        self.assertEqual(self.state.visit_count("cellar"), 0)

    def test_visit_counts_and_returns_the_new_total(self) -> None:
        # The return value is what lets the engine report "first time" honestly.
        self.assertEqual(self.state.visit("hall"), 1)
        self.assertEqual(self.state.visit("hall"), 2)
        self.assertEqual(self.state.visit_count("hall"), 2)

    def test_scenes_are_counted_separately(self) -> None:
        self.state.visit("hall")
        self.state.visit("hall")
        self.state.visit("cellar")
        self.assertEqual(self.state.visit_count("hall"), 2)
        self.assertEqual(self.state.visit_count("cellar"), 1)


class UsedChoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState.new(minimal_story(), seed=1)

    def test_a_choice_is_unused_until_it_is_taken(self) -> None:
        self.assertFalse(self.state.used("hall", "look"))
        self.state.mark_used("hall", "look")
        self.assertTrue(self.state.used("hall", "look"))

    def test_the_same_choice_id_in_two_scenes_is_two_choices(self) -> None:
        """Choice ids are only unique *within* a scene, so "look_again" written
        by two authors in two rooms must not collide."""
        self.state.mark_used("hall", "look_again")
        self.assertTrue(self.state.used("hall", "look_again"))
        self.assertFalse(self.state.used("cellar", "look_again"))


class PickleTests(unittest.TestCase):
    """The save file is W10's job; the *shape* of the state is this round's.

    Anything that cannot survive a round trip through pickle cannot be saved, so
    these tests are really asking whether the state is genuinely self-contained:
    no closures, no generators, no cached bound methods.
    """

    def test_a_state_survives_a_round_trip(self) -> None:
        state = GameState.new(minimal_story(), seed=3)
        state.take("brass_key")
        state.visit("hall")
        state.mark_used("hall", "look")
        state.variables["stops_passed"] = 2

        # This comparison only works because `rng` is declared compare=False.
        # random.Random defines no __eq__, so it would compare by identity and
        # this assertion could never pass however correct the code was.
        self.assertEqual(pickle.loads(pickle.dumps(state)), state)

    def test_the_random_generator_resumes_where_it_left_off(self) -> None:
        """Position, not just seed.

        A save that restored the seed but not how far it had been advanced would
        replay the same rolls -- so a reader who saved and reloaded would hit the
        same coin flip again, which is a bug you only find by doing it twice.
        """
        story = minimal_story()
        advanced = GameState.new(story, seed=3)
        for _ in range(4):
            advanced.rng.random()

        restored = pickle.loads(pickle.dumps(advanced))

        fresh = GameState.new(story, seed=3)
        for _ in range(4):
            fresh.rng.random()

        self.assertEqual(restored.rng.random(), fresh.rng.random())

    def test_the_scene_id_is_mutable_after_loading(self) -> None:
        """Not a frozen dataclass, precisely so a loaded save can be moved.

        Asserted rather than assumed because `frozen=True` is the house style in
        `model.py`, and copying it here would break W10 in a way nothing else
        would notice.
        """
        state = GameState.new(minimal_story(), seed=3)
        state.scene_id = "cellar"
        self.assertEqual(pickle.loads(pickle.dumps(state)).scene_id, "cellar")

    def test_a_save_from_before_a_field_existed_still_loads(self) -> None:
        """The one thing here that can be older than the code reading it.

        A reader who left a run half-finished last week should not meet an
        AttributeError because a field was added since. This asserts the outcome
        -- an old save opens, with the new field at its default -- rather than
        the mechanism, so it survives `__setstate__` being rewritten.
        """
        story = minimal_story()
        state = GameState.new(story, seed=3)
        state.take("brass_key")
        state.visit("hall")

        old = _as_saved_before(state, missing="used_choices")

        self.assertEqual(old.used_choices, set())
        self.assertFalse(old.used("hall", "look"))
        # ...and everything the save *did* have is untouched.
        self.assertEqual(old.seed, 3)
        self.assertEqual(old.carried_ids(), ("brass_key",))
        self.assertEqual(old.visit_count("hall"), 1)

    def test_an_old_save_without_the_generator_still_reproduces_itself(self) -> None:
        """`rng` is the field no generic default can stand in for.

        Without a generator the engine cannot roll a `Chance`, so a load that
        "mostly worked" would fail later, somewhere else. And an *unseeded*
        replacement would be worse than a crash: the run would stop matching the
        seed it still reports, quietly. So it is rebuilt from the saved seed, and
        an old save draws exactly what a fresh one with that seed draws.
        """
        old = _as_saved_before(GameState.new(minimal_story(), seed=3), missing="rng")
        fresh = GameState.new(minimal_story(), seed=3)
        self.assertEqual(
            [old.rng.random() for _ in range(3)],
            [fresh.rng.random() for _ in range(3)],
        )


if __name__ == "__main__":
    unittest.main()

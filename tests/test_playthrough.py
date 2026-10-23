"""Whole playthroughs of the demo story, from the first scene to an ending.

Everything else in the suite tests a piece. These test the thing the pieces are
for: that a person can sit down, make a series of choices, and arrive somewhere.
They drive the `Engine` directly and never touch `input()`, so they run in a
second and can be trusted -- a test that needs someone at a keyboard is a test
that does not get run.

The story is read from `story/observatory.json`, the real one, not a fixture. If
a playthrough cannot get through the real story, the real story is broken.
"""

from __future__ import annotations

import pickle
import tempfile
import unittest
from pathlib import Path

from branchline import ChoiceLocked, Engine, NoSuchOption, Turn, load_story
from branchline.model import Goto, Story
from branchline.save import read_save, reconcile, write_save

STORY_PATH = Path(__file__).parent.parent / "story" / "observatory.json"


def opened(seed: int = 1) -> Engine:
    return Engine.start(demo_story(), seed=seed)


def demo_story() -> Story:
    return load_story(STORY_PATH)


def take(engine: Engine, text: str) -> Turn:
    """Take the option whose text starts with `text`, whatever number it has.

    Deliberately by text rather than by number: option numbers are renumbered
    every time the state changes -- which is the behaviour these tests are here
    to demonstrate -- so a playthrough written against numbers would be asserting
    the very thing it is trying to check.
    """
    for option in engine.options():
        if option.text.startswith(text):
            return engine.take(option.number)
    available = ", ".join(repr(o.text) for o in engine.options()) or "nothing"
    raise AssertionError(
        f"no option starting with {text!r} in {engine.state.scene_id!r}. "
        f"Available: {available}"
    )


def walk_to_the_vestibule(engine: Engine) -> Engine:
    """The one route inside: find the key, unlock the gate, step through."""
    take(engine, "Walk up to the gate")
    take(engine, "Search the flowerbed")
    take(engine, "Straighten up")
    take(engine, "Unlock the gate")
    return engine


class EndingPlaythroughTests(unittest.TestCase):
    """One playthrough per ending, played the way a reader would play it."""

    def test_the_road_back(self) -> None:
        """Branch point 2 taken the other way: the reader walks away."""
        engine = opened()
        take(engine, "Walk up to the gate")
        take(engine, "Turn around and go home")

        self.assertTrue(engine.is_over)
        self.assertEqual(engine.ending().id, "the_road_back")
        self.assertEqual(engine.ending().kind, "neutral")

    def test_you_can_also_leave_after_pushing_at_the_door(self) -> None:
        """Leaving is never taken away from the reader, at any point.

        The door refusing is not a trap -- it is a scene with a way out of it.
        """
        engine = opened()
        take(engine, "Walk up to the gate")
        take(engine, "Push at the door")
        take(engine, "Step back and look around")
        take(engine, "Turn around and go home")

        self.assertEqual(engine.ending().id, "the_road_back")

    def test_the_long_look(self) -> None:
        """Branch point 3, the telescope."""
        engine = walk_to_the_vestibule(opened())
        take(engine, "Climb to the telescope")
        take(engine, "Put your eye to it")

        self.assertTrue(engine.is_over)
        self.assertEqual(engine.ending().id, "the_long_look")
        self.assertEqual(engine.ending().kind, "ambiguous")

    def test_what_was_written(self) -> None:
        """Branch point 3, the logbook -- and the paging loop inside it."""
        engine = walk_to_the_vestibule(opened())
        take(engine, "Read the open logbook")
        take(engine, "Turn the page")
        take(engine, "Turn the page")
        take(engine, "Close the book")

        self.assertTrue(engine.is_over)
        self.assertEqual(engine.ending().id, "what_was_written")
        self.assertEqual(engine.ending().kind, "bitter")

    def test_the_reader_cannot_be_wedged(self) -> None:
        """Somewhere in every scene there is always something to press.

        Checked across the whole story rather than at one point: a scene that
        offers only hidden choices would stop the reader dead, and the loader
        refuses to accept one. A scene with no choices at all is allowed only if
        it is an ending, or if it hands its prose to the next scene and jumps --
        otherwise the reader stands in a room with no doors.
        """
        for scene_id, scene in demo_story().scenes.items():
            with self.subTest(scene=scene_id):
                if scene.ending is not None:
                    continue
                if not scene.choices:
                    self.assertTrue(
                        any(isinstance(a, Goto) for a in scene.on_enter),
                        f"{scene_id} has nothing to press and nowhere to jump",
                    )
                    continue
                self.assertTrue(
                    any(c.when is None for c in scene.choices),
                    f"{scene_id} could offer nothing at all",
                )


class RenumberingTests(unittest.TestCase):
    """The assertion this round exists for.

    The gate is one scene with one list of choices, and it numbers them
    differently depending on what is in your pocket -- because two of them are
    hidden without the key and the last one is dimmed. Same code, different
    numbers, different meanings.
    """

    def test_at_the_gate_without_the_key(self) -> None:
        engine = opened()
        take(engine, "Walk up to the gate")

        self.assertEqual(
            [o.text for o in engine.options()],
            [
                "Search the flowerbed",
                "Push at the door",
                "Unlock the gate",
                "Turn around and go home",
            ],
        )
        self.assertEqual([o.number for o in engine.options()], [1, 2, 3, 4])
        self.assertTrue(engine.options()[2].locked)

    def test_at_the_gate_with_the_key(self) -> None:
        engine = opened()
        take(engine, "Walk up to the gate")
        take(engine, "Search the flowerbed")
        take(engine, "Straighten up")

        self.assertEqual(
            [o.text for o in engine.options()],
            ["Unlock the gate", "Turn around and go home"],
        )
        self.assertEqual([o.number for o in engine.options()], [1, 2])
        self.assertFalse(engine.options()[0].locked)

    def test_the_option_that_was_number_three_is_now_number_one(self) -> None:
        engine = opened()
        take(engine, "Walk up to the gate")
        self.assertEqual(engine.options()[2].text, "Unlock the gate")

        take(engine, "Search the flowerbed")
        take(engine, "Straighten up")

        self.assertEqual(engine.options()[0].text, "Unlock the gate")

    def test_the_locked_door_refuses_before_you_have_the_key(self) -> None:
        engine = opened()
        take(engine, "Walk up to the gate")
        locked = next(o for o in engine.options() if o.locked)

        with self.assertRaises(ChoiceLocked) as caught:
            engine.take(locked.number)

        self.assertEqual(str(caught.exception), "the lock wants something small and metal")

    def test_there_is_no_key_you_can_press_to_get_in(self) -> None:
        """Not 4, not 5, not 0. With four options offered, five is not a secret
        fifth one -- and saying so is the difference between a considered game
        and one that looks like it is ignoring you."""
        engine = opened()
        take(engine, "Walk up to the gate")
        with self.assertRaises(NoSuchOption):
            engine.take(5)


class LogbookLoopTests(unittest.TestCase):
    """The demo story's one variable, and the loop it drives.

    `pages_read` is worth having because it does three separate jobs: it drives
    the status line, it selects which page of prose is shown, and it closes off
    the option to turn another page. A variable that only did the first would be
    decoration.
    """

    def setUp(self) -> None:
        engine = walk_to_the_vestibule(opened())
        take(engine, "Read the open logbook")
        self.engine = engine

    def pages_read(self) -> int:
        return self.engine.state.variables["pages_read"]

    def test_the_logbook_starts_at_the_first_page(self) -> None:
        self.assertEqual(self.pages_read(), 0)
        self.assertEqual(self.engine.view().title, "The Logbook")

    def test_turning_a_page_counts_it(self) -> None:
        take(self.engine, "Turn the page")
        self.assertEqual(self.pages_read(), 1)
        self.assertEqual(self.engine.state.scene_id, "logbook")

    def test_the_second_page_reads_differently_from_the_first(self) -> None:
        first = self.engine.view().body[0].text
        take(self.engine, "Turn the page")
        self.assertNotEqual(self.engine.view().body[0].text, first)

    def test_the_third_page_reads_differently_again(self) -> None:
        take(self.engine, "Turn the page")
        second = self.engine.view().body[0].text
        take(self.engine, "Turn the page")
        self.assertNotEqual(self.engine.view().body[0].text, second)

    def test_the_status_line_follows_the_variable(self) -> None:
        ((decl, value),) = self.engine.hud()
        self.assertEqual(decl.label, "pages read")
        self.assertEqual(value, 0)

        take(self.engine, "Turn the page")

        ((_, value),) = self.engine.hud()
        self.assertEqual(value, 1)

    def test_the_book_runs_out_of_pages(self) -> None:
        """The loop has to end, or the reader can turn pages forever."""
        take(self.engine, "Turn the page")
        take(self.engine, "Turn the page")

        self.assertNotIn("Turn the page", [o.text for o in self.engine.options()])
        self.assertIn("Close the book", [o.text for o in self.engine.options()])

    def test_the_book_can_be_closed_at_once(self) -> None:
        """Not reading on is allowed, and reaches the same ending."""
        take(self.engine, "Close the book")
        self.assertEqual(self.engine.ending().id, "what_was_written")

    def test_the_count_outlives_the_scene_that_changed_it(self) -> None:
        """The variable belongs to the run, not to the scene.

        The pages counted inside the logbook are still counted once the reader
        has left it and the story has ended. If a variable were re-initialised
        on every scene entry the status line would be a decoration, and the
        ending could not refer back to how much was read.
        """
        take(self.engine, "Turn the page")
        take(self.engine, "Close the book")

        self.assertEqual(self.engine.state.scene_id, "what_was_written")
        self.assertEqual(self.engine.state.variables["pages_read"], 1)


class DeterminismTests(unittest.TestCase):
    ROUTE = [
        "Walk up to the gate",
        "Search the flowerbed",
        "Straighten up",
        "Unlock the gate",
        "Read the open logbook",
        "Turn the page",
        "Close the book",
    ]

    def transcript(self, seed: int) -> list[str]:
        engine = Engine.start(demo_story(), seed=seed)
        seen = []
        for step in self.ROUTE:
            seen.append(
                f"{engine.state.scene_id}: "
                + " | ".join(o.text for o in engine.options())
            )
            take(engine, step)
        seen.append(f"{engine.state.scene_id}: {engine.ending().id}")
        return seen

    def test_the_same_seed_replays_the_same_run(self) -> None:
        self.assertEqual(self.transcript(1), self.transcript(1))

    def test_the_seed_makes_no_difference_at_all_to_this_story(self) -> None:
        """Which is the point, not an oversight.

        `observatory.json` contains no `chance` anywhere, so there is nothing for
        a seed to decide. That the run is bit-for-bit identical under two wildly
        different seeds is the clearest demonstration of the rule the whole
        system is built on: randomness enters through an action, or not at all.
        """
        self.assertEqual(self.transcript(1), self.transcript(999_999))

    def test_a_saved_run_finishes_the_same_way(self) -> None:
        """The seam a save file is built on, exercised on the real story rather
        than a fixture -- including across a scene whose prose depends on a
        variable."""
        engine = Engine.start(demo_story(), seed=1)
        take(engine, "Walk up to the gate")
        take(engine, "Search the flowerbed")
        take(engine, "Straighten up")
        take(engine, "Unlock the gate")
        take(engine, "Read the open logbook")
        take(engine, "Turn the page")

        saved = pickle.loads(pickle.dumps(engine.state))
        resumed = Engine.resume(engine.story, saved)

        self.assertEqual(resumed.state.variables, engine.state.variables)
        self.assertEqual(resumed.view().body[0].text, engine.view().body[0].text)
        self.assertEqual(
            [o.text for o in resumed.options()],
            [o.text for o in engine.options()],
        )


class AcrossASaveTests(unittest.TestCase):
    """Closing the terminal at the gate, and coming back to it tomorrow.

    This is the acceptance criterion for saving, stated as an assertion on the
    real story rather than on a fixture: **a reader stops at the gate, closes the
    window, comes back, and is exactly where they were.**

    The key-gated path here was built in W8 -- `enabled_when: has_item` and its
    `locked_hint` were already there. So the interesting question is not whether
    the gate works but whether it still works in a run that has been through a
    file. Everything the reader can *do* is decided from the state, so a save
    that dropped one field would not fail here loudly; it would hand back a gate
    that no longer opens, or a lock that opens with no key, and look like a story
    that had changed.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "observatory.save"

    def reload(self) -> Engine:
        """What the next run of the program does: read the file, read the story
        off disk, and fit the one to the other."""
        return Engine.resume(demo_story(), reconcile(read_save(self.path), demo_story()))

    def at_the_gate_with_the_key(self) -> Engine:
        engine = opened()
        take(engine, "Walk up to the gate")
        take(engine, "Search the flowerbed")
        take(engine, "Straighten up")
        return engine

    def test_the_key_is_still_carried_and_the_gate_still_opens(self) -> None:
        engine = self.at_the_gate_with_the_key()
        write_save(self.path, engine.state)

        resumed = self.reload()

        self.assertEqual(resumed.state.scene_id, "gate")
        self.assertTrue(resumed.state.has("brass_key"))
        lock = next(o for o in resumed.options() if o.text.startswith("Unlock"))
        self.assertFalse(lock.locked)

    def test_the_options_are_the_same_ones_in_the_same_order(self) -> None:
        """The numbers are what the reader actually presses, so a save that
        reordered them would put a different choice under the same key -- which
        is the one way a load can silently change what someone asked for."""
        engine = self.at_the_gate_with_the_key()
        write_save(self.path, engine.state)

        self.assertEqual(
            [(o.number, o.text, o.locked) for o in self.reload().options()],
            [(o.number, o.text, o.locked) for o in engine.options()],
        )

    def test_the_reader_can_still_be_wedged_into_going_home(self) -> None:
        """Leaving is always available, and a save must not take it away."""
        write_save(self.path, self.at_the_gate_with_the_key().state)

        resumed = self.reload()
        take(resumed, "Turn around and go home")

        self.assertEqual(resumed.ending().id, "the_road_back")

    def test_a_run_saved_at_the_gate_finishes_in_the_same_place(self) -> None:
        """The strongest statement of the whole round: split the playthrough in
        two at the gate, and the ending is the one the unsplit run reached.

        The route continues into the logbook on purpose -- it is the demo's one
        variable at work, read across a save, in a run that was written to disk
        and read back by a second engine.
        """
        route = ["Unlock the gate", "Read the open logbook", "Turn the page", "Close the book"]

        whole = self.at_the_gate_with_the_key()
        for step in route:
            take(whole, step)

        write_save(self.path, self.at_the_gate_with_the_key().state)
        resumed = self.reload()
        for step in route:
            take(resumed, step)

        self.assertEqual(resumed.ending().id, whole.ending().id)
        self.assertEqual(
            resumed.state.variables["pages_read"], whole.state.variables["pages_read"]
        )

    def test_the_count_is_still_where_it_was_left(self) -> None:
        """Split *after* the logbook instead, so the variable is what crosses the
        file rather than what is re-derived after it."""
        engine = self.at_the_gate_with_the_key()
        take(engine, "Unlock the gate")
        take(engine, "Read the open logbook")
        take(engine, "Turn the page")
        write_save(self.path, engine.state)

        resumed = self.reload()

        ((decl, value),) = resumed.hud()
        self.assertEqual(decl.label, "pages read")
        self.assertEqual(value, 1)
        self.assertEqual(resumed.view().title, "The Logbook")


if __name__ == "__main__":
    unittest.main()

"""Tests for the engine.

Almost everything here is about a rule that would be invisible if it broke.
Option numbering, `once`, the order messages arrive in, whether a resumed run
re-enters the scene it saved in -- none of these announce themselves when they
go wrong. They just make the game slightly, quietly incorrect.

The fixture is `engine_story.json`, which is deliberately free of `Chance` so
that "take option 2" means the same thing every time.
"""

from __future__ import annotations

import ast
import pickle
import subprocess
import sys
import unittest
from pathlib import Path

from branchline import (
    ChoiceLocked,
    Engine,
    EngineError,
    GameState,
    NoSuchOption,
    Story,
    StoryError,
    load_story,
    parse_story,
)
from branchline.engine import MAX_JUMPS_PER_TURN
from tests.fixtures import said

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "engine_story.json"
ENGINE_PATH = Path(__file__).parent.parent / "branchline" / "engine.py"


def story() -> Story:
    return load_story(FIXTURE_PATH)


def started(seed: int = 1) -> Engine:
    return Engine.start(story(), seed=seed)


def options(engine: Engine) -> list[str]:
    return [option.text for option in engine.options()]


class StartingTests(unittest.TestCase):
    def test_a_new_run_opens_at_the_start_scene(self) -> None:
        engine = started()
        self.assertEqual(engine.state.scene_id, "landing")
        self.assertEqual(engine.view().title, "The Landing")

    def test_opening_the_story_counts_the_visit(self) -> None:
        """Opening a scene is entering it, so `on_enter` has already run.

        Which is why `trips` is 1 and not 0 the first time the reader looks.
        """
        self.assertEqual(started().state.variables["trips"], 1)

    def test_a_new_run_has_an_opening(self) -> None:
        self.assertIsNotNone(started().opening)

    def test_a_resumed_run_has_no_opening(self) -> None:
        """Nothing was opened, so there is nothing to show. This is the whole
        difference between the two constructors."""
        engine = started()
        resumed = Engine.resume(engine.story, engine.state)
        self.assertIsNone(resumed.opening)

    def test_resuming_does_not_re_enter_the_scene(self) -> None:
        """The reason `Engine.start` and `Engine.resume` are separate at all.

        If constructing an engine walked into its scene, then loading a save
        would count the visit a second time, re-roll anything on entry, and show
        the prose again -- and a reader who saved and reloaded would slowly drift
        into a different run from the one they saved.
        """
        engine = started()
        engine.take(1)  # into the office
        before = pickle.dumps(engine.state)

        Engine.resume(engine.story, engine.state)

        self.assertEqual(pickle.dumps(engine.state), before)


class VariantTests(unittest.TestCase):
    """A variant is a presentation override. It must arrive with the scene."""

    def test_the_first_visit_uses_the_scene_s_own_title(self) -> None:
        view = started().view()
        self.assertEqual(view.title, "The Landing")
        self.assertEqual(view.pace, "normal")

    def test_a_later_visit_uses_the_variant(self) -> None:
        engine = started()
        engine.take(1)  # office
        engine.take(2)  # back to the landing
        view = engine.view()
        self.assertEqual(view.title, "The Landing, Again")
        self.assertEqual(view.body[0].text, "You have stood here before.")

    def test_a_variant_carries_its_pace_too(self) -> None:
        """The one that would otherwise go wrong silently.

        `pace` is read by the typewriter in W9 and by nothing else, so a variant
        that overrode the prose but not the pace would look correct in every test
        that only checks text, and read at the wrong speed forever.
        """
        engine = started()
        engine.take(1)
        engine.take(2)
        self.assertEqual(engine.view().pace, "fast")

    def test_a_variant_does_not_change_the_logic(self) -> None:
        """Presentation only. The scene behind the view is the same scene."""
        engine = started()
        first = engine.view().scene
        engine.take(1)
        engine.take(2)
        self.assertIs(engine.view().scene, first)


class OptionTests(unittest.TestCase):
    def test_options_are_numbered_from_one_without_gaps(self) -> None:
        self.assertEqual(
            [o.number for o in started().options()],
            [1, 2, 3],
        )

    def test_a_locked_option_is_still_offered(self) -> None:
        """Visible, numbered, and pressable -- it just refuses.

        Whether a locked door is even *shown* is an authorial decision, which is
        why it is the author's `enabled_when` that decides this and not Python.
        """
        locked = [o for o in started().options() if o.locked]
        self.assertEqual(len(locked), 1)
        self.assertEqual(locked[0].text, "Open the strongbox")
        self.assertEqual(locked[0].locked_hint, "the box wants something small and metal")

    def test_a_hidden_option_does_not_consume_a_number(self) -> None:
        """Numbering happens after filtering, so no key is ever a no-op.

        In a terminal a gap in the numbers reads as the program being broken --
        the reader presses 3, nothing happens, and they conclude the game is
        finished with them.
        """
        engine = started()
        engine.take(3)  # read the notice; it is a `once` choice
        engine.take(1)  # back to the landing
        self.assertEqual(options(engine), ["Go through to the office", "Open the strongbox"])

    def test_the_numbers_are_redone_each_time_you_look(self) -> None:
        """The same scene numbers its options differently as state changes.

        This is the assertion the round exists for: identical code, different
        numbers, different meanings, and the option that was 3 is now 2.
        """
        engine = started()
        self.assertEqual(engine.options()[2].text, "Read the notice")

        engine.take(3)
        engine.take(1)

        self.assertEqual(len(engine.options()), 2)
        self.assertEqual(engine.options()[1].text, "Open the strongbox")
        self.assertEqual(engine.options()[1].number, 2)

    def test_a_once_choice_comes_back_when_you_leave_and_return(self) -> None:
        """The trap `once` is easy to get wrong in a way that looks fine.

        Keyed on the wrong scene, nothing would ever match, and the choice would
        simply be offered forever. The obvious test -- take it twice in a row --
        passes anyway, because you have moved somewhere else by then. It has to
        be tested by leaving and coming back.
        """
        engine = started()
        engine.take(3)
        engine.take(1)
        self.assertNotIn("Read the notice", options(engine))

    def test_an_ended_story_offers_nothing(self) -> None:
        engine = _reach_the_dark()
        self.assertTrue(engine.is_over)
        self.assertEqual(engine.options(), ())


class TakingTests(unittest.TestCase):
    def test_taking_an_option_moves_the_reader(self) -> None:
        engine = started()
        turn = engine.take(1)
        self.assertEqual(engine.state.scene_id, "office")
        self.assertEqual(turn.entered.title, "The Office")

    def test_what_the_scene_hands_over_is_carried(self) -> None:
        engine = started()
        engine.take(1)
        self.assertEqual(
            engine.carried(),
            (engine.story.items["key"], engine.story.items["lamp"]),
        )
        self.assertEqual([item.id for item in engine.carried()], ["key", "lamp"])

    def test_a_locked_option_refuses_and_says_why(self) -> None:
        engine = started()
        with self.assertRaises(ChoiceLocked) as caught:
            engine.take(2)
        self.assertEqual(str(caught.exception), "the box wants something small and metal")

    def test_refusing_to_open_a_locked_option_changes_nothing(self) -> None:
        """A refused press is not a move. Same scene, same visit count."""
        engine = started()
        before = pickle.dumps(engine.state)
        with self.assertRaises(ChoiceLocked):
            engine.take(2)
        self.assertEqual(pickle.dumps(engine.state), before)

    def test_an_option_that_is_not_offered_cannot_be_taken(self) -> None:
        engine = started()
        with self.assertRaises(NoSuchOption) as caught:
            engine.take(9)
        self.assertIn("no option 9", str(caught.exception))

    def test_the_refusal_lists_what_is_actually_available(self) -> None:
        engine = started()
        with self.assertRaises(NoSuchOption) as caught:
            engine.take(9)
        self.assertIn("1, 2, 3", str(caught.exception))

    def test_pressing_a_key_after_the_ending_says_so(self) -> None:
        engine = _reach_the_dark()
        with self.assertRaises(NoSuchOption) as caught:
            engine.take(1)
        self.assertIn("the story has ended", str(caught.exception))

    def test_a_refusal_is_not_a_story_error(self) -> None:
        """`StoryError` means "the author's file is wrong, here is the file and
        the exact place in it". A reader pressing 9 is not that, and showing them
        a JSON pointer for it would be nonsense."""
        for error in (NoSuchOption, ChoiceLocked):
            with self.subTest(error=error.__name__):
                self.assertFalse(issubclass(error, StoryError))
                self.assertTrue(issubclass(error, EngineError))

    def test_an_option_becomes_available_when_its_condition_is_met(self) -> None:
        """The locked option is not a different option once unlocked."""
        engine = started()
        self.assertTrue(engine.options()[1].locked)

        engine.take(1)  # office: takes the key
        engine.take(2)  # back to the landing

        self.assertFalse(engine.options()[1].locked)
        self.assertEqual(engine.options()[1].text, "Open the strongbox")


class MessageOrderTests(unittest.TestCase):
    """Messages are prose the world says in reply, and their order is meaning."""

    def test_messages_from_a_chain_arrive_in_the_order_they_happened(self) -> None:
        engine = started()
        engine.take(1)  # office
        engine.take(1)  # cellar
        turn = engine.take(1)  # start down -- through two connective scenes

        self.assertEqual(
            turn.messages,
            said(
                "You go first, because there is nobody else.",  # the choice's own effects
                "The first step holds.",  # first_step's on_enter
                "The second does not.",  # second_step's on_enter
            ),
        )

    def test_a_chain_lands_where_it_ends_up_not_where_it_started(self) -> None:
        """The connective scenes are passed through, never shown.

        `entered` describes the scene the reader actually arrives at, so a
        presenter never tries to draw a scene that exists only to hand off.
        """
        engine = started()
        engine.take(1)
        engine.take(1)
        turn = engine.take(1)

        self.assertEqual(turn.entered.scene.id, "bottom")
        self.assertEqual(engine.state.scene_id, "bottom")

    def test_every_scene_in_a_chain_is_still_counted(self) -> None:
        """Passing through counts as entering.

        Which is what makes `visits` on a connective scene meaningful even
        though its prose is never read.
        """
        engine = started()
        engine.take(1)
        engine.take(1)
        engine.take(1)

        self.assertEqual(engine.state.visit_count("first_step"), 1)
        self.assertEqual(engine.state.visit_count("second_step"), 1)

    def test_a_quiet_scene_says_nothing(self) -> None:
        engine = started()
        self.assertEqual(engine.take(1).messages, ())


class EndingTests(unittest.TestCase):
    def test_a_running_story_has_no_ending(self) -> None:
        engine = started()
        self.assertFalse(engine.is_over)
        self.assertIsNone(engine.ending())

    def test_the_ending_arrives_with_its_title_and_kind(self) -> None:
        engine = _reach_the_dark()
        ending = engine.ending()
        self.assertIsNotNone(ending)
        self.assertEqual(ending.title, "The Dark")
        self.assertEqual(ending.kind, "bitter")

    def test_the_endings_are_reached_from_different_routes(self) -> None:
        """Both ending scenes exist and are arrived at, not merely declared."""
        dark = _reach_the_dark()
        box = started()
        box.take(1)  # office, which takes the key
        box.take(2)  # back to the landing
        box.take(2)  # the strongbox, now unlocked

        self.assertEqual(dark.ending().id, "the_dark")
        self.assertEqual(box.ending().id, "the_open_box")


class HudTests(unittest.TestCase):
    def test_the_hud_reports_the_declared_variables_and_their_values(self) -> None:
        engine = started()
        ((decl, value),) = engine.hud()
        self.assertEqual(decl.name, "trips")
        self.assertEqual(decl.label, "landings")
        self.assertEqual(value, 1)

    def test_the_hud_changes_as_the_story_does(self) -> None:
        """A status line that never moves is decoration. This one moves."""
        engine = started()
        engine.take(1)
        engine.take(2)
        ((_, value),) = engine.hud()
        self.assertEqual(value, 2)

    def test_values_are_handed_over_raw(self) -> None:
        """Turning `True` into "yes" is a presentation decision. The engine does
        not know how anything is displayed, including the status line."""
        self.assertIsInstance(started().hud()[0][1], int)


class RunawayJumpTests(unittest.TestCase):
    def test_a_loop_of_jumps_stops_with_a_diagnosis(self) -> None:
        """Two scenes pointing at each other would otherwise hang the program.

        An infinite loop is a mistake in the story, so the reader gets a
        diagnosis rather than a frozen terminal.
        """
        circular = parse_story(
            {
                "format": "branchline.story",
                "format_version": 1,
                "start": "a",
                "meta": {"title": "Round and Round"},
                "scenes": {
                    "a": {"title": "A", "on_enter": [{"goto": "b"}]},
                    "b": {"title": "B", "on_enter": [{"goto": "a"}]},
                },
            }
        )
        with self.assertRaises(EngineError) as caught:
            Engine.start(circular)
        message = str(caught.exception)
        self.assertIn("a -> b -> a", message)

    def test_the_limit_is_generous_enough_to_be_invisible(self) -> None:
        """A long chain of connective scenes is a legitimate way to write, so the
        limit exists to catch a loop rather than to constrain an author."""
        self.assertGreaterEqual(MAX_JUMPS_PER_TURN, 16)


class TerminalIndependenceTests(unittest.TestCase):
    """The engine does not know it is in a terminal, asserted rather than intended.

    This is not theatre. The temptation to print something from inside the engine
    -- a debug line, an easter egg, a progress dot -- arrives with W9, and this is
    the test that will still be standing when it does.
    """

    def test_the_engine_does_not_import_a_presentation_library(self) -> None:
        self.assertNotIn("rich", _imported_modules_of(ENGINE_PATH))

    def test_importing_the_engine_does_not_drag_in_a_presentation_library(self) -> None:
        self.assertEqual(
            in_a_fresh_interpreter(
                "import branchline.engine; print('rich' in sys.modules)"
            ),
            "False",
        )

    def test_importing_the_package_does_not_drag_in_a_presentation_library(self) -> None:
        """`import branchline` is what everything reaches for, including the
        loader. If the presenter were exported from `__init__.py`, then merely
        importing the package would need Rich installed -- and STORY_FORMAT.md's
        promise that you install nothing to *write* a story would be false for
        the one audience it was written for."""
        self.assertEqual(
            in_a_fresh_interpreter("import branchline; print('rich' in sys.modules)"),
            "False",
        )

    def test_the_presenter_is_not_reachable_from_the_package(self) -> None:
        self.assertEqual(
            in_a_fresh_interpreter(
                "import branchline; print('branchline.present' in sys.modules)"
            ),
            "False",
        )

    def test_the_engine_never_asks_the_terminal_for_input(self) -> None:
        tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "input"
        ]
        self.assertEqual(calls, [], "the engine read from the terminal")

    def test_the_engine_never_prints(self) -> None:
        tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
        prints = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        self.assertEqual(prints, [])

    def test_the_engine_knows_no_prompt_word(self) -> None:
        """`save`, `load` and `look` are the presenter's words, and only its.

        The engine is the thing a story is played through, and the words a
        *reader* types at the program are not part of it. `look` is the one that
        makes this worth asserting: it examines what is being carried, and
        `carried()` is already on this class, so adding it here would pass every
        other test in this file and break the line the whole design rests on.

        Whole string constants are compared rather than substrings, because this
        file's own docstrings contain the words "save" and "load" in sentences
        about saving and loading -- a search for the text would fail on prose
        that is not a prompt word at all.
        """
        tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
        constants = {
            node.value.strip().lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertEqual(constants & {"save", "load", "look"}, set())


class SaveSeamTests(unittest.TestCase):
    """W8 does not save anything. It does have to leave the door open.

    If the state cannot survive a round trip through pickle, nothing W10 builds
    can rescue it -- so the seam is proved now, while it is still cheap.
    """

    def test_a_run_can_be_put_down_and_picked_up_again(self) -> None:
        engine = started()
        engine.take(1)  # office
        engine.take(1)  # cellar

        saved = pickle.loads(pickle.dumps(engine.state))
        resumed = Engine.resume(engine.story, saved)

        self.assertEqual(resumed.state.scene_id, "cellar")
        self.assertEqual(options(resumed), options(engine))
        self.assertEqual(resumed.carried(), engine.carried())
        self.assertEqual(resumed.view().title, engine.view().title)

    def test_the_resumed_run_carries_on_to_the_same_ending(self) -> None:
        """Not just "the same screen" -- the same rest of the story."""
        engine = started()
        engine.take(1)
        engine.take(1)

        resumed = Engine.resume(engine.story, pickle.loads(pickle.dumps(engine.state)))

        self.assertEqual(resumed.take(1).messages, engine.take(1).messages)
        self.assertEqual(resumed.ending().id, engine.ending().id)

    def test_the_visit_counts_survive_the_round_trip(self) -> None:
        """Otherwise `first_time` would fire again after a load, and a reader who
        saved halfway would be told they had never been here."""
        engine = started()
        engine.take(1)
        engine.take(2)  # back to the landing, for the second time

        resumed = Engine.resume(engine.story, pickle.loads(pickle.dumps(engine.state)))

        self.assertEqual(resumed.state.visit_count("landing"), 2)
        self.assertEqual(resumed.view().title, "The Landing, Again")

    def test_a_state_built_by_hand_works_too(self) -> None:
        """`GameState` needs no engine to exist, which is what makes a save file
        a save file rather than a screenshot."""
        engine = started()
        state = GameState.new(engine.story, seed=5)
        self.assertEqual(Engine.resume(engine.story, state).state.scene_id, "landing")


def _reach_the_dark() -> Engine:
    """Play the fixture through to its bitter ending."""
    engine = started()
    engine.take(1)  # office
    engine.take(1)  # cellar
    engine.take(1)  # start down the stair
    return engine


REPO_ROOT = Path(__file__).parent.parent


def in_a_fresh_interpreter(source: str) -> str:
    """Run `source` in a new Python, with the repo importable, and return its output.

    **Why a subprocess, for a question this small.** Asking "is `rich` in
    `sys.modules`?" inside the running suite answers a different question from the
    one meant: it answers whether anything that imports Rich has already run. It
    passes today because `test_engine` sorts before `test_present` -- so the day a
    file sorts between them it would start failing, and what it would be
    reporting is the alphabetical order of the test directory. A new interpreter
    has no history, so the only thing left for it to answer is what importing
    this module actually pulls in.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {REPO_ROOT.as_posix()!r})\n{source}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:  # pragma: no cover - only when the repo is broken
        raise AssertionError(f"the interpreter could not run it:\n{result.stderr}")
    return result.stdout.strip()


def _imported_modules_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


if __name__ == "__main__":
    unittest.main()

"""Tests for the linter: what the story declares that no reader will ever see.

The rules are about the *shape of the whole story* rather than about one file
location, so these tests are too: they mutate a fresh document, parse it, and ask
what is now unreachable. Nothing here plays the story, with one deliberate
exception -- the regression test at the bottom of `OrphanSceneTests`, which
insists that a scene the linter calls reachable is one a reader can actually walk
into. A check that cries wolf about a working room is worse than no check.

`StoryTestCase` is not used here. Its assertions are about what an author is told
when their file is *rejected*, and nothing in this module is rejected -- a story
with a finding loads and plays exactly like a story without one.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from branchline import Engine, load_story, parse_story
from branchline.lint import KINDS, PROBLEMS, Finding, find_unseen
from tests.fixtures import minimal_document

DEMO = Path(__file__).parent.parent / "story" / "observatory.json"
SAMPLE = Path(__file__).parent.parent / "story" / "sample.json"

#: The fixture's own known findings, written down rather than assumed.
#:
#: `tests/fixtures/minimal_story.json` declares a scene called `locked_door` that
#: nothing points at, and `fall` hangs off it -- so the second orphan is a
#: consequence of the first rather than a second mistake. The loader has never had
#: an opinion about orphans and the fixture's job is to exercise the schema rather
#: than to be a good story, so both are left exactly as they are. Recording them
#: here means every assertion below reads against a baseline that is stated
#: instead of implied.
BASELINE = (
    Finding("scene", "locked_door"),
    Finding("scene", "fall"),
)


def unseen(document: dict) -> tuple[Finding, ...]:
    return find_unseen(parse_story(document))


def take(engine: Engine, text: str):
    """Take the option with this text, whatever number it currently has.

    By text rather than by number, because option numbers are renumbered every
    time the state changes -- which is the behaviour `test_playthrough.py` exists
    to demonstrate, and not something a test about the linter should depend on.
    """
    for option in engine.options():
        if option.text == text:
            return engine.take(option.number)
    raise AssertionError(f"no option {text!r}; offered: {[o.text for o in engine.options()]}")


class FindingTests(unittest.TestCase):
    def test_a_finding_names_a_kind_and_a_declaration(self) -> None:
        self.assertEqual(Finding("item", "tin_whistle").name, "tin_whistle")

    def test_every_kind_can_explain_itself(self) -> None:
        """The guard against a fifth rule arriving with no sentence to report it.

        The same shape as `test_palette.py` failing when a register has no look:
        without this, adding a rule and forgetting its explanation would raise a
        `KeyError` in the middle of somebody's `--check`.
        """
        self.assertEqual(set(KINDS), set(PROBLEMS))

    def test_the_explanation_says_why_it_matters(self) -> None:
        self.assertIn("never read", Finding("scene", "cellar").problem)
        self.assertIn("never be looked at", Finding("item", "key").problem)


class OrphanSceneTests(unittest.TestCase):
    def test_the_fixture_has_exactly_the_orphans_this_module_expects(self) -> None:
        self.assertEqual(unseen(minimal_document()), BASELINE)

    def test_a_scene_nothing_links_to_is_reported(self) -> None:
        document = minimal_document()
        document["scenes"]["attic"] = {
            "title": "The Attic",
            "body": ["Dust, and a skylight."],
            "choices": [{"text": "Back down", "to": "hall"}],
        }

        self.assertIn(Finding("scene", "attic"), unseen(document))

    def test_one_forgotten_link_makes_the_fixture_clean(self) -> None:
        """The fixture is one line away from passing, and that is the point.

        `locked_door` is not damaged and `fall` is not damaged -- they are a
        working room and a working fall, and nobody ever walks into either. What
        the linter reports is a forgotten link rather than a broken story, which
        is exactly the kind of fault that cannot be found by playing: the game
        runs perfectly, and it runs without them.
        """
        document = minimal_document()
        document["scenes"]["hall"]["choices"].append(
            {"text": "Try the locked door", "to": "locked_door"}
        )

        self.assertEqual(unseen(document), ())

    def test_a_scene_reached_only_through_a_jump_on_entry_is_not_reported(self) -> None:
        """A connective scene with no body, no choices and no ending.

        `landing` exists only to hand the reader onward, which it does with a
        `goto` in its `on_enter` -- the idiom the loader recommends. `attic` is
        reachable *only* that way, so this is the test that the walk follows
        jumps out of an action list and not merely out of a choice.
        """
        document = minimal_document()
        document["scenes"]["landing"] = {
            "title": "The Landing",
            "on_enter": [{"goto": "attic"}],
        }
        document["scenes"]["attic"] = {
            "title": "The Attic",
            "body": ["Dust, and a skylight."],
            "choices": [{"text": "Back down", "to": "hall"}],
        }
        document["scenes"]["hall"]["choices"].append(
            {"text": "Up the stair", "to": "landing"}
        )

        findings = unseen(document)

        self.assertNotIn(Finding("scene", "landing"), findings)
        self.assertNotIn(Finding("scene", "attic"), findings)

    def test_a_scene_behind_a_conditional_choice_is_still_reachable(self) -> None:
        """Conditions are not evaluated, deliberately.

        `tide_table` is reachable only through a choice gated on a variable and a
        visit count. Asking whether anyone *will* arrive there needs a solver;
        asking whether anyone *could* is the question a dead-link check asks, and
        it is the one this answers.
        """
        self.assertNotIn(Finding("scene", "tide_table"), unseen(minimal_document()))

    def test_a_scene_reached_only_through_a_choices_effects_is_not_reported(self) -> None:
        """**The regression this module was written against.**

        A choice has an ordinary `to`, and it may also carry a `goto` inside its
        `effects`. `Engine.take` takes the second when it is there, because it is
        the more specific instruction -- so `attic` below is a room a reader can
        walk into. `reached_scenes()` used to follow only `to`, which made it
        report this scene as orphaned: the linter accusing an author of a fault
        that is not there.

        The second half of the test is the part that matters. Asserting the
        linter agrees with itself would prove nothing; asserting it agrees with
        the *engine* is what makes reachable mean reachable.
        """
        document = minimal_document()
        document["scenes"]["attic"] = {
            "title": "The Attic",
            "body": ["Dust, and a skylight."],
            "choices": [{"text": "Back down", "to": "hall"}],
        }
        document["scenes"]["hall"]["choices"].append(
            {
                "text": "Climb the ladder",
                "to": "workshop",
                "effects": [{"goto": "attic"}],
            }
        )

        self.assertNotIn(Finding("scene", "attic"), unseen(document))

        engine = Engine.start(parse_story(document), seed=1)
        take(engine, "Climb the ladder")
        self.assertEqual(engine.state.scene_id, "attic")


class UnusedEndingTests(unittest.TestCase):
    def test_an_ending_no_scene_ends_at_is_reported(self) -> None:
        document = minimal_document()
        document["endings"]["the_quiet"] = {
            "title": "The Quiet",
            "kind": "neutral",
            "epilogue": ["Nothing, for a while."],
        }

        self.assertIn(Finding("ending", "the_quiet"), unseen(document))

    def test_an_ending_stops_being_reported_when_a_scene_ends_there(self) -> None:
        document = minimal_document()
        document["scenes"]["lamps"]["ending"] = "steady_light"

        self.assertIn(Finding("ending", "dark_tide"), unseen(document))

    def test_both_of_the_fixtures_endings_are_used(self) -> None:
        findings = unseen(minimal_document())
        self.assertNotIn(Finding("ending", "steady_light"), findings)
        self.assertNotIn(Finding("ending", "dark_tide"), findings)


class UnreadItemTests(unittest.TestCase):
    """The rule that only means anything because the reader can `look`."""

    def test_an_item_nothing_takes_is_reported(self) -> None:
        document = minimal_document()
        document["items"]["tin_whistle"] = {
            "name": "Tin Whistle",
            "description": "Dented along one edge.",
        }

        self.assertIn(Finding("item", "tin_whistle"), unseen(document))

    def test_an_item_becomes_readable_by_being_taken(self) -> None:
        document = minimal_document()
        document["items"]["tin_whistle"] = {
            "name": "Tin Whistle",
            "description": "Dented along one edge.",
        }
        document["scenes"]["workshop"]["on_enter"] = [{"take": "tin_whistle"}]

        self.assertNotIn(Finding("item", "tin_whistle"), unseen(document))

    def test_an_item_taken_inside_a_coin_is_not_reported(self) -> None:
        """`oil_can` is taken only on one branch of a `chance` in the cellar.

        A walk that stopped at the surface of an action list would miss it, and
        would tell an author their oil can can never be seen -- while they are
        holding it. Recursion is not a refinement here; it is the difference
        between the report being useful and being wrong.
        """
        self.assertNotIn(Finding("item", "oil_can"), unseen(minimal_document()))

    def test_an_item_taken_inside_a_guard_is_not_reported(self) -> None:
        document = minimal_document()
        document["scenes"]["workshop"]["on_enter"] = [
            {"when": {"flag": "trusted"}, "do": [{"take": "brass_key"}]}
        ]

        self.assertNotIn(Finding("item", "brass_key"), unseen(document))

    def test_an_item_that_is_only_asked_about_is_still_reported(self) -> None:
        """Being named in a condition is not being obtained.

        The hall's key-gated door asks `has_item: brass_key`, so the item is
        referenced all over the story -- and if nothing ever hands it over, that
        door can never open and the description can never be read. A rule that
        looked for the item's *name* anywhere would miss exactly this.
        """
        document = minimal_document()
        document["scenes"]["workshop"]["on_enter"] = []

        self.assertIn(Finding("item", "brass_key"), unseen(document))


class UnreadVariableTests(unittest.TestCase):
    def test_a_variable_nothing_reads_is_reported(self) -> None:
        document = minimal_document()
        document["variables"]["warned"] = {"type": "bool", "initial": False}

        self.assertIn(Finding("variable", "warned"), unseen(document))

    def test_a_variable_on_the_status_line_is_exempt(self) -> None:
        """The reader watches it change, so it takes effect however little reads it."""
        document = minimal_document()
        document["variables"]["steps"] = {
            "type": "int",
            "initial": 0,
            "label": "steps",
            "hud": True,
        }

        self.assertNotIn(Finding("variable", "steps"), unseen(document))

    def test_hud_is_the_only_difference(self) -> None:
        """Same variable, same story, one key added -- and the report changes.

        Written as a pair so the exemption is shown to be exactly `hud` rather
        than some other thing the two documents differ by.
        """
        document = minimal_document()
        document["variables"]["steps"] = {"type": "int", "initial": 0}
        self.assertIn(Finding("variable", "steps"), unseen(document))

        document["variables"]["steps"]["label"] = "steps"
        document["variables"]["steps"]["hud"] = True
        self.assertNotIn(Finding("variable", "steps"), unseen(document))

    def test_being_written_is_not_being_read(self) -> None:
        document = minimal_document()
        document["variables"]["warned"] = {"type": "bool", "initial": False}
        document["scenes"]["workshop"]["on_enter"] = [
            {"set": {"warned": True}},
            {"inc": {"lamps_lit": 1}},
        ]

        self.assertIn(Finding("variable", "warned"), unseen(document))

    def test_a_variable_read_deep_inside_a_condition_is_read(self) -> None:
        """`all` > `any` > `not` > the variable, four levels down.

        A reference buried in a tree is read just as surely as one at the top,
        and reporting a live variable dead would be the one fault that makes
        this module worse than not having it.
        """
        document = minimal_document()
        document["variables"]["warned"] = {"type": "bool", "initial": False}
        document["scenes"]["tide_table"]["variants"] = [
            {
                "when": {"all": [{"any": [{"not": {"flag": "warned"}}]}]},
                "body": ["The margin again, and the same name in it."],
            }
        ]

        self.assertNotIn(Finding("variable", "warned"), unseen(document))

    def test_the_fixtures_own_variables_are_all_read(self) -> None:
        findings = unseen(minimal_document())
        for name in ("lamps_lit", "trusted", "mood"):
            with self.subTest(variable=name):
                self.assertNotIn(Finding("variable", name), findings)


class OrderingTests(unittest.TestCase):
    def test_findings_are_grouped_by_rule_in_a_fixed_order(self) -> None:
        """Scene, ending, item, variable -- and stable within each group.

        A report that reordered itself between runs would be one more thing to
        re-read rather than recognise, and the author is looking for their own
        declaration order in it.
        """
        document = minimal_document()
        document["scenes"]["attic"] = {
            "title": "The Attic",
            "body": ["Dust."],
            "choices": [{"text": "Down", "to": "hall"}],
        }
        document["endings"]["the_quiet"] = {
            "title": "The Quiet",
            "kind": "neutral",
            "epilogue": ["Nothing."],
        }
        document["items"]["tin_whistle"] = {"name": "Tin Whistle", "description": "Dented."}
        document["variables"]["warned"] = {"type": "bool", "initial": False}

        self.assertEqual(
            [finding.kind for finding in unseen(document)],
            ["scene", "scene", "scene", "ending", "item", "variable"],
        )

    def test_orphans_come_back_in_the_order_the_author_declared_them(self) -> None:
        document = minimal_document()
        document["scenes"]["attic"] = {
            "title": "The Attic",
            "body": ["Dust."],
            "choices": [{"text": "Down", "to": "hall"}],
        }

        names = [f.name for f in unseen(document) if f.kind == "scene"]

        self.assertEqual(names, ["locked_door", "fall", "attic"])


class TheRealStoriesTests(unittest.TestCase):
    """The claim `--check` makes about the two files that ship with the project."""

    def test_the_demo_story_is_clean(self) -> None:
        self.assertEqual(find_unseen(load_story(DEMO)), ())

    def test_the_sample_story_is_clean(self) -> None:
        self.assertEqual(find_unseen(load_story(SAMPLE)), ())

    def test_a_clean_story_really_was_checked(self) -> None:
        """A linter that returned nothing would pass the two above.

        So the demo is shown to have everything the rules look for: scenes that
        are all reachable, endings that are all used, an item that is taken, and
        variables that are read or displayed. The first of those is the one the
        loader never checked, and the third only matters because of `look`.
        """
        story = load_story(DEMO)

        self.assertEqual(story.unreached_scenes(), set())
        self.assertTrue(story.items)
        self.assertTrue(story.endings)
        self.assertTrue(story.variables)


if __name__ == "__main__":
    unittest.main()

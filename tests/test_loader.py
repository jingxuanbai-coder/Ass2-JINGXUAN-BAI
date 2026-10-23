"""Tests for reading a story file.

The happy-path tests check that the fixture arrives intact. The rest check that a
broken file produces a *diagnosis* -- a message naming the file, the exact place,
and what is wrong -- because that is the claim this whole project rests on: that
someone who does not program can edit the story safely.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from branchline import StoryError, load_story, parse_story
from branchline.errors import Pointer
from branchline.model import (
    AllOf,
    AnyOf,
    Chance,
    Conditional,
    DropItems,
    Ending,
    FirstTime,
    FlagSet,
    Goto,
    HasItem,
    IncrementVars,
    Message,
    Negate,
    Paragraph,
    SetVars,
    TakeItems,
    VarAtLeast,
    VarIs,
    VisitCount,
    Visited,
)
from tests.fixtures import (
    MINIMAL_PATH,
    StoryTestCase,
    clone,
    minimal_document,
    minimal_story,
    said,
)

EXPECTED_CONDITIONS = {
    AllOf,
    AnyOf,
    Negate,
    HasItem,
    FlagSet,
    VarIs,
    VarAtLeast,
    Visited,
    VisitCount,
    FirstTime,
}
EXPECTED_ACTIONS = {
    SetVars,
    IncrementVars,
    TakeItems,
    DropItems,
    Goto,
    Message,
    Conditional,
    Chance,
}


def schema_surface(story):
    """Every kind of condition and action the loaded story actually uses."""
    conditions: set[type] = set()
    actions: set[type] = set()

    def walk_conditions(node) -> None:
        if node is None:
            return
        conditions.add(type(node))
        if isinstance(node, (AllOf, AnyOf)):
            for child in node.children:
                walk_conditions(child)
        elif isinstance(node, Negate):
            walk_conditions(node.child)

    def walk_actions(items) -> None:
        for item in items:
            actions.add(type(item))
            if isinstance(item, Conditional):
                walk_conditions(item.condition)
                walk_actions(item.actions)
            elif isinstance(item, Chance):
                walk_actions(item.then)
                walk_actions(item.otherwise)

    for scene in story.scenes.values():
        for variant in scene.variants:
            walk_conditions(variant.when)
        for choice in scene.choices:
            walk_conditions(choice.when)
            walk_conditions(choice.enabled_when)
            walk_actions(choice.effects)
        walk_actions(scene.on_enter)

    return conditions, actions


class HappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.story = minimal_story()

    def test_top_level_facts(self) -> None:
        self.assertEqual(self.story.meta.title, "Fixture")
        self.assertEqual(self.story.meta.author, "the test suite")
        self.assertEqual(self.story.meta.subtitle, "a story that exists only to be loaded")
        self.assertEqual(self.story.start, "hall")
        self.assertEqual(self.story.format_version, 1)
        self.assertEqual(len(self.story.scenes), 8)
        self.assertEqual(len(self.story.items), 2)
        self.assertEqual(len(self.story.endings), 2)
        self.assertEqual(len(self.story.variables), 3)
        self.assertEqual(len(self.story.meta.title_card), 1)

    def test_parse_story_needs_no_file(self) -> None:
        self.assertIsNone(self.story.source)

    def test_scene_lookup(self) -> None:
        hall = self.story.scene("hall")
        self.assertEqual(hall.title, "The Hall")
        self.assertEqual(hall.pace, "slow")
        self.assertEqual(len(hall.choices), 4)
        self.assertEqual(len(hall.body), 2)
        self.assertEqual(len(hall.variants), 1)
        self.assertEqual(len(hall.on_enter), 2)
        self.assertIsNone(hall.ending)

    def test_paragraph_shorthand_and_full_form(self) -> None:
        body = self.story.scene("hall").body
        self.assertEqual(body[0], Paragraph("A draught moves under the door."))
        self.assertEqual(body[1].style, "aside")
        self.assertEqual(body[1].pace, "fast")
        self.assertEqual(body[1].text, "someone has been here tonight.")

    def test_the_two_kinds_of_gate_are_kept_apart(self) -> None:
        choices = self.story.scene("hall").choices
        # `when` decides whether the option exists at all.
        self.assertIsNotNone(choices[2].when)
        self.assertIsNone(choices[2].enabled_when)
        # `enabled_when` decides whether it can be taken, and carries a hint.
        self.assertIsNotNone(choices[1].enabled_when)
        self.assertEqual(choices[1].locked_hint, "you would need something small and metal")
        self.assertTrue(choices[1].once)
        self.assertEqual(choices[1].id, "unlock")

    def test_choice_effects_are_typed(self) -> None:
        unlock = self.story.scene("hall").choices[1]
        self.assertEqual(len(unlock.effects), 1)
        self.assertIsInstance(unlock.effects[0], SetVars)
        self.assertEqual(unlock.effects[0].values, {"trusted": True})

    def test_on_enter_mixes_guarded_actions_and_chance(self) -> None:
        guarded, flip = self.story.scene("hall").on_enter
        self.assertIsInstance(guarded, Conditional)
        self.assertIsInstance(guarded.condition, FirstTime)
        self.assertIsInstance(guarded.actions[0], IncrementVars)
        self.assertIsInstance(flip, Chance)
        self.assertEqual(flip.probability, 0.5)
        self.assertEqual(flip.otherwise, (Message(said("Nothing moves.")),))

    def test_a_message_carries_a_register_through_the_loader(self) -> None:
        """The fixture's cellar hides grit from you, and says so as an aside.

        Both forms are in the fixture on purpose. A message written as bare text
        is what every story predating registers uses, and it has to keep loading;
        the object form is what an author reaches for once they want one. If the
        fixture only had the first, a schema that dropped the second would still
        pass everything here.
        """
        cellar = self.story.scene("cellar")
        flip = cellar.on_enter[0]
        elsewhere = flip.otherwise[0]
        self.assertIsInstance(elsewhere, Message)
        self.assertEqual(
            elsewhere.paragraphs,
            (Paragraph("Only grit behind the stair.", style="aside", pace="fast"),),
        )

    def test_a_scene_can_exist_only_to_fall_through(self) -> None:
        """A corridor, not a room: no prose, no choices, just the jump.

        The prose lives in the jump as a message rather than in a `body`,
        because a scene that always jumps away is never shown -- see the
        connective-scene rules in `ConnectiveSceneTests`.
        """
        fall = self.story.scene("fall")
        self.assertEqual(fall.choices, ())
        self.assertIsNone(fall.ending)
        self.assertEqual(fall.body, ())
        self.assertEqual(
            fall.on_enter,
            (Message(said("The stair gives way.")), Goto("cellar")),
        )

    def test_endings_keep_their_kind_and_epilogue(self) -> None:
        steady = self.story.endings["steady_light"]
        self.assertIsInstance(steady, Ending)
        self.assertEqual(steady.kind, "warm")
        self.assertEqual(steady.title, "Steady Light")
        self.assertIsInstance(steady.epilogue[0], Paragraph)
        self.assertEqual(self.story.endings["dark_tide"].kind, "bitter")

    def test_items_carry_name_description_and_art(self) -> None:
        key = self.story.items["brass_key"]
        self.assertEqual(key.name, "Small Brass Key")
        self.assertEqual(key.art, "( o )")
        self.assertEqual(self.story.items["oil_can"].art, None)

    def test_hud_variables_come_back_in_declaration_order(self) -> None:
        hud = self.story.hud_variables()
        self.assertEqual([decl.name for decl in hud], ["lamps_lit"])
        self.assertEqual(hud[0].label, "lamps lit")

    def test_the_fixture_exercises_every_kind_of_condition_and_action(self) -> None:
        """The scope for this project is fixed: three branch points, gated paths,
        items, endings, random events. If the schema cannot *say* one of those
        things, that is a schema bug -- and this is where it shows up, against
        the fixture, rather than during the writing of an actual story.
        """
        conditions, actions = schema_surface(self.story)
        self.assertEqual(conditions, EXPECTED_CONDITIONS)
        self.assertEqual(actions, EXPECTED_ACTIONS)

    def test_underscore_keys_are_ignored_everywhere(self) -> None:
        document = minimal_document()
        document["_a_comment"] = "ignored"
        document["scenes"]["hall"]["_another"] = ["also ignored"]
        document["scenes"]["hall"]["choices"][0]["_why"] = "so authors can annotate"
        self.assertEqual(parse_story(document).start, "hall")

    def test_annotations_survive_at_every_depth(self) -> None:
        document = minimal_document()
        for scene in document["scenes"].values():
            scene["_note"] = "annotation"
        self.assertEqual(len(parse_story(document).scenes), 8)


class FileLevelFailures(StoryTestCase):
    """Failures that live in the text, not the parsed document."""

    def test_missing_file(self) -> None:
        with self.assertRaises(StoryError) as caught:
            load_story(Path("no-such-story-here.json"))
        self.assertIn("no story file", str(caught.exception))

    def test_directory_instead_of_file(self) -> None:
        with self.assertRaises(StoryError) as caught:
            load_story(MINIMAL_PATH.parent)
        self.assertIn("folder", str(caught.exception))

    def test_malformed_json_is_located(self) -> None:
        error = self.assertRejectsText(
            '{\n  "format": "branchline.story",\n  "format_version": 1,\n}\n',
            mentions=("not valid JSON", "line "),
        )
        # Which line CPython blames for a trailing comma changed in 3.13, so the
        # contract tested here is that a position inside the file is named --
        # not which position a particular interpreter picks.
        self.assertIsNotNone(error.line)
        self.assertIsNotNone(error.column)
        self.assertIn(f"line {error.line}", str(error))
        self.assertTrue(1 <= error.line <= 4, f"line {error.line} is outside the file")

    def test_duplicate_keys_are_caught(self) -> None:
        """json keeps only the last of a duplicated key, so pasting a scene in
        twice would silently discard the earlier copy."""
        self.assertRejectsText(
            """
            {
              "format": "branchline.story",
              "format_version": 1,
              "start": "a",
              "meta": {"title": "T"},
              "scenes": {
                "a": {"title": "First", "choices": [{"text": "on", "to": "b"}]},
                "a": {"title": "Second", "choices": [{"text": "on", "to": "b"}]},
                "b": {"title": "B", "choices": [{"text": "back", "to": "a"}]}
              }
            }
            """,
            mentions=('"a" appears twice', "silently"),
        )

    def test_exotic_numbers_are_rejected(self) -> None:
        self.assertRejectsText(
            """
            {
              "format": "branchline.story",
              "format_version": 1,
              "start": "a",
              "meta": {"title": "T"},
              "variables": {"n": {"type": "int", "initial": NaN}},
              "scenes": {"a": {"title": "A", "choices": [{"text": "on", "to": "a"}]}}
            }
            """,
            mentions=("NaN", "not valid JSON"),
        )

    def test_a_story_file_is_read_as_utf8_even_with_a_bom(self) -> None:
        """Notepad writes a byte order mark; plain utf-8 reading would mangle the
        first key of the file and report a baffling error."""
        text = minimal_document()
        text["meta"]["title"] = "Curly “quotes” and an em—dash"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.json"
            path.write_text(json.dumps(text), encoding="utf-8-sig")
            self.assertEqual(load_story(path).meta.title, "Curly “quotes” and an em—dash")


class FormatTests(StoryTestCase):
    def test_missing_format(self) -> None:
        document = clone(minimal_document())
        document.pop("format")
        self.assertRejects(document, mentions=("does not say what it is", "branchline.story"))

    def test_wrong_format(self) -> None:
        document = clone(minimal_document())
        document["format"] = "twine.archive"
        self.assertRejects(
            document, mentions=("not a BranchLine story",), pointer="format"
        )

    def test_future_format_version(self) -> None:
        document = clone(minimal_document())
        document["format_version"] = 99
        self.assertRejects(
            document, mentions=("format version 99",), pointer="format_version"
        )

    def test_missing_format_version(self) -> None:
        document = clone(minimal_document())
        document.pop("format_version")
        self.assertRejects(document, mentions=("which version",))

    def test_missing_meta(self) -> None:
        document = clone(minimal_document())
        document.pop("meta")
        self.assertRejects(document, mentions=('"meta"',))

    def test_missing_start(self) -> None:
        document = clone(minimal_document())
        document.pop("start")
        self.assertRejects(document, mentions=('"start"',))

    def test_start_points_at_no_scene(self) -> None:
        document = clone(minimal_document())
        document["start"] = "attic"
        self.assertRejects(document, mentions=("attic",), pointer="start")

    def test_story_with_no_scenes(self) -> None:
        document = clone(minimal_document())
        document["scenes"] = {}
        self.assertRejects(document, mentions=("no scenes",), pointer="scenes")


class LinkTests(StoryTestCase):
    def test_dead_link_names_the_exact_choice(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][0]["to"] = "nowhere"
        self.assertRejects(
            document,
            mentions=("nowhere", "not a scene"),
            pointer="scenes.hall.choices[0].to",
        )

    def test_dead_link_is_corrected_by_suggestion(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][0]["to"] = "workshp"
        error = self.assertRejects(document, mentions=("workshp",))
        self.assertIn("workshop", str(error))

    def test_goto_to_no_scene(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [{"goto": "cellars"}]
        self.assertRejects(
            document, mentions=("cellars",), pointer="scenes.fall.on_enter[0].goto"
        )

    def test_ending_not_declared(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["lit"]["ending"] = "steady_lite"
        self.assertRejects(
            document, mentions=("steady_lite",), pointer="scenes.lit.ending"
        )

    def test_dead_end(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["workshop"].pop("choices")
        self.assertRejects(
            document,
            mentions=("dead end",),
            pointer="scenes.workshop",
        )

    def test_a_scene_that_always_jumps_away_cannot_offer_choices(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["locked_door"]["on_enter"] = [{"goto": "cellar"}]
        self.assertRejects(
            document,
            mentions=("can never be reached",),
            pointer="scenes.locked_door.on_enter",
        )

    def test_a_scene_cannot_both_end_and_offer_choices(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["lit"]["choices"] = [{"text": "more", "to": "hall"}]
        self.assertRejects(
            document, mentions=("both an", "ending", "choices"), pointer="scenes.lit"
        )


class VocabularyTests(StoryTestCase):
    def test_unknown_item_on_a_gate(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["cellar"]["choices"][0]["enabled_when"] = {"has_item": "oilcan"}
        error = self.assertRejects(
            document,
            mentions=("oilcan", "not an item"),
            pointer="scenes.cellar.choices[0].enabled_when.has_item",
        )
        self.assertIn("oil_can", str(error))

    def test_unknown_item_being_given(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["workshop"]["on_enter"] = [{"take": "brasskey"}]
        self.assertRejects(
            document, mentions=("brasskey",), pointer="scenes.workshop.on_enter[0].take"
        )

    def test_unknown_variable_being_written(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["on_enter"][0]["do"] = [{"inc": {"lamps_litt": 1}}]
        self.assertRejects(
            document,
            mentions=("lamps_litt", "not a variable"),
            pointer="scenes.hall.on_enter[0].do[0].inc.lamps_litt",
        )

    def test_unknown_variable_being_read(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][3]["when"] = {"flag": "trustd"}
        self.assertRejects(document, mentions=("trustd",))

    def test_unknown_scene_in_a_visited_condition(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][2]["when"] = {
            "all": [{"not": {"visited": "tide_tabl"}}]
        }
        self.assertRejects(
            document,
            mentions=("tide_tabl",),
            pointer="scenes.hall.choices[2].when.all[0].not.visited",
        )


class TypoTests(StoryTestCase):
    def test_a_misspelled_key_is_caught_and_corrected(self) -> None:
        document = clone(minimal_document())
        scene = document["scenes"]["hall"]
        scene["choises"] = scene.pop("choices")
        self.assertRejects(
            document,
            mentions=("choises", 'did you mean "choices"'),
            pointer="scenes.hall.choises",
        )

    def test_a_misspelled_operator_is_caught_and_corrected(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["cellar"]["choices"][0]["enabled_when"] = {"has_itm": "oil_can"}
        self.assertRejects(
            document,
            mentions=("has_itm", 'did you mean "has_item"'),
            pointer="scenes.cellar.choices[0].enabled_when.has_itm",
        )

    def test_a_misspelled_action_verb_is_caught(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["workshop"]["on_enter"] = [{"tkae": "brass_key"}]
        self.assertRejects(
            document, mentions=("tkae", 'did you mean "take"'), pointer="scenes.workshop.on_enter[0].tkae"
        )

    def test_unknown_top_level_key(self) -> None:
        document = clone(minimal_document())
        document["scene"] = document.pop("scenes")
        self.assertRejects(document, mentions=("scene", 'did you mean "scenes"'))

    def test_a_typo_deep_in_the_file_still_lands_on_the_right_paragraph(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["body"][1]["stile"] = "aside"
        self.assertRejects(
            document, mentions=("stile",), pointer="scenes.hall.body[1].stile"
        )


class ChoiceTests(StoryTestCase):
    def test_more_than_nine_choices(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"] = [
            {"text": f"option {i}", "to": "workshop"} for i in range(10)
        ]
        self.assertRejects(
            document,
            mentions=("10 choices", "nine"),
            pointer="scenes.hall.choices",
        )

    def test_nine_choices_are_allowed(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"] = [
            {"text": f"option {i}", "to": "workshop"} for i in range(9)
        ]
        self.assertEqual(len(parse_story(document).scene("hall").choices), 9)

    def test_once_without_an_id(self) -> None:
        """Without an id the engine would remember a choice by its position, and
        inserting a new choice above it would move that memory to the wrong one."""
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][1].pop("id")
        self.assertRejects(
            document,
            mentions=("once", "id", "position"),
            pointer="scenes.hall.choices[1]",
        )

    def test_once_with_an_id_is_fine(self) -> None:
        self.assertTrue(minimal_story().scene("hall").choices[1].once)

    def test_duplicate_choice_ids_within_a_scene(self) -> None:
        document = clone(minimal_document())
        fourth = document["scenes"]["hall"]["choices"][3]
        fourth["id"] = "unlock"
        fourth["once"] = True
        self.assertRejects(
            document, mentions=("unlock", "twice"), pointer="scenes.hall.choices"
        )

    def test_the_same_id_in_a_different_scene_is_fine(self) -> None:
        document = clone(minimal_document())
        for scene_id in ("workshop", "tide_table"):
            document["scenes"][scene_id]["choices"][0]["id"] = "back"
            document["scenes"][scene_id]["choices"][0]["once"] = True
        self.assertEqual(len(parse_story(document).scenes), 8)

    def test_choice_without_text(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][0].pop("text")
        self.assertRejects(document, mentions=('"text"',), pointer="scenes.hall.choices[0]")

    def test_choice_without_a_destination(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][0].pop("to")
        self.assertRejects(document, mentions=('"to"',), pointer="scenes.hall.choices[0]")


class ConnectiveSceneTests(StoryTestCase):
    """A scene that always jumps away is a corridor, not a room.

    Everything written on it for the reader to see would be discarded silently,
    which is exactly the failure this project exists to argue against -- prose
    that is in the file, is never shown, and cannot be noticed by playing. So it
    is refused at load time, and the author is told where to put the prose
    instead.
    """

    def test_the_fixture_s_connective_scene_has_no_prose(self) -> None:
        fall = minimal_story().scene("fall")
        self.assertEqual(fall.body, ())
        self.assertEqual(fall.variants, ())

    def test_a_body_on_a_scene_that_always_jumps_away(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["fall"]["body"] = ["Nobody will read this."]
        self.assertRejects(
            document,
            mentions=("jumps away", "ever read", "message"),
            pointer="scenes.fall.body",
        )

    def test_variants_on_a_scene_that_always_jumps_away(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["fall"]["variants"] = [
            {"when": {"flag": "trusted"}, "body": ["Nor this."]}
        ]
        self.assertRejects(
            document, mentions=("jumps away",), pointer="scenes.fall.variants"
        )

    def test_an_ending_on_a_scene_that_always_jumps_away(self) -> None:
        """The ending would be unreachable, so the reader could never arrive at
        the ending this scene was named after."""
        document = clone(minimal_document())
        document["scenes"]["fall"]["ending"] = "steady_light"
        self.assertRejects(
            document, mentions=("jumps away", "ending"), pointer="scenes.fall.ending"
        )

    def test_a_guarded_jump_does_not_make_a_scene_connective(self) -> None:
        """The rule is about *always* jumping away.

        A scene that only sometimes jumps still gets shown the rest of the time,
        so its prose is read and is perfectly legitimate. The loader has to be
        able to tell the two apart, or the rule would forbid the idiom it
        recommends.
        """
        document = clone(minimal_document())
        document["scenes"]["fall"]["body"] = ["The stair gives way."]
        document["scenes"]["fall"]["on_enter"] = [
            {"when": {"first_time": True}, "do": [{"goto": "cellar"}]}
        ]
        document["scenes"]["fall"]["choices"] = [{"text": "Get up", "to": "hall"}]

        story = parse_story(document)

        self.assertEqual(story.scene("fall").body[0].text, "The stair gives way.")
        self.assertEqual(len(story.scene("fall").choices), 1)


class ChoicesCanAlwaysBeHiddenTests(StoryTestCase):
    def test_a_scene_where_every_choice_is_conditional(self) -> None:
        """Otherwise a reader whose state matches none of the conditions is left
        with nothing to press, and the story simply stops there."""
        document = clone(minimal_document())
        for choice in document["scenes"]["hall"]["choices"]:
            choice["when"] = {"flag": "trusted"}
        self.assertRejects(
            document,
            mentions=("can be hidden", "nothing to press"),
            pointer="scenes.hall.choices",
        )

    def test_one_unconditional_choice_is_enough(self) -> None:
        document = clone(minimal_document())
        for choice in document["scenes"]["hall"]["choices"][1:]:
            choice["when"] = {"flag": "trusted"}
        self.assertEqual(len(parse_story(document).scene("hall").choices), 4)

    def test_a_locked_choice_still_counts_as_something_to_press(self) -> None:
        """Deliberately *not* extended to `enabled_when`.

        "Everything here is locked until you come back with the key" is a real
        design, and a room that is all shut doors is a scene in a story rather
        than a bug -- the reader can see the options, and can read what they
        want. Hiding them would be the different, and wrong, answer.
        """
        document = clone(minimal_document())
        for choice in document["scenes"]["hall"]["choices"]:
            choice["enabled_when"] = {"has_item": "brass_key"}
            choice["locked_hint"] = "not yet"
        self.assertEqual(len(parse_story(document).scene("hall").choices), 4)


class LockedHintTests(StoryTestCase):
    def test_an_enabled_when_without_a_locked_hint(self) -> None:
        """A dimmed option with no explanation is indistinguishable from a
        broken program, from where the reader is sitting."""
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][1].pop("locked_hint")
        self.assertRejects(
            document,
            mentions=("enabled_when", "locked_hint", "dimmed"),
            pointer="scenes.hall.choices[1]",
        )

    def test_a_locked_hint_beside_an_enabled_when_is_fine(self) -> None:
        choice = minimal_story().scene("hall").choices[1]
        self.assertIsNotNone(choice.enabled_when)
        self.assertTrue(choice.locked_hint)


class DeadActionTests(StoryTestCase):
    """Nothing after an unconditional `goto` can run, so nothing may follow one.

    The rule is a generalisation of "no two unconditional gotos": under
    first-applied-wins the list stops at the first jump, which makes *every*
    action below it dead -- a `take` that takes nothing, a `message` nobody
    reads.
    """

    def test_an_action_after_an_unconditional_goto(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [
            {"goto": "cellar"},
            {"take": "brass_key"},
        ]
        self.assertRejects(
            document,
            mentions=("can never run", "goto"),
            pointer="scenes.fall.on_enter[0]",
        )

    def test_two_unconditional_gotos(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [
            {"goto": "cellar"},
            {"goto": "workshop"},
        ]
        self.assertRejects(document, mentions=("can never run",), pointer="scenes.fall.on_enter[0]")

    def test_a_message_after_an_unconditional_goto(self) -> None:
        """The quietest version of the mistake: prose written for a scene it can
        never be read in."""
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [
            {"goto": "cellar"},
            {"message": ["You will never see this."]},
        ]
        self.assertRejects(document, mentions=("can never run",), pointer="scenes.fall.on_enter[0]")

    def test_a_goto_may_be_the_last_thing_in_a_list(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [
            {"message": ["Down we go."]},
            {"goto": "cellar"},
        ]
        self.assertEqual(len(parse_story(document).scene("fall").on_enter), 2)

    def test_the_recommended_idiom_survives(self) -> None:
        """A guarded jump followed by an unconditional one is *the* way to write
        "go here if you can, otherwise go there" -- and it has to keep loading,
        because the loader's own error messages tell authors to write it."""
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [
            {"when": {"has_item": "brass_key"}, "do": [{"goto": "workshop"}]},
            {"goto": "cellar"},
        ]
        story = parse_story(document)
        self.assertEqual(len(story.scene("fall").on_enter), 2)

    def test_a_guarded_jump_inside_a_guard_is_checked_too(self) -> None:
        """Every list is checked, including the ones nested inside a `do`."""
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"] = [
            {
                "when": {"flag": "trusted"},
                "do": [{"goto": "cellar"}, {"message": ["Unreachable."]}],
            }
        ]
        self.assertRejects(
            document, mentions=("can never run",), pointer="scenes.fall.on_enter[0].do[0]"
        )


class VariableTests(StoryTestCase):
    def test_hud_variable_without_a_label(self) -> None:
        document = clone(minimal_document())
        document["variables"]["lamps_lit"].pop("label")
        self.assertRejects(
            document, mentions=("status line", "label"), pointer="variables.lamps_lit"
        )

    def test_initial_value_does_not_match_the_declared_type(self) -> None:
        document = clone(minimal_document())
        document["variables"]["lamps_lit"]["initial"] = "three"
        self.assertRejects(
            document,
            mentions=("lamps_lit", "declared as int"),
            pointer="variables.lamps_lit.initial",
        )

    def test_unknown_variable_type(self) -> None:
        document = clone(minimal_document())
        document["variables"]["mood"]["type"] = "text"
        self.assertRejects(
            document, mentions=("text",), pointer="variables.mood.type"
        )

    def test_setting_a_variable_to_the_wrong_type(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][1]["effects"] = [{"set": {"trusted": "yes"}}]
        self.assertRejects(
            document,
            mentions=("trusted", "declared as bool"),
            pointer="scenes.hall.choices[1].effects[0].set.trusted",
        )

    def test_incrementing_a_non_number(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["choices"][1]["effects"] = [{"inc": {"trusted": 1}}]
        self.assertRejects(
            document,
            mentions=("trusted", "incremented"),
            pointer="scenes.hall.choices[1].effects[0].inc.trusted",
        )

    def test_a_boolean_is_not_a_number(self) -> None:
        """True is an int in Python, and a load-time check that forgot this would
        accept `{"inc": {"lamps_lit": true}}` and then quietly add one."""
        document = clone(minimal_document())
        document["scenes"]["hall"]["on_enter"][0]["do"] = [{"inc": {"lamps_lit": True}}]
        self.assertRejects(
            document, mentions=("whole number",), pointer="scenes.hall.on_enter[0].do[0].inc.lamps_lit"
        )


class VariantTests(StoryTestCase):
    def test_variant_that_changes_nothing(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["variants"] = [{"when": {"flag": "trusted"}}]
        self.assertRejects(
            document, mentions=("changes nothing",), pointer="scenes.hall.variants[0]"
        )

    def test_variant_without_a_condition(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["variants"] = [{"title": "Something Else"}]
        self.assertRejects(
            document, mentions=('"when"',), pointer="scenes.hall.variants[0]"
        )


class ProseTests(StoryTestCase):
    def test_unknown_paragraph_register(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["body"][1]["style"] = "whisperr"
        self.assertRejects(
            document,
            mentions=("whisperr",),
            pointer="scenes.hall.body[1].style",
        )

    def test_unknown_pace(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["pace"] = "glacial"
        self.assertRejects(document, mentions=("glacial",), pointer="scenes.hall.pace")

    def test_empty_paragraph(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["body"] = ["   "]
        self.assertRejects(document, mentions=("empty",), pointer="scenes.hall.body[0]")

    def test_paragraph_given_as_a_number(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["body"] = [42]
        self.assertRejects(
            document,
            mentions=("should be text, or an object", "a number (42)"),
            pointer="scenes.hall.body[0]",
        )

    def test_body_given_as_a_bare_string(self) -> None:
        document = clone(minimal_document())
        document["scenes"]["hall"]["body"] = "just the one line"
        self.assertRejects(
            document,
            mentions=("expected a list",),
            pointer="scenes.hall.body",
        )


class MessageProseTests(StoryTestCase):
    """A `message` is a paragraph like any other, including when it is wrong.

    A `message` used to hold bare strings while a scene's `body` could hold a
    string or an object, so the same sentence was written two ways depending on
    whether it was the room speaking or the world answering. Both go through one
    parser now, and **the diagnostics are what that puts at risk**: a shared
    parser is the easiest place in a loader to lose an author's own word, and a
    rewritten diagnostic is invisible in play and invisible to any test that only
    checks a message still loads.

    So each of these asserts the pointer *as well as* the wording -- the same
    faults as `ProseTests`, reached through a `message` instead of a `body`, so
    that the two paths are provably the same one from the author's side.
    """

    WHERE = "scenes.fall.on_enter[0].message"

    def message(self, value: Any) -> dict[str, Any]:
        """The fixture with its one message replaced."""
        document = clone(minimal_document())
        document["scenes"]["fall"]["on_enter"][0]["message"] = value
        return document

    def test_a_message_that_is_not_a_list_names_the_author_s_own_key(self) -> None:
        """Not `expected a list for prose`, which is what a shared parser says
        when it is handed the wrong word."""
        self.assertRejects(
            self.message("one line, unwrapped"),
            mentions=("expected a list", '"message"'),
            pointer=self.WHERE,
        )

    def test_an_empty_message_is_refused(self) -> None:
        """Because `[]` would otherwise become an action that does nothing.

        Prose written for a reader who can never be shown it is the failure this
        project refuses everywhere else, and an effect that silently has no
        effect is the same failure wearing a different hat.
        """
        self.assertRejects(
            self.message([]),
            mentions=('"message"', "empty"),
            pointer=self.WHERE,
        )

    def test_a_message_item_that_is_a_number(self) -> None:
        self.assertRejects(
            self.message([42]),
            mentions=("should be text, or an object", "a number (42)"),
            pointer=self.WHERE + "[0]",
        )

    def test_a_message_item_that_is_empty(self) -> None:
        self.assertRejects(
            self.message(["   "]),
            mentions=("empty",),
            pointer=self.WHERE + "[0]",
        )

    def test_an_unknown_register_in_a_message(self) -> None:
        """`whisperr` -- the typo the vocabulary exists to catch."""
        self.assertRejects(
            self.message([{"text": "quietly", "style": "whisperr"}]),
            mentions=("whisperr", "aside, letter, sign, whisper"),
            pointer=self.WHERE + "[0].style",
        )

    def test_an_unknown_pace_in_a_message(self) -> None:
        self.assertRejects(
            self.message([{"text": "quietly", "pace": "glacial"}]),
            mentions=("glacial",),
            pointer=self.WHERE + "[0].pace",
        )

    def test_the_item_is_named_with_the_key_the_author_actually_wrote(self) -> None:
        """Which is why this branch does not simply call `parse_paragraphs`.

        That helper names every item generically -- "a paragraph" -- and for a
        scene's `body` that is exactly right, because the pointer above the line
        already says `body`. An author writing a message never typed the word
        `body`, so theirs says `"message" paragraph 0`: the key they wrote, and
        which line of it. The two wordings differing is the point, not the
        accident.

        It also makes a tempting tidy-up -- replacing this branch with a call to
        the shared helper -- fail here. It would look like a simplification, and
        it would silently rewrite what every author with a broken message is
        told, which is a thing no playthrough can show.
        """
        message = str(self.assertRejects(self.message([42])))
        self.assertIn('"message" paragraph 0', message)

        document = clone(minimal_document())
        document["scenes"]["hall"]["body"] = [42]
        body = str(self.assertRejects(document))
        self.assertIn("a paragraph should", body)


class ErrorRenderingTests(unittest.TestCase):
    def test_a_message_names_the_file_the_place_and_the_problem(self) -> None:
        document = minimal_document()
        document["scenes"]["hall"]["choices"][0]["to"] = "nowhere"
        story_path = MINIMAL_PATH
        self.assertTrue(story_path.exists())

        try:
            parse_story(document, story_path)
        except StoryError as error:
            rendered = str(error)
            self.assertIn(str(story_path), rendered)
            self.assertIn("scenes.hall.choices[0].to", rendered)
            self.assertIn("nowhere", rendered)
            self.assertIn("hint:", rendered)
        else:
            self.fail("expected the loader to reject this story")

    def test_an_error_without_a_file_still_renders(self) -> None:
        error = StoryError("something is wrong", pointer=Pointer().key("a").index(2))
        self.assertIn("a[2]", str(error))
        self.assertNotIn("None", str(error))

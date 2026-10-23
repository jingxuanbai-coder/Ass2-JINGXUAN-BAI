"""Structural tests for the demo story itself.

These do not test the loader -- the loader has its own tests, against a fixture
built to exercise every corner of the schema. These test *this story*, against
the design it is supposed to implement: three branch points, three endings, one
item-gated way in, and a way to walk away.

Nothing here asserted on prose before W11 did its rewrite, and the rewrite is
the evidence that was worth arranging: every sentence in the file changed and
these tests kept passing untouched. What they pin down is the shape the story is
not allowed to lose.

`ProseTests` is new, and it is the one exception -- it asserts on prose, because
W11 found four more things written that no reader could see, and one of them was
in the story itself. The reader was told about four lines twice and shown none,
and `letter` was a register with a look, a chapter in `STORY_FORMAT.md`, and no
story that used it. Those are claims about the text now, so they are tested
against the text.

**Two of them now delegate.** `test_the_story_is_clean` and the ending check
used to re-implement the walk themselves; they call `find_unseen` instead. The
rule belongs in one place, and the place is `lint.py` -- this file is about
*this story having the shape it was designed with*, and a second implementation
of the same walk is a second thing to keep in step with the first.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from branchline import load_story
from branchline.lint import find_unseen
from branchline.model import HasItem, Scene, Story, TakeItems

STORY_PATH = Path(__file__).parent.parent / "story" / "observatory.json"

# Named here rather than repeated as literals, because these three ids are what
# the tests below are actually about.
KEY = "brass_key"
GATE = "gate"
INSIDE = "vestibule"

#: The register that exists for a document rather than for a voice. It has had a
#: look in the palette and a chapter in `STORY_FORMAT.md` since W9; W11 is the
#: first round in which any story writes in it.
LETTER = "letter"


def demo_story() -> Story:
    return load_story(STORY_PATH)


def ending_scene(story: Story, ending_id: str) -> Scene:
    """The one scene that ends the story the given way."""
    return next(scene for scene in story.scenes.values() if scene.ending == ending_id)


def sentences(text: str) -> set[str]:
    """The sentences in a passage, lowercased, for comparing one to another.

    Split on full stops only. The comparison is equality, so a crude split can
    only ever *miss* an overlap -- never invent one -- and both passages are
    short prose with no abbreviations in them.
    """
    return {part.strip().lower() for part in text.split(".") if part.strip()}


class DemoStoryTests(unittest.TestCase):
    def test_the_story_loads(self) -> None:
        """The real story file must be loadable, not merely the test fixture."""
        story = demo_story()
        self.assertTrue(story.meta.title)
        self.assertIn(story.start, story.scenes)

    def test_the_story_is_clean(self) -> None:
        """Nothing in this file is written that a reader can never see.

        One assertion covering four rules -- an orphaned scene, an ending nothing
        ends at, an item nothing takes, a variable nothing reads -- because that
        is what the linter answers and it is the same question this test always
        asked. A version that named the rules here would be the second
        implementation `lint.py` exists to replace.
        """
        self.assertEqual(find_unseen(demo_story()), ())

    def test_the_ending_check_was_not_a_tautology(self) -> None:
        """`test_the_story_is_clean` would pass on a story with no endings at all.

        So the endings are shown to be here, and to be three: the ambiguous one
        that takes the story's own name, the bitter one the logbook pays off, and
        the neutral one for walking away.
        """
        story = demo_story()
        used = {
            scene.ending for scene in story.scenes.values() if scene.ending is not None
        }
        self.assertEqual(used, set(story.endings))
        self.assertEqual(len(story.endings), 3)

    def test_the_one_item_is_one_a_reader_can_actually_look_at(self) -> None:
        """The demo's item is the worked example of `look`, so it has to be
        worth looking at -- a name, a picture, and something written about it.

        Before `look` existed this data was already in the file and unreadable,
        which is the fault the whole round is arranged against: the loader's
        `ITEM_KEYS` accepts `art` and `description`, the model stores them, and
        the format document has told authors since the schema landed that
        `description` is what the reader is told when they look.
        """
        item = demo_story().items[KEY]

        self.assertTrue(item.name)
        self.assertTrue(item.description)
        self.assertTrue(item.art)

    # -- branch point 2: the item gate -------------------------------------

    def test_the_building_can_only_be_entered_with_the_key(self) -> None:
        """The single most important invariant in this story.

        If a route in exists that does not ask for the key, the key stops being
        part of the story and the flowerbed becomes decoration.

        Either gate counts. `when` hides the option until you are holding the
        key; `enabled_when` shows it, dimmed, and refuses. Which of the two the
        door uses is an authorial decision about how much the reader is told,
        and the story currently uses the second -- so this asserts what the door
        *requires*, not how it says so.
        """
        story = demo_story()
        routes = [
            (scene_id, choice)
            for scene_id, scene in story.scenes.items()
            for choice in scene.choices
            if choice.to == INSIDE
        ]
        self.assertTrue(routes, "there has to be a way in")
        for scene_id, choice in routes:
            with self.subTest(entering_from=scene_id):
                gates = [
                    gate
                    for gate in (choice.when, choice.enabled_when)
                    if gate is not None
                ]
                self.assertIn(
                    HasItem((KEY,)),
                    gates,
                    "every route into the observatory should ask for the key",
                )

    def test_the_key_is_found_outside_the_building(self) -> None:
        """The gate must be openable from a cold start.

        A story whose only key is behind the door it opens is unwinnable, and
        playtesting is the expensive way to find that out.
        """
        story = demo_story()
        granted = [
            scene_id
            for scene_id, scene in story.scenes.items()
            if any(
                isinstance(action, TakeItems) and KEY in action.item_ids
                for action in scene.on_enter
            )
        ]
        self.assertEqual(len(granted), 1, "exactly one scene should hand over the key")
        self.assertIn(granted[0], story.reached_scenes())

    def test_the_gate_always_allows_giving_up(self) -> None:
        """Giving up must never be gated. It is the reader's, not the story's."""
        gate = demo_story().scene(GATE)
        ungated = [
            choice
            for choice in gate.choices
            if choice.when is None and choice.enabled_when is None
        ]
        self.assertTrue(ungated, "a reader with nothing should still be able to leave")

    # -- branch point 3: the two ways the story ends -----------------------

    def test_inside_offers_two_routes_to_different_endings(self) -> None:
        story = demo_story()
        destinations = {choice.to for choice in story.scene(INSIDE).choices}
        self.assertEqual(len(destinations), 2)

    def test_inside_is_reachable_but_not_where_you_start(self) -> None:
        story = demo_story()
        self.assertNotEqual(story.start, INSIDE)
        self.assertIn(INSIDE, story.reached_scenes())


class ProseTests(unittest.TestCase):
    """What W11 found written and unreadable, asserted against the text itself.

    The organising rule of this project is that a thing declared which no reader
    ever perceives is the cardinal fault. It was found four times in the code
    this round -- and a fifth time in the story, which is the one that matters
    most, because the story is the thing being made.
    """

    def test_the_letter_register_is_used_by_the_story(self) -> None:
        """`letter` had a look in `palette.py`, five paragraphs in
        `STORY_FORMAT.md`, and no story that wrote in it.

        A register nothing is written in is a look no reader will ever see --
        the palette's own fault, one level up, and invisible in every test that
        only checks the palette covers the vocabulary.
        """
        story = demo_story()
        written_in_letter = [
            paragraph
            for scene in story.scenes.values()
            for paragraph in scene.body
            if paragraph.style == LETTER
        ]
        self.assertTrue(
            written_in_letter, "no story writes in the letter register"
        )

    def test_the_four_lines_are_delivered(self) -> None:
        """The scene is called "Four Lines" and its body says it is four lines.

        Before W11 it said so twice and showed none: the reader was told about
        the only text that matters, by the narrator, and never handed it. A
        story about writing things down in which the writing is never read is
        the cardinal fault in its literary form.
        """
        scene = ending_scene(demo_story(), "what_was_written")
        quoted = [p for p in scene.body if p.style == LETTER]
        self.assertEqual(len(quoted), 4)

    def test_the_last_line_stops_in_the_middle(self) -> None:
        """The cut is the content: whoever was writing stopped writing.

        The third line runs into the fourth without a full stop, and the fourth
        ends on a word with nothing after it. Restoring the punctuation -- the
        single most likely thing for a later editor to "tidy" -- would leave the
        ending's *it is not yours* with nothing to land on, and no test that
        only counted paragraphs would notice.
        """
        scene = ending_scene(demo_story(), "what_was_written")
        quoted = [p for p in scene.body if p.style == LETTER]
        self.assertFalse(
            quoted[2].text.rstrip().endswith("."),
            "the third line should run on into the fourth, not end",
        )
        self.assertTrue(
            quoted[3].text.rstrip()[-1].isalpha(),
            "the fourth line should stop mid-sentence, with no mark after it",
        )

    def test_the_epilogue_does_not_restate_the_scene(self) -> None:
        """The scene shows the text; the epilogue is what the reader does about
        it.

        These two passages were the same passage once -- the body restated the
        epilogue sentence for sentence, which is a whole scene of prose that
        took effect exactly nowhere. No sentence may now appear in both.
        """
        story = demo_story()
        scene = ending_scene(story, "what_was_written")
        body = set().union(*(sentences(p.text) for p in scene.body))
        epilogue = set().union(
            *(sentences(p.text) for p in story.endings["what_was_written"].epilogue)
        )
        self.assertEqual(body & epilogue, set())


class NoDraftPromiseTests(unittest.TestCase):
    """The `_note` apologised for a draft. The draft has been written."""

    def test_the_note_does_not_apologise_for_a_draft(self) -> None:
        """A file that tells its author the prose is temporary will be believed.

        This one shipped saying the sentences "are provisional and get rewritten
        in W11". They were, and W11 has been and gone -- so the note would have
        been a promise about a stage that no longer exists, in the first thing
        any author opening this file reads.
        """
        document = json.loads(STORY_PATH.read_text(encoding="utf-8"))
        note = " ".join(document["_note"]).lower()

        for phrase in ("provisional", "w11", "week 11", "draft", "placeholder"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, note)


if __name__ == "__main__":
    unittest.main()

"""Tests for save files.

Two things are being checked here, and only one of them is about files.

The first is the ordinary one: a run goes into a file and comes back out the way
it went in, and a file that is not a save is a sentence rather than a traceback.

The second is the reason this module is built the way it is. **The story is not
in the save.** The save holds where the reader is and what they have done; the
sentences come from the story file on disk, every time. That is a design choice
with a cost -- a save can stop fitting its story, and the whole reconciliation
table exists to pay it -- and it is worth paying, because the alternative is a
save that keeps serving the reader prose the author has since rewritten, forever,
with nothing in the game to show it. `ProseTests` below is the acceptance
criterion stated as an assertion: take the story, rewrite every sentence in it,
and the save must still load, with the *new* words.

**Every mismatch is built by changing the state, not by breaking the story.**
That is not a shortcut. What a mismatch *is*, is a save that no longer fits: the
story drops a scene, and the save on disk still names it. Mutating the document
until the loader rejects it would test the loader, and most of them could not be
expressed that way at all -- an item the story has stopped declaring leaves no
trace in the story to point at.
"""

from __future__ import annotations

import json
import pickle
import random
import tempfile
import unittest
from pathlib import Path
from typing import Any

from branchline import Engine, StoryError, load_story, parse_story
from branchline.save import (
    FORMAT,
    SAVE_DIR,
    SUFFIX,
    VERSION,
    SaveFile,
    read_save,
    reconcile,
    shown,
    write_save,
)
from branchline.state import GameState
from tests.fixtures import clone, minimal_document, minimal_story


def without_scene(document: dict[str, Any], scene_id: str) -> dict[str, Any]:
    """The document with a scene removed, and every path to it removed with it.

    Deleting the scene alone would leave a choice pointing at nothing, and the
    loader would reject the whole file -- which would prove nothing about saves,
    since the story would never have loaded to be saved against.
    """
    del document["scenes"][scene_id]
    for scene in document["scenes"].values():
        if "choices" in scene:
            scene["choices"] = [
                choice for choice in scene["choices"] if choice.get("to") != scene_id
            ]
    return document


class SaveTestCase(unittest.TestCase):
    """A story, a run, and a throwaway directory to write saves into."""

    def setUp(self) -> None:
        self.story = minimal_story()
        self.run = GameState.new(self.story, seed=99)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / f"fixture{SUFFIX}"

    def round_trip(self, state: GameState | None = None) -> SaveFile:
        """Write a run out and read it back, which is the only path a save takes."""
        write_save(self.path, state if state is not None else self.run)
        return read_save(self.path)

    def reconciled(self, state: GameState, story: Any = None) -> GameState:
        """The state a load of `state` would produce against this story."""
        return reconcile(SaveFile(state=state), story if story is not None else self.story)

    def refused(self, state: GameState, story: Any = None) -> StoryError:
        with self.assertRaises(StoryError) as caught:
            self.reconciled(state, story)
        return caught.exception


class RoundTripTests(SaveTestCase):
    def test_a_run_comes_back_the_way_it_went_in(self) -> None:
        self.run.scene_id = "cellar"
        self.run.variables = {"lamps_lit": 5, "trusted": True, "mood": "settled"}
        self.run.take("brass_key")
        self.run.take("oil_can")
        self.run.visit("hall")
        self.run.visit("hall")
        self.run.visit("cellar")
        self.run.mark_used("hall", "unlock")

        back = self.reconciled(self.round_trip().state)

        self.assertEqual(back.scene_id, "cellar")
        self.assertEqual(back.variables, {"lamps_lit": 5, "trusted": True, "mood": "settled"})
        self.assertEqual(back.carried_ids(), ("brass_key", "oil_can"))
        self.assertEqual(back.visits, {"hall": 2, "cellar": 1})
        self.assertEqual(back.used_choices, {("hall", "unlock")})
        self.assertEqual(back.seed, 99)

    def test_what_is_carried_keeps_the_order_it_was_picked_up_in(self) -> None:
        """The inventory is a dict used as an ordered set, and W9 prints it.

        A save that came back sorted would reorder the reader's own backpack
        between one session and the next, which is the kind of detail that reads
        as a bug without ever being one.
        """
        for item_id in ("oil_can", "brass_key"):
            self.run.take(item_id)
        self.assertEqual(self.reconciled(self.round_trip().state).carried_ids(),
                         ("oil_can", "brass_key"))

    def test_the_file_says_what_it_is(self) -> None:
        """A pickle of *something* is not a save.

        Without the tag, a `GameState` from someone's experiment -- or a
        `SaveFile` written by a future version with fields this one has never
        heard of -- would be unpacked and played.
        """
        loaded = self.round_trip()
        self.assertEqual(loaded.format, FORMAT)
        self.assertEqual(loaded.version, VERSION)

    def test_the_file_is_written_where_it_was_asked_to_be_written(self) -> None:
        self.assertEqual(write_save(self.path, self.run), self.path)
        self.assertTrue(self.path.exists())

    def test_a_directory_that_is_not_there_yet_is_made(self) -> None:
        """The reader never types a path, so nobody can make the directory for them."""
        nested = Path(self.directory.name) / "deeper" / "still" / f"x{SUFFIX}"
        write_save(nested, self.run)
        self.assertTrue(nested.exists())

    def test_a_field_an_old_save_predates_is_filled_in(self) -> None:
        """`GameState.__setstate__` is the generic repair, and this is it working
        through a real file rather than in a unit test of the mechanism.

        Deleting the field from the state's `__dict__` before writing is exactly
        what a save written before that field existed looks like on disk, so the
        only way to tell the difference is to actually make one.
        """
        del self.run.__dict__["visits"]
        write_save(self.path, self.run)

        back = read_save(self.path).state

        self.assertEqual(back.visits, {})
        self.assertEqual(back.scene_id, "hall")


class ProseTests(SaveTestCase):
    """Rewrite the story, and the save must still load.

    This is the acceptance criterion for the whole design, so it is written as an
    assertion rather than as an intention. If anyone ever "simplifies" the save
    by pickling the engine -- which holds the story, which holds every sentence
    -- this is the test that fails, and it fails for the right reason.

    It was called a rehearsal once, when W11 was still coming and this was the
    dress run for it. It is no longer a rehearsal: W11 rewrote the real story's
    prose, and this test's premise is the one that rewrite ran on. What it does
    here deliberately, with a rewritten fixture, is what was done to
    `observatory.json` -- change the sentences under a saved run and require the
    run to come back, and to come back reading the *new* words.
    """

    def respun(self, document: dict[str, Any]) -> dict[str, Any]:
        """Every sentence the reader reads, replaced with a different one."""
        for scene in document["scenes"].values():
            if "body" in scene:
                scene["body"] = [self.one(paragraph) for paragraph in scene["body"]]
        for ending in document["endings"].values():
            ending["epilogue"] = [self.one(paragraph) for paragraph in ending["epilogue"]]
        return document

    @staticmethod
    def one(paragraph: Any) -> Any:
        """A paragraph, rewritten -- keeping its register and pace if it has them."""
        if isinstance(paragraph, str):
            return paragraph.upper()
        return {**paragraph, "text": paragraph["text"].upper()}

    def test_a_rewritten_story_still_loads_the_same_run(self) -> None:
        # Written first, then the story changes under it -- which is the order
        # this happens in life, and the only order that tests anything.
        self.run.scene_id = "cellar"
        self.run.take("brass_key")
        written = self.round_trip()

        rewritten = parse_story(self.respun(clone(minimal_document())))
        back = self.reconciled(written.state, rewritten)

        self.assertEqual(back.scene_id, "cellar")
        self.assertEqual(back.carried_ids(), ("brass_key",))

    def test_and_the_reader_is_served_the_new_words(self) -> None:
        """The half that makes the first test mean something.

        A save that loaded but still showed the old prose would satisfy "it
        loads" while failing at the only thing the reader can see. So the check
        is not that some state survived -- it is that the engine assembled from
        the save draws the sentence the *author* has now written.
        """
        self.round_trip()
        rewritten = parse_story(self.respun(clone(minimal_document())))

        resumed = Engine.resume(rewritten, self.reconciled(read_save(self.path).state, rewritten))

        self.assertEqual(
            resumed.view().body[0].text, self.story.scenes["hall"].body[0].text.upper()
        )
        self.assertNotEqual(
            resumed.view().body[0].text, self.story.scenes["hall"].body[0].text
        )

    def test_not_one_sentence_of_the_story_is_in_the_save_file(self) -> None:
        """The whole design, checked against the bytes rather than the code.

        Read the file and look for the prose. If anyone ever "simplifies" this by
        pickling the engine -- which holds the story, which holds every sentence
        -- every sentence in the story is suddenly in the save, and this fails
        naming the one that gave it away.
        """
        write_save(self.path, self.run)
        written = self.path.read_bytes()

        for scene_id, scene in self.story.scenes.items():
            for index, paragraph in enumerate(scene.body):
                with self.subTest(scene=scene_id, paragraph=index):
                    self.assertNotIn(paragraph.text.encode("utf-8"), written)

    def test_the_rewrite_actually_rewrites_something(self) -> None:
        """Guards the two above.

        If `respun` ever stopped rewriting anything, both of them would still
        pass and this file's whole claim would be untested. Only the *prose* is
        compared, and only where there is prose to compare: `fall` has no body
        at all -- it is a connective scene that only falls through -- so
        asserting that its empty body changed would fail on a correct story.
        """
        rewritten = parse_story(self.respun(clone(minimal_document())))
        compared = 0
        for scene_id, scene in self.story.scenes.items():
            if not scene.body:
                continue
            compared += 1
            with self.subTest(scene=scene_id, part="body"):
                self.assertNotEqual(
                    [p.text for p in rewritten.scenes[scene_id].body],
                    [p.text for p in scene.body],
                )
        for ending_id, ending in self.story.endings.items():
            compared += 1
            with self.subTest(ending=ending_id):
                self.assertNotEqual(
                    [p.text for p in rewritten.endings[ending_id].epilogue],
                    [p.text for p in ending.epilogue],
                )
        self.assertGreater(compared, 0, "the story has no prose left to rewrite")


class RepairTests(SaveTestCase):
    """The half of the table that is fixed quietly, because nothing visible changes."""

    def test_a_variable_the_story_stopped_declaring_is_dropped(self) -> None:
        """It is read by nothing, so its absence is invisible to the reader."""
        self.run.variables["mood"] = "settled"
        self.run.variables["confidence"] = 4

        back = self.reconciled(self.run)

        self.assertNotIn("confidence", back.variables)
        self.assertEqual(back.variables["mood"], "settled")

    def test_a_variable_the_story_started_declaring_takes_its_initial_value(self) -> None:
        """The reader has never seen it, so there is nothing to preserve -- and
        the declared initial is not a guess, it is what the author wrote."""
        del self.run.variables["trusted"]

        back = self.reconciled(self.run)

        self.assertFalse(back.variables["trusted"])

    def shorter_story(self) -> Any:
        """The fixture with `tide_table` deleted -- a rename, with the rename left out.

        A scene the author took out is the same problem as one they renamed, and
        it needs no suggestion machinery to read clearly: the save names a scene
        the story does not have, and the reader is not standing in it.
        """
        return parse_story(without_scene(clone(minimal_document()), "tide_table"))

    def test_a_scene_the_story_dropped_is_dropped_from_the_visit_counts(self) -> None:
        """A visit count for a scene that is not in the story affects nothing the
        reader can perceive -- so it is repaired rather than refused."""
        self.run.visit("hall")
        self.run.visits["tide_table"] = 3

        back = self.reconciled(self.run, self.shorter_story())

        self.assertEqual(back.visits, {"hall": 1})

    def test_a_scene_the_story_dropped_is_dropped_from_the_used_choices(self) -> None:
        """The worst this can do is bring a `once` option back, in a scene that
        no longer exists -- so it cannot even do that."""
        self.run.used_choices.add(("tide_table", "back"))

        back = self.reconciled(self.run, self.shorter_story())

        self.assertEqual(back.used_choices, set())
        self.assertEqual(self.run.used_choices, {("tide_table", "back")})

    def test_repairing_does_not_edit_the_state_that_was_read(self) -> None:
        """`reconcile` returns a new state and leaves the file's alone.

        The file is not a draft to be corrected. Something else in the program
        may still be holding it, and a load that half-happened in the object the
        caller passed in is a great deal harder to reason about than one that
        either returned or raised.
        """
        self.run.variables["confidence"] = 4
        before = pickle.dumps(self.run)

        self.reconciled(self.run)

        self.assertEqual(pickle.dumps(self.run), before)


class RefusalTests(SaveTestCase):
    """The half of the table that must not be guessed at."""

    def test_a_scene_the_story_no_longer_declares_is_refused(self) -> None:
        """Standing in a near neighbour is not standing where you saved."""
        self.run.scene_id = "hallway"

        error = self.refused(self.run)

        self.assertIn('you are standing in "hallway"', str(error))
        self.assertIn("not a scene in this story", str(error))

    def test_and_it_suggests_the_scene_it_was_probably_meant_to_be(self) -> None:
        """The same courtesy the loader extends to a misspelled scene id.

        It is the same failure -- an id that names nothing -- so it gets the same
        answer, which is the reason a save is diagnosed by `load_story`'s error
        class rather than by one of its own.
        """
        self.run.scene_id = "hallway"
        self.assertIn('did you mean "hall"?', str(self.refused(self.run)))

    def test_an_item_the_story_no_longer_declares_is_refused(self) -> None:
        """The inventory is part of what the reader can do."""
        self.run.take("iron_key")

        error = self.refused(self.run)

        self.assertIn('you are carrying "iron_key"', str(error))
        self.assertIn("not an item this story declares", str(error))

    def test_every_problem_is_listed_and_not_just_the_first(self) -> None:
        """An author who fixes one and reloads to be told about the next is
        reading the file by hand to find out what is wrong with it -- exactly the
        loop this project refuses everywhere else."""
        self.run.scene_id = "hallway"
        self.run.take("iron_key")
        self.run.take("glass_eye")

        rendered = str(self.refused(self.run))

        self.assertIn("hallway", rendered)
        self.assertIn("iron_key", rendered)
        self.assertIn("glass_eye", rendered)

    def test_a_refusal_names_the_save_and_says_what_it_is(self) -> None:
        """One sentence at the top saying which file is being complained about."""
        self.run.scene_id = "hallway"
        self.assertIn("from an earlier version of the story", str(self.refused(self.run)))

    def test_a_refused_load_leaves_the_run_in_progress_untouched(self) -> None:
        """All or nothing: a half-applied save is a game state that never existed.

        Compared by pickling both, because "equal" here has to mean every field,
        including the ones a hand-written comparison would forget to mention.
        """
        engine = Engine.start(self.story, seed=7)
        engine.take(1)  # into the workshop, which hands over the key
        before = pickle.dumps(engine.state)

        self.run.scene_id = "hallway"
        self.refused(self.run)

        self.assertEqual(pickle.dumps(engine.state), before)


class GeneratorTests(SaveTestCase):
    """The seed is what the opening screen advertises; the position is what it means."""

    def test_the_generator_resumes_where_it_stopped_and_not_at_the_seed(self) -> None:
        """A run saved after three coin flips must make the fourth flip next.

        Restoring the seed alone would start the sequence again, so a reader who
        loaded would meet a repeat of everything chancy they had already seen --
        silently, and only if they were paying attention.
        """
        for _ in range(3):
            self.run.rng.random()

        back = self.reconciled(self.round_trip().state)

        self.assertEqual(back.rng.random(), self.run.rng.random())

    def test_the_generator_in_the_file_is_not_the_generator_that_keeps_running(self) -> None:
        """Copied, not shared.

        Handing the loaded run the very `Random` out of the file would leave the
        file's contents advancing underneath whoever still holds it -- invisible,
        and the kind of aliasing that is discovered a year later.
        """
        written = self.round_trip()
        first = reconcile(written, self.story)
        second = reconcile(written, self.story)

        first.rng.random()

        self.assertEqual(second.rng.random(), written.state.rng.random())


class NotASaveTests(SaveTestCase):
    """Every one of these is a thing a *reader* does, not a fault in the program."""

    def refused_read(self, **kwargs: Any) -> StoryError:
        with self.assertRaises(StoryError) as caught:
            read_save(**kwargs)
        return caught.exception

    def test_nothing_saved_yet_says_so_and_says_how_to_save(self) -> None:
        error = self.refused_read(path=self.path)
        self.assertIn("nothing saved for this story yet", str(error))
        self.assertIn("save", str(error))

    def test_a_story_file_is_not_a_save(self) -> None:
        """The most likely wrong file by far: the reader points at the story."""
        self.path.write_text(json.dumps(minimal_document()), encoding="utf-8")
        self.assertIn("not a save", str(self.refused_read(path=self.path)))

    def test_an_empty_file_is_not_a_save(self) -> None:
        """Half a copy, or a file a text editor touched."""
        self.path.write_bytes(b"")
        self.assertIn("not a save", str(self.refused_read(path=self.path)))

    def test_a_truncated_save_is_not_a_save(self) -> None:
        write_save(self.path, self.run)
        whole = self.path.read_bytes()
        self.path.write_bytes(whole[: len(whole) // 2])
        self.assertIn("not a save", str(self.refused_read(path=self.path)))

    def test_a_pickle_of_something_else_is_not_a_save(self) -> None:
        """Someone else's experiment, or this program's own state written out
        without its envelope. Unpackable, and still not a run."""
        self.path.write_bytes(pickle.dumps({"not": "a save"}))
        self.assertIn("not a save", str(self.refused_read(path=self.path)))

    def test_a_state_written_without_its_envelope_is_not_a_save(self) -> None:
        self.path.write_bytes(pickle.dumps(self.run))
        rendered = str(self.refused_read(path=self.path))
        self.assertIn("not a save", rendered)
        self.assertIn("GameState", rendered)

    def test_a_save_from_a_newer_program_says_so_rather_than_guessing(self) -> None:
        """Refusing is the honest answer. Unpacking it and hoping the fields
        line up is how a reader loses a run without being told."""
        self.path.write_bytes(
            pickle.dumps(SaveFile(state=self.run, version=VERSION + 1))
        )
        rendered = str(self.refused_read(path=self.path))
        self.assertIn("newer BranchLine", rendered)
        self.assertIn(str(VERSION + 1), rendered)

    def test_a_save_with_no_run_in_it_says_that_and_not_something_else(self) -> None:
        """`state` is the one field with no default, so this is a file that was
        written by something that is nearly a save -- and the reader should be
        told which of the two problems they have."""
        self.path.write_bytes(pickle.dumps(SaveFile(state=None)))  # type: ignore[arg-type]
        self.assertIn("no run in it", str(self.refused_read(path=self.path)))

    def test_a_save_that_cannot_be_written_is_a_sentence_and_not_a_traceback(self) -> None:
        """A read-only folder is a thing that happens to a reader. It is not a
        reason for their run to end in a wall of red."""
        blocker = Path(self.directory.name) / "not-a-directory"
        blocker.write_text("this is a file", encoding="utf-8")

        with self.assertRaises(StoryError) as caught:
            write_save(blocker / f"x{SUFFIX}", self.run)

        self.assertIn("could not be written", str(caught.exception))


class PathTests(unittest.TestCase):
    """Where a save goes, and how the path is said out loud."""

    def test_the_slot_is_named_after_the_story(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            story_file = Path(tmp) / "observatory.json"
            story_file.write_text(json.dumps(minimal_document()), encoding="utf-8")
            self.assertEqual(
                SaveFile.path_for(load_story(story_file), directory=tmp),
                Path(tmp) / f"observatory{SUFFIX}",
            )

    def test_two_stories_do_not_share_one_slot(self) -> None:
        """One slot per story, so the demo cannot overwrite the sample -- and the
        reader still never has to choose anything."""
        with tempfile.TemporaryDirectory() as tmp:
            names = []
            for name in ("observatory", "sample"):
                path = Path(tmp) / f"{name}.json"
                path.write_text(json.dumps(minimal_document()), encoding="utf-8")
                names.append(SaveFile.path_for(load_story(path), directory=tmp))
            self.assertNotEqual(*names)

    def test_a_story_built_from_a_document_still_gets_a_slot(self) -> None:
        """`parse_story` has no file to take a name from. Falling back to a fixed
        name is better than a crash, and better than refusing to save a story
        that came from a string, which is exactly what the test suite plays."""
        self.assertEqual(
            SaveFile.path_for(minimal_story(), directory="saves"),
            Path("saves") / f"branchline{SUFFIX}",
        )

    def test_saves_live_beside_the_program_and_not_in_the_directory_you_are_in(self) -> None:
        """A story opened by double-click has no useful current directory, and
        `story/` is the author's source rather than the reader's bookkeeping."""
        self.assertEqual(SAVE_DIR, Path(__file__).parent.parent / "saves")

    def test_a_path_under_where_you_are_is_shortened_to_what_you_can_type(self) -> None:
        self.assertEqual(shown(Path.cwd() / "saves" / f"x{SUFFIX}"),
                         Path("saves") / f"x{SUFFIX}")

    def test_a_path_somewhere_else_is_left_alone(self) -> None:
        """There the absolute path *is* the short one -- the alternative is
        `..\\..\\..` for someone who did nothing wrong."""
        elsewhere = Path(tempfile.gettempdir()) / "elsewhere" / f"x{SUFFIX}"
        self.assertEqual(shown(elsewhere), elsewhere)


if __name__ == "__main__":
    unittest.main()

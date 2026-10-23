"""Tests for the program itself.

`main.py` is the one file nothing else imports, which is precisely why it needs
tests rather than trust. W9 changed nearly everything it calls -- the presenter
arrived, `show` and `lines` went -- and **the whole suite stayed green through
all of it**, because no test touched it. A reader would have found the damage,
in the terminal, where a dataclass repr would have been printed where the world's
reply belongs.

**The promise this file exists to keep.** `STORY_FORMAT.md` opens by telling an
author who does not program that they need to install nothing to *write* a
story. `--check` is the writing tool, and `--play` is the reading one. So the
first tests here run `main.py` in an interpreter where `rich` cannot be imported
at all -- the only way to know the sentence is still true, and the reason the
import sits inside `play()` rather than at the top of the file.

The last group here is the newest promise, and it is the one this file could not
have tested before: `--check` now **fails** on a story that writes something no
reader will ever see. That is a claim about an exit code, so it is checked the
only way an exit code can be -- by running the program and looking at the number
it returns.

Nothing here drives a playthrough. That half is checked by playing the game,
which is what the flag is for.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MAIN = REPO_ROOT / "main.py"
SAMPLE = REPO_ROOT / "story" / "sample.json"
SAVES = REPO_ROOT / "saves"


def run_main(
    *args: str, without_rich: bool = False, typed: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Run `main.py` in a new interpreter, optionally one with no presentation library.

    `runpy` rather than the command line, because the blocked case has to take
    effect *before* `main.py` is read -- and a `from rich...` at the top of the
    file would then fail here, which is exactly the thing worth failing on.

    Making `import rich` fail is one line: in `sys.modules`, a name bound to
    `None` is a name Python refuses to import rather than one it looks for.

    `typed` is what the reader types, one line per prompt. The pipe then *ends*,
    which is the same Ctrl+Z the run ends on for a real reader -- so a script
    that stops typing mid-run is a normal ending and not a hang. Without it the
    child would inherit a stdin that never closes and the test would sit there.
    """
    blocker = (
        "# `rich` is not installed, as far as this interpreter is concerned.\n"
        "import sys; sys.modules['rich'] = None\n"
        if without_rich
        else ""
    )
    script = (
        f"{blocker}"
        f"import runpy, sys\n"
        f"sys.path.insert(0, {REPO_ROOT.as_posix()!r})\n"
        f"sys.argv = ['main.py'] + {list(args)!r}\n"
        f"runpy.run_path({MAIN.as_posix()!r}, run_name='__main__')\n"
    )
    # Both ends of the pipe are pinned to UTF-8. The alternative is the child
    # writing in whatever its locale is and this process reading in whatever
    # *its* locale is, and a story title with an em dash in it arriving as a
    # decode error from a test that has nothing to do with encodings.
    return subprocess.run(
        [sys.executable, "-c", script],
        input="\n".join(typed) + "\n" if typed else "",
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def top_level_imports(path: Path) -> set[str]:
    """Every module imported at the top of a file -- as opposed to inside a function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def imports_inside(path: Path, function: str) -> set[str]:
    """Every module imported inside one function of a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
    )
    found: set[str] = set()
    for node in ast.walk(body):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def write_orphaned_story(directory: Path, stem: str) -> Path:
    """A copy of the sample with one scene cut loose, written to `directory`.

    The sample is used rather than the demo because it is smaller and because
    `--check` on it is already asserted to exit 0 three times above -- so the
    pair of runs is the same file both ways, differing only in one link.

    Mutating a *copy* is the point. A test that damaged a story which ships with
    the project would be a test that leaves the project broken when it fails,
    and the fault it is demonstrating -- a link the author forgot -- is one you
    can only introduce on purpose.
    """
    document = json.loads(SAMPLE.read_text(encoding="utf-8"))
    carriage = document["scenes"]["carriage"]
    carriage["choices"] = [
        choice for choice in carriage["choices"] if choice["to"] != "guard"
    ]
    path = directory / f"{stem}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


class CheckingNeedsNothingInstalledTests(unittest.TestCase):
    """The promise made to the person the format document is written for."""

    def test_a_story_can_be_checked_with_no_presentation_library_at_all(self) -> None:
        result = run_main("--check", str(SAMPLE), without_rich=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The Last Branch Line", result.stdout)

    def test_the_loading_is_still_done_and_not_merely_survived(self) -> None:
        """A run that printed nothing would also exit zero."""
        result = run_main("--check", str(SAMPLE), without_rich=True)
        self.assertIn("scene graph", result.stdout)
        self.assertIn("platform", result.stdout)

    def test_checking_is_what_happens_when_nobody_says_otherwise(self) -> None:
        result = run_main(str(SAMPLE), without_rich=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scene graph", result.stdout)


class CheckingTests(unittest.TestCase):
    def test_checking_reports_what_the_story_is_made_of(self) -> None:
        result = run_main("--check", str(SAMPLE))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scenes", result.stdout)
        self.assertIn("endings", result.stdout)

    def test_a_broken_story_is_a_diagnosis_and_not_a_traceback(self) -> None:
        """The whole point of the loader's error format is that this one line is
        the only thing a non-programmer ever has to read."""
        broken = REPO_ROOT / "tests" / "fixtures" / "broken_for_main.json"
        self.addCleanup(broken.unlink, True)
        broken.write_text('{"format": "branchline.story"}', encoding="utf-8")

        result = run_main("--check", str(broken))

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("format_version", result.stderr)

    def test_playing_and_checking_cannot_be_asked_for_at_once(self) -> None:
        """Argparse refuses the pair, which is better than silently picking one."""
        result = run_main("--check", "--play", str(SAMPLE))
        self.assertEqual(result.returncode, 2)


class PlayingNeedsThePresentationTests(unittest.TestCase):
    """The import lives inside `play()`. These are the tests that say so.

    The subprocess above proves the promise holds today. These say *why* it
    holds, so that moving a line to the top of the file -- which reads like
    tidying -- fails here with a reason attached.
    """

    def test_the_presentation_layer_is_not_imported_at_the_top_of_the_program(self) -> None:
        top = top_level_imports(MAIN)
        self.assertNotIn("rich", top)
        self.assertNotIn("rich.console", top)
        self.assertNotIn("branchline.present", top)

    def test_it_is_imported_where_it_is_used(self) -> None:
        inside = imports_inside(MAIN, "play")
        self.assertIn("rich.console", inside)
        self.assertIn("branchline.present", inside)

    def test_nothing_else_in_the_program_imports_it(self) -> None:
        """Checking a story goes through `summarise`, which draws with `print`.

        The counts, the scene graph and the diagnostics are plain text on
        purpose: an author who has installed nothing should be able to see them.
        """
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name != "play":
                with self.subTest(function=node.name):
                    self.assertNotIn("rich.console", imports_inside(MAIN, node.name))

    def test_saving_is_imported_where_it_is_used_too(self) -> None:
        """`save.py` needs no Rich, but it has no business being loaded to check
        a story either.

        The promise is that checking a story installs nothing and touches
        nothing. A module imported at the top of the file would be read -- and
        so would the `saves/` path it computes -- for a reader who only wanted
        to know whether their JSON was understood.
        """
        self.assertNotIn("branchline.save", top_level_imports(MAIN))
        self.assertIn("branchline.save", imports_inside(MAIN, "play"))

    def test_the_linter_is_imported_at_the_top(self) -> None:
        """The deliberate exception to the rule above, and the reason for it.

        `save` is deferred because importing it computes the `saves/` directory
        and touches the filesystem's idea of a save -- neither of which checking
        a story should do. `lint` has nothing of the kind: it is functions over a
        `Story`, and it is wanted on every single run of the default mode. So it
        sits at the top with the loader, where the dependency is visible, rather
        than inside `summarise` copying the shape of a rule whose reason does not
        apply to it.
        """
        self.assertIn("branchline.lint", top_level_imports(MAIN))


class SavingAndLoadingTests(unittest.TestCase):
    """One process saves, a second loads, and the second one is a reader returning.

    Run as two processes rather than as two function calls, because that is the
    only way to check the claim these commands make. The state is not passed
    across in memory and it is not passed across by a fixture: it goes through a
    file, in a process that has since exited, and comes back in another one that
    read the story from disk again. Everything the design rests on is in that gap.

    **The story is a copy in a temporary directory.** Not because the story
    matters, but because the save does not: `SaveFile.path_for` names the slot
    after the story's own file name, and `SAVE_DIR` is fixed beside the program.
    A copy called `save_test_story.json` therefore gets a slot
    `saves/save_test_story.save`, which is a name no reader will ever have used,
    and the cleanup is allowed to delete it without asking.
    """

    STEM = "save_test_story"

    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.story = Path(self.workspace.name) / f"{self.STEM}.json"
        shutil.copyfile(SAMPLE, self.story)
        self.save = SAVES / f"{self.STEM}.save"
        self.addCleanup(self.save.unlink, True)

    def play(self, *typed: str) -> subprocess.CompletedProcess[str]:
        return run_main("--play", str(self.story), typed=typed)

    def test_the_run_is_written_down_and_picked_up_again(self) -> None:
        first = self.play("1", "save")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("Saved to", first.stdout)
        self.assertTrue(self.save.exists())

        second = self.play("load", "yes")

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Loaded", second.stdout)
        # "The Ticket Window" is where option 1 led, so the second process is
        # not merely reporting that a file existed -- it is standing in the room
        # the first process walked into.
        self.assertIn("The Ticket Window", second.stdout)
        self.assertIn("Punched Ticket", second.stdout)

    def test_the_seed_of_the_loaded_run_is_the_seed_of_the_saved_one(self) -> None:
        """The number is the one thing the opening screen advertises, and the
        whole point of it is that a strange run can be reproduced.

        So a load has to say it again -- and say the *saved* run's, not the one
        the new process happened to be started with, which is the number that
        would otherwise sit there being a false statement about the run on screen.
        """
        first = run_main("--play", "--seed", "4242", str(self.story), typed=("1", "save"))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("seed 4242", first.stdout)

        second = self.play("load", "yes")

        self.assertIn("Loaded", second.stdout)
        self.assertIn("seed 4242", second.stdout)
        self.assertEqual(second.returncode, 0, second.stderr)

    def test_a_reader_does_not_load_by_accident(self) -> None:
        """`yes` is the only word that throws a run away.

        Anything else cancels, and the run carries on from where it stood --
        which is why the scene the reader was in is still the scene they are in
        after typing `load` and then thinking better of it.
        """
        self.play("1", "save")

        result = self.play("load", "no", "2")

        self.assertNotIn("Loaded", result.stdout)
        self.assertIn("Nothing was loaded", result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_load_with_nothing_saved_says_so_without_pretending_to_ask(self) -> None:
        result = self.play("load", "1")

        self.assertIn("Nothing is saved yet", result.stdout)
        self.assertNotIn("will be lost", result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_leaving_does_not_save(self) -> None:
        """The sentence the program used to end on said saving arrived in week
        10. It arrives, and it still is not automatic -- a reader who walks away
        has thrown the run away, and is told how not to next time."""
        result = self.play("1")

        self.assertFalse(self.save.exists())
        self.assertIn("Left where it stands", result.stdout)
        self.assertIn("save", result.stdout)

    def test_a_file_that_is_not_a_save_is_a_diagnosis_and_not_a_traceback(self) -> None:
        """A story file is the most likely wrong file by far: the reader points
        `load` at the one file they have heard of."""
        SAVES.mkdir(parents=True, exist_ok=True)
        for label, contents in (
            ("a story file", SAMPLE.read_bytes()),
            ("an empty file", b""),
        ):
            with self.subTest(what=label):
                self.save.write_bytes(contents)

                result = self.play("load", "yes")

                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertIn("not a save", result.stdout)
                self.assertIn("left alone", result.stdout)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_truncated_save_is_a_diagnosis_and_not_a_traceback(self) -> None:
        self.play("1", "save")
        whole = self.save.read_bytes()
        self.save.write_bytes(whole[: len(whole) // 2])

        result = self.play("load", "yes")

        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("not a save", result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_refused_load_leaves_the_reader_where_they_stood(self) -> None:
        """The whole of the all-or-nothing rule, seen from outside: the run in
        progress is not silently replaced by a broken one, and the game goes on."""
        SAVES.mkdir(parents=True, exist_ok=True)
        self.save.write_text("this is not a save", encoding="utf-8")

        result = self.play("1", "load", "yes", "1")

        self.assertIn("left alone", result.stdout)
        # "Carriage Seven" is reached by pressing 1 *after* the refusal, and the
        # run before it never got that far -- so its presence is what says the
        # game carried on rather than the reader being left at a dead prompt.
        self.assertIn("Carriage Seven", result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)


class LintExitCodeTests(unittest.TestCase):
    """`--check` fails on a story that writes something no reader will ever see.

    **Why this is a correct exit code rather than a harsh one.** The loader
    already refuses an action written after an unconditional `goto`, because it
    can never run -- and the loader can only see that because the dead action is
    in the same list as the jump that killed it. An orphaned scene is the same
    fault one scale up, and the loader cannot see it for the same reason it needs
    a walk to find it: reachability is a property of the whole graph rather than
    of one file location. A check that prints a warning and exits zero is the
    shape of promise this project has twice refused, so this one fails.

    **And why it must not be silent when it passes.** An empty report and a check
    that never ran are the same picture on a terminal, and the second is the only
    reason anyone ran the first -- so the healthy case has a sentence of its own,
    and the first test below is that sentence.
    """

    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.dirty = write_orphaned_story(Path(self.workspace.name), "orphaned")

    def test_a_clean_story_says_so_and_exits_zero(self) -> None:
        result = run_main("--check", str(SAMPLE))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing written here is unseen", result.stdout)

    def test_the_demo_story_is_clean_too(self) -> None:
        """The story that ships as the finished work, not just the sample."""
        result = run_main("--check", str(REPO_ROOT / "story" / "observatory.json"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing written here is unseen", result.stdout)

    def test_an_orphaned_scene_fails_the_check(self) -> None:
        result = run_main("--check", str(self.dirty))

        self.assertEqual(result.returncode, 1, result.stdout)

    def test_the_finding_is_a_report_and_not_a_traceback(self) -> None:
        """It goes to stdout with the rest of the report, under a heading.

        The graph above it is report content and so is this: an author who
        redirects `--check` to a file wants the whole of it, and the non-zero
        exit already carries the "this failed" signal on its own.
        """
        result = run_main("--check", str(self.dirty))

        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("written, and never seen", result.stdout)
        self.assertIn('scene "guard"', result.stdout)
        self.assertIn("never read", result.stdout)

    def test_a_finding_stops_nothing(self) -> None:
        """The orphaned scene is still drawn in the graph, and still plays.

        This is the difference between a finding and a `StoryError`, seen from
        outside: the error stops the load and says the file is wrong, and a
        finding says the file has something in it nobody will reach -- and the
        room still works, and the game still runs, and the author is the only
        person who was ever going to care.

        So the check that fails is the *writing* tool failing. The reader's run
        is untouched, which is why `--play` does not lint at all.
        """
        checked = run_main("--check", str(self.dirty))
        self.assertIn("The Guard", checked.stdout)

        # Board the train, then get off one stop later -- a whole run, in a
        # story with a room in it that nobody can walk into.
        played = run_main("--play", str(self.dirty), typed=("2", "2"))

        self.assertEqual(played.returncode, 0, played.stderr)
        self.assertIn("Carriage Seven", played.stdout)
        self.assertIn("Return", played.stdout)

    def test_the_linter_needs_nothing_installed_either(self) -> None:
        """The promise the format document opens with, applied to the new half.

        `test_a_story_can_be_checked_with_no_presentation_library_at_all` proves
        the loader survives a machine with no Rich. This proves the *linter*
        does, on a story where it has something to say -- which is the harder
        case, because the healthy path could pass by never running.
        """
        result = run_main("--check", str(self.dirty), without_rich=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("written, and never seen", result.stdout)


class LookInPlayTests(unittest.TestCase):
    """`look`, in the program, over a real keyboard.

    `test_present.py` checks what the drawing says. This checks that a reader can
    reach it -- that the word the prompt advertises is the word `main.play()`
    dispatches, and that the loop comes back to the prompt afterwards rather than
    treating an answer that was not an option as a turn.

    It is also the only test that ties `look` to the *demo story's* item, which
    is the one that has to work: `brass_key`'s description has been in that file
    since the schema landed, waiting for a way to read it.
    """

    DEMO = REPO_ROOT / "story" / "observatory.json"

    def test_a_reader_can_look_at_what_they_are_carrying(self) -> None:
        """Walk in, pick the key up, and ask about it, then walk back out.

        The choices are by position because that is what a reader has: the
        flowerbed is the first option at the gate, and once the key is in hand
        the gate offers only two things, of which walking away is the second.
        That the positions move is not an inconvenience here -- it is the demo's
        own demonstration, and the run arriving at an ending is what says every
        one of these keystrokes went where it was meant to.
        """
        result = run_main(
            "--play",
            str(self.DEMO),
            typed=("1", "1", "look brass key", "1", "2"),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Small Brass Key", result.stdout)
        self.assertIn("Worn smooth at the bow", result.stdout)
        self.assertIn("The Road Back", result.stdout)

    def test_looking_does_not_cost_a_turn(self) -> None:
        """The prompt comes back, and the story has not moved.

        A `look` that advanced the run would be a command that quietly plays the
        game for the reader -- and the way to see it is that the same options are
        on screen after it as before.
        """
        result = run_main("--play", str(self.DEMO), typed=("1", "look", "look"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The Gate", result.stdout)
        # The gate's own options, offered twice: once before the look and once
        # after it. Anything else means the look moved something.
        self.assertGreaterEqual(result.stdout.count("Turn around and go home"), 2)


class NoPromiseOfALaterStageTests(unittest.TestCase):
    """The IOU this round came to pay, and the guard against its returning.

    The program printed `(a full linter for this arrives in week 11)` on every
    check of a story with an orphan. It was true when it was written and it is
    not true now, and a program that still says it is lying about itself -- the
    project's own fault, committed in the one place the author is most likely to
    be reading. The output is the weaker claim and the source is the stronger
    one, so both are asserted.
    """

    def test_no_output_mentions_a_later_week(self) -> None:
        """Both real stories, so the sentence cannot survive in a branch.

        `write_orphaned_story` is not used here on purpose: the IOU was printed
        on the orphan path, and it is worth checking that the story everybody
        actually runs is not the one it survived on.
        """
        for story in (SAMPLE, REPO_ROOT / "story" / "observatory.json"):
            with self.subTest(story=story.name):
                result = run_main("--check", str(story))
                self.assertNotIn("week", (result.stdout + result.stderr).lower())

    def test_the_source_no_longer_promises_one(self) -> None:
        """Any week number, not just eleven.

        A program cannot print its way out of this by rewording it: what was
        wrong was promising a stage that had not arrived, and the next such
        sentence would be written with a different number in it.
        """
        source = MAIN.read_text(encoding="utf-8").lower()

        self.assertNotIn("week 11", source)
        self.assertNotIn("in week 1", source)


if __name__ == "__main__":
    unittest.main()

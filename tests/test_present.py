"""Tests for the presenter.

A Rich layer is usually left untested, because its output is "what it looks
like". Rich removes that excuse, and this file spends it: the presenter takes its
`Console` as an argument, and `export_text` hands back everything that was drawn.
So layout, indentation, wrapping and the number printed beside an option are all
assertions. `export_text(styles=True)` goes further and returns the **real ANSI
escapes**, which turns "an aside is drawn as an aside" from a matter of taste
into a test.

**Reading the screen clears it.** `export_text` empties the record buffer unless
told otherwise, so `drawn()` is the only place this file reads it, and it takes
both forms at once. The plain form is what the reader reads; the styled one is
what the reader sees.

**What is deliberately not tested here.** Whether the prose is any good, and
whether the colours are pleasant. Those are answered by playing the game, which
is what `.\\main.py --play` is for.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest import mock

from branchline import Engine, StoryError, parse_story
from branchline.engine import Turn
from branchline.model import Ending, Item, Meta, Paragraph
from tests.fixtures import minimal_document, minimal_story

try:
    from rich.console import Console
    from rich.text import Text

    from branchline import palette
    from branchline import present as present_module
    from branchline.present import Presenter, emphasise, keys_pressed, resolve_item
except ImportError:  # pragma: no cover - an interpreter with no Rich
    # Everything Rich touches is imported inside this block, including the two
    # package modules that need it. A `from branchline import palette` further
    # down would fail when the file was *read*, and a module that cannot be
    # imported cannot skip: it takes the whole run down with it.
    Console = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    palette = None  # type: ignore[assignment]
    present_module = None  # type: ignore[assignment]
    Presenter = emphasise = keys_pressed = resolve_item = None  # type: ignore[assignment]

WIDTH = 60

#: How an ANSI escape starts. Rich writes one immediately before a styled run.
_ANSI = re.compile(r"\x1b\[([0-9;]*)m")


def codes_before(styled: str, text: str) -> set[str]:
    """The ANSI parameters that introduce `text`, as a set of strings.

    Rich marks a styled run by writing the escape just before it, so this reads
    back the style an element was actually drawn in. The set is what makes the
    assertion say the thing it means: `"3" in codes_before(...)` is "this run is
    italic", not "this run is this colour". A run drawn with no style at all
    comes back empty, which is how "the narrator is left alone" is checked.

    The search stops at the start of the run's own line. Without that, an
    unstyled line would find the previous line's closing `\\x1b[0m` and look
    styled-with-nothing rather than not styled.
    """
    index = styled.index(text)
    line_start = styled.rfind("\n", 0, index) + 1
    head = styled[line_start:index]
    opened = head.rfind("\x1b[")
    if opened == -1:
        return set()
    params = head[opened + 2 : head.index("m", opened)]
    return set() if params in ("", "0") else set(params.split(";"))


def palette_codes(style: object) -> set[str]:
    """The same, for a style the palette declares -- so a test can name a style
    rather than an escape sequence."""
    return codes_before(style.render("x"), "x")  # type: ignore[attr-defined]


@unittest.skipUnless(Console is not None, "rich is not installed")
class RichTestCase(unittest.TestCase):
    """Skipped where Rich is absent rather than fatal.

    The decorator sits on a base class so that one line covers every class in
    this file, including the ones that never build a `Console`: everything here
    reaches `present.py`, and `present.py` cannot be imported without Rich. The
    alternative -- an import that raises while the module is being read -- is
    not a skip at all. It is a suite that dies before it can report anything,
    taking the loader and engine tests down with it on an interpreter that has
    every right to run them.
    """


class PresenterTestCase(RichTestCase):
    """A presenter drawing into a string, and the helpers its tests need."""

    width = WIDTH

    def setUp(self) -> None:
        self.story = minimal_story()
        self.engine = Engine.start(self.story, seed=1)
        self.console = self.console_recording()
        self.presenter = Presenter(
            self.console, sleep=lambda seconds: None, watch=lambda: False
        )

    def console_recording(self, *typed: str) -> Console:
        """A console that is not a terminal, so nothing is typewritten.

        Every layout assertion wants this one: with the typewriter off, a styled
        run is drawn once, as a run. Under it, each character carries its own
        escape, and any assertion about a span would be an assertion about Rich.
        """
        return Console(
            file=StringIO("\n".join(typed) + "\n" if typed else ""),
            record=True,
            width=self.width,
            highlight=False,
        )

    def drawn(self) -> tuple[str, str]:
        """(what was drawn, the same with its ANSI) and clear the screen."""
        plain = self.console.export_text(clear=False)
        return plain, self.console.export_text(styles=True)

    def plain(self) -> list[str]:
        return self.drawn()[0].splitlines()

    def line_with(self, text: str) -> str:
        """The line `text` was drawn on."""
        return next(line for line in self.plain() if text in line)

    def drawn_from(self, mark: str) -> str:
        """Everything on screen from `mark` onwards, unwrapped.

        For a message longer than the console is wide, which is most of them.
        `line_with` would hand back the first line only, and `"\\n".join(...)`
        would not help either: Rich breaks a line *at* a space and keeps it, so
        a sentence that wrapped comes back as ``"...and everything \\nsince will
        be lost."`` and the phrase the test is looking for is in neither line.
        Collapsing every run of whitespace to one space is what makes the words
        on screen readable as the words that were said.
        """
        drawn = "\n".join(self.plain())
        return " ".join(drawn[drawn.index(mark) :].split())

    def prose_lines(self, marker: str) -> list[str]:
        """The lines of the last paragraph drawn, found by its first word.

        A turn draws the scene's title and rule before the prose, so "the first
        line on screen" is not the paragraph -- and a test that assumed it was
        would pass while checking the title.
        """
        lines = self.plain()
        start = next(i for i, line in enumerate(lines) if marker in line)
        return [line for line in lines[start:] if line.strip()]

    def view(self, **changes: object):
        """The scene the reader is in, with parts of it overridden."""
        return replace(self.engine.view(), **changes)

    def turn(self, **changes: object) -> None:
        """Draw arriving at the current scene, with the view adjusted."""
        self.presenter.turn(Turn(messages=(), entered=self.view(**changes)))

    def typing(self, *lines: str):
        """The reader types these lines, one per prompt, and then stops.

        The seam is the builtin `input` rather than `console.input`, because
        Rich's own `input` calls the builtin: patching the builtin leaves the
        prompt being drawn by the console, so a test can assert on it.

        **The end is sticky, because that is what end-of-input is.** A mock with
        a fixed list raises `StopIteration` once when it runs dry, which is an
        error in the harness; a real stream keeps saying so, and `builtins.input`
        keeps raising `EOFError`. The difference is not academic here: `load`
        reads a *second* time to confirm, so a reader who answers `load` and then
        stops has one more `input()` coming, and the two models disagree about
        what it returns. The one that matters is the one a terminal does.
        """
        pending = list(lines)

        def read(prompt: str = "") -> str:
            if pending:
                return pending.pop(0)
            raise EOFError

        return mock.patch("builtins.input", side_effect=read)

    # -- at the prompt ------------------------------------------------------
    #
    # On the base rather than on one class, because the tests for the two words
    # are a separate class from the tests for a number and they ask the same way.

    def answer(self, *typed: str, can_load: bool = False) -> None:
        """Ask, with the reader typing these lines. Leaves the reply in `self.reply`."""
        with self.typing(*typed):
            self.reply = self.presenter.ask(self.engine, can_load=can_load)

    def chosen(self) -> int | None:
        """The option number they landed on, if they landed on one."""
        return self.reply.number if self.reply is not None else None


class TitleTests(PresenterTestCase):
    def test_a_scene_title_is_drawn_with_a_rule_under_it(self) -> None:
        self.turn()
        lines = self.plain()
        title = self.view().title
        self.assertIn("  " + title, lines)
        self.assertEqual(lines[lines.index("  " + title) + 1], "  " + "─" * len(title))

    def test_the_rule_is_the_width_of_the_title_and_not_of_the_screen(self) -> None:
        """A fixed-width rule is what this replaced.

        A title that grows past a constant somebody chose months ago leaves the
        rule either wrapping under it or stopping short of the words it is meant
        to be underlining.
        """
        for title in ("Lit", "The Cellar, Revisited, And Longer Than Sixty"):
            with self.subTest(title=title):
                self.setUp()
                self.turn(title=title)
                lines = self.plain()
                self.assertEqual(lines[lines.index("  " + title) + 1], "  " + "─" * len(title))

    def test_the_title_is_set_in_the_palette_s_title_style(self) -> None:
        self.turn()
        _, styled = self.drawn()
        self.assertEqual(
            codes_before(styled, self.view().title), palette_codes(palette.TITLE)
        )

    def test_the_rule_under_it_is_not_the_same_style_as_the_title(self) -> None:
        """Two things drawn identically are one thing drawn twice."""
        self.turn()
        _, styled = self.drawn()
        self.assertNotEqual(
            codes_before(styled, "─"),
            codes_before(styled, self.view().title),
        )


class ProseTests(PresenterTestCase):
    def test_body_prose_is_set_in_from_the_edge(self) -> None:
        self.turn(body=(Paragraph("A draught moves under the door."),))
        self.assertEqual(
            self.line_with("A draught"),
            " " * palette.PROSE_INDENT + "A draught moves under the door.",
        )

    def test_body_prose_is_left_completely_alone(self) -> None:
        """The narrator is the terminal's own default.

        This is the commonest text on the screen, and styling it would mean the
        story's ordinary sentences arrived in a colour the reader did not choose
        -- on a terminal whose colours they did choose.
        """
        body = "A draught moves under the door."
        self.turn(body=(Paragraph(body),))
        plain, styled = self.drawn()
        self.assertIn(body, plain)
        self.assertEqual(codes_before(styled, body), set())

    def test_a_register_is_set_in_further_than_the_narrator(self) -> None:
        aside = "someone has been here tonight."
        self.turn(body=(Paragraph(aside, style="aside"),))
        self.assertEqual(
            self.line_with(aside), " " * palette.REGISTER_INDENT + aside
        )

    def test_an_aside_is_italic_and_the_narrator_is_not(self) -> None:
        """The whole of "an aside reads as an aside", asserted.

        Italic is the part that carries it: indentation says "not the narrator",
        and colour says which register. On a terminal with no colour -- or one
        the reader configured -- italic is what is left.
        """
        aside = "someone has been here tonight."
        self.turn(body=(Paragraph(aside, style="aside"),))
        _, styled = self.drawn()
        self.assertIn("3", codes_before(styled, aside))

    def test_every_register_is_drawn_differently(self) -> None:
        body = tuple(
            Paragraph(f"a line in the {name} register", style=name)
            for name in sorted(palette.REGISTER_STYLES)
        )
        self.turn(body=body)
        _, styled = self.drawn()
        seen: dict[frozenset[str], str] = {}
        for paragraph in body:
            codes = frozenset(codes_before(styled, paragraph.text))
            with self.subTest(register=paragraph.style):
                self.assertNotIn(codes, seen, f"looks the same as {seen.get(codes)}")
                seen[codes] = str(paragraph.style)

    def test_each_register_is_drawn_in_the_style_the_palette_gives_it(self) -> None:
        """The wiring, not the colours: the presenter must ask the palette."""
        body = tuple(
            Paragraph(f"a line in the {name} register", style=name)
            for name in sorted(palette.REGISTER_STYLES)
        )
        self.turn(body=body)
        _, styled = self.drawn()
        for paragraph in body:
            with self.subTest(register=paragraph.style):
                self.assertEqual(
                    codes_before(styled, paragraph.text),
                    palette_codes(palette.REGISTER_STYLES[str(paragraph.style)]),
                )

    def test_a_blank_line_separates_two_paragraphs(self) -> None:
        """Without it the body and the aside run together into one block, and the
        register stops reading as a change of voice."""
        self.turn(body=(Paragraph("A draught."), Paragraph("Then nothing.", style="aside")))
        lines = self.plain()
        body = next(i for i, line in enumerate(lines) if "A draught." in line)
        self.assertEqual(lines[body + 1], "")
        self.assertIn("Then nothing.", lines[body + 2])

    def test_a_paragraph_longer_than_the_screen_is_wrapped(self) -> None:
        self.turn(body=(Paragraph("word " * 40),))
        lines = self.prose_lines("word")
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(len(line), self.width)

    def test_the_continuation_lines_are_set_in_too(self) -> None:
        """The bug the per-line indent exists to prevent.

        Indenting the paragraph once leaves the second line hard against the left
        margin, so a set-in paragraph stops being set in halfway down.
        """
        self.turn(body=(Paragraph("word " * 40, style="aside"),))
        for line in self.prose_lines("word"):
            with self.subTest(line=line):
                self.assertTrue(line.startswith(" " * palette.REGISTER_INDENT))

    def test_wrapping_does_not_lose_any_words(self) -> None:
        """A terminal that silently ate half a paragraph would be worse than one
        that drew it badly."""
        story = "the dome turns and the shutters follow it all night long " * 4
        self.turn(body=(Paragraph(story.strip()),))
        rejoined = " ".join(line.strip() for line in self.prose_lines("the dome"))
        self.assertEqual(rejoined, story.strip())

    def test_a_console_narrower_than_the_indent_does_not_break_the_wrapping(self) -> None:
        """A wrapping width of zero or less is not a width at all.

        `_lines` subtracts the indent from the console's width, so on a terminal
        narrower than the indent that subtraction goes negative -- and handing
        Rich a negative width to wrap into is how a paragraph ends up drawn one
        character per line. There is a floor under it, and this is the floor.
        """
        self.console = Console(file=StringIO(), record=True, width=4, highlight=False)
        self.presenter.console = self.console
        lines = self.presenter._lines(Text("a word or two"), palette.REGISTER_INDENT)
        self.assertEqual([line.plain for line in lines], ["    a word or two"])

    def test_a_register_that_does_not_exist_stops_the_program(self) -> None:
        """Rather than falling back to the narrator.

        The loader rejects an unknown register, so this can only be reached by a
        story that has not been through it -- a hand-built one, in a test. A
        silent fallback would render the paragraph as ordinary prose and take
        away the only evidence that anything had gone wrong.
        """
        with self.assertRaises(KeyError):
            self.turn(body=(Paragraph("it is not what it says", style="nonsense"),))


class AskingTests(PresenterTestCase):
    def test_the_options_are_drawn_with_the_number_the_reader_presses(self) -> None:
        self.answer("1")
        drawn = "\n".join(self.plain())
        for option in self.engine.options():
            with self.subTest(option=option.number):
                self.assertIn(f"▸ {option.number}. {option.text}", drawn)

    def test_the_options_are_numbered_without_a_gap(self) -> None:
        """A gap is a key that does nothing when pressed, which in a terminal is
        indistinguishable from a broken program."""
        self.answer("1")
        drawn = [
            int(match.group(1))
            for line in self.plain()
            if (match := re.search(r"▸ (\d+)\.", line))
        ]
        self.assertEqual(drawn, list(range(1, len(drawn) + 1)))

    def test_a_number_chooses_that_option(self) -> None:
        self.answer("2")
        self.assertEqual(self.chosen(), 2)

    def test_a_number_is_never_a_command(self) -> None:
        """The two kinds of answer are exclusive. A `Reply` carrying both would
        make the branch taken depend on which field `main` happened to read."""
        self.answer("1")
        self.assertIsNone(self.reply.command)

    def test_surrounding_space_is_not_part_of_the_answer(self) -> None:
        self.answer("  2  ")
        self.assertEqual(self.chosen(), 2)

    def test_something_that_is_not_a_number_is_asked_again(self) -> None:
        self.answer("what?", "1")
        self.assertEqual(self.chosen(), 1)
        self.assertIn("is not one of the options here", self.drawn()[0])

    def test_a_character_the_reader_cannot_see_is_not_an_answer(self) -> None:
        """The fault this was written for, and it is not hypothetical.

        PowerShell 5.1 puts a byte-order mark on the first line of a pipe, and
        `.strip()` does not remove one. A scripted demo would lose its first
        answer and shift every keypress by one, which looks exactly like an
        engine bug and is not one.
        """
        self.answer("﻿1")
        self.assertEqual(self.chosen(), 1)

    def test_a_bare_enter_is_not_worth_explaining(self) -> None:
        """Someone leaning on the return key should not be told they typed
        something wrong -- and the message would have to quote an empty string
        back at them, which reads as a fault in the program."""
        self.answer("", "1")
        self.assertEqual(self.chosen(), 1)
        self.assertNotIn("is not one of the options here", self.drawn()[0])

    def test_leaving_is_not_an_error(self) -> None:
        """Ctrl+Z then Enter in PowerShell. Without this the reader gets a
        traceback, which is a wall of noise for someone who simply stopped."""
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertIsNone(self.presenter.ask(self.engine))

    def test_the_reader_is_prompted_rather_than_left_to_guess(self) -> None:
        self.answer("1")
        self.assertIn(">", self.drawn()[0])

    def test_being_told_they_typed_something_wrong_still_says_how_to_leave(self) -> None:
        """The one message a reader is looking at when they are already looking
        for the way out."""
        self.answer("what?", "1")
        self.assertIn("Ctrl+Z", self.drawn()[0])

    # -- the words ----------------------------------------------------------
    #
    # They are commands the *program* answers, not options the story offers, so
    # the engine never hears about them. These tests hold that line: if `save`
    # ever came back as a number, `engine.take()` would be handed it. `look` is
    # in the tuple for the opposite reason as well -- it is answered from what is
    # already on screen, so the engine has nothing to be asked.

    def test_save_is_a_command_and_not_an_option(self) -> None:
        self.answer("save")
        self.assertEqual(self.reply.command, "save")
        self.assertIsNone(self.reply.number)

    def test_load_is_a_command_and_not_an_option(self) -> None:
        self.answer("load", "yes", can_load=True)
        self.assertEqual(self.reply.command, "load")
        self.assertIsNone(self.reply.number)

    def test_the_words_are_read_however_they_are_typed(self) -> None:
        """A reader who types `Save` meant the command. Refusing on case would be
        the program being pedantic about something it understood perfectly."""
        for typed in ("Save", "SAVE", "sAvE"):
            with self.subTest(typed=typed):
                self.answer(typed)
                self.assertEqual(self.reply.command, "save")

    def test_the_prompt_says_which_words_exist(self) -> None:
        """A command nobody can find is not a feature.

        Asserted as one line rather than as three words somewhere on the screen,
        because "quietly, where the prompt is" is the claim -- and a `look` that
        was only ever mentioned by a refusal would satisfy the weaker version.

        Driven from `COMMANDS` rather than listing the words here, because the
        point of the tuple is that the prompt line and this assertion cannot
        disagree about what the reader can type. A fourth word added to the tuple
        and forgotten in the prompt fails this test by name.
        """
        self.answer("1")
        line = self.line_with("or a number")
        for word in present_module.COMMANDS:
            with self.subTest(word=word):
                self.assertIn(word, line)

    def test_a_near_miss_is_told_what_can_be_typed(self) -> None:
        """`sav` must not be swallowed, and must not be read as option 0.

        The refusal is built from `COMMANDS` too, which is the half that used to
        be wrong: it named the words by hand one screen below an unused tuple
        listing them, so a third word would have appeared on the prompt and not
        here.
        """
        self.answer("sav", "1")
        said = self.drawn_from("is not one of the options here")
        for word in present_module.COMMANDS:
            with self.subTest(word=word):
                self.assertIn(word, said)


class LoadingTests(PresenterTestCase):
    """The one command that throws a run away, and the consent it needs first."""

    def test_load_asks_before_it_throws_a_run_away(self) -> None:
        self.answer("load", "yes", can_load=True)
        self.assertIn("everything since will be lost", self.drawn_from("This will put you back"))

    def test_anything_other_than_yes_is_a_no(self) -> None:
        for typed in ("y", "no", "sure", "Yes please"):
            with self.subTest(typed=typed):
                self.answer("load", typed, "1", can_load=True)
                self.assertIsNone(self.reply.command)
                self.assertIn("Nothing was loaded", self.drawn()[0])

    def test_running_out_of_input_is_not_agreement(self) -> None:
        """A piped run whose answers end exactly at a `load` has consented to
        nothing. Reading silence as consent would make the last line of a script
        destroy the run it was checking.

        And because the end of input does not stop being the end, the run then
        finishes rather than looping -- which is the same thing that happens to
        a reader who presses Ctrl+Z to answer the confirmation.
        """
        self.answer("load", can_load=True)
        self.assertIsNone(self.reply)

    def test_a_no_asks_again_rather_than_counting_as_a_mistake(self) -> None:
        self.answer("load", "no", "1", can_load=True)
        self.assertEqual(self.chosen(), 1)

    def test_load_with_nothing_saved_says_so_and_asks_nothing(self) -> None:
        """Asking a reader to confirm losing a run, and only then telling them
        there is nothing to go back to, is the wrong order."""
        self.answer("load", "1", can_load=False)
        self.assertEqual(self.chosen(), 1)
        drawn = self.drawn()[0]
        self.assertIn("Nothing is saved yet", drawn)
        self.assertNotIn("everything since will be lost", drawn)

    def test_saving_says_where_it_went(self) -> None:
        """The path is the one thing the reader cannot work out, and naming it is
        also how they learn an earlier save has just been replaced.

        Asserted against `str(Path(...))` rather than against a written-out
        `saves/observatory.save`, because this suite runs on Windows too and
        there the separator is a backslash -- a test hard-coding a forward slash
        would be asserting the platform, not the message.
        """
        path = Path("saves") / "observatory.save"
        self.presenter.saved(path)
        self.assertIn(f"Saved to {path}.", self.line_with("Saved to"))

    def test_a_save_that_will_not_load_leaves_the_run_alone(self) -> None:
        """Not a crash, and not a half-applied state either -- so the last thing
        said is what did *not* happen."""
        self.presenter.refused(
            StoryError("this file is not a save", path="saves/observatory.save")
        )
        drawn = "\n".join(self.plain())
        self.assertIn("this file is not a save", drawn)
        self.assertIn("The run in progress was left alone.", drawn)

    def test_a_load_draws_the_room_again_with_nothing_said_on_the_way(self) -> None:
        """Entering a scene is what runs its `on_enter` and produces its
        messages. A resumed run deliberately does not re-enter, so there are no
        messages -- and drawing the room without them is the correct picture.

        The fixture's `hall` says something on entry, so "no messages" is a
        claim this test can actually see. Without the `assertNotIn` it would pass
        for a presenter that drew them.
        """
        view = self.view()
        self.presenter.loaded(Engine.resume(self.story, self.engine.state))
        drawn = "\n".join(self.plain())
        self.assertIn(view.title, drawn)
        self.assertIn(view.body[0].text, drawn)
        self.assertNotIn("A bell rings once, somewhere below.", drawn)
        self.assertNotIn("Nothing moves.", drawn)

    def test_a_load_restates_the_seed(self) -> None:
        """The number at the top of the screen belonged to the run just thrown
        away. Leaving it there would be a false statement about the run being
        played -- and it is the one piece of state that screen advertises."""
        resumed = Engine.resume(self.story, self.engine.state)
        self.presenter.loaded(resumed)
        self.assertIn(f"seed {resumed.state.seed}", self.line_with("Loaded"))

    def test_leaving_does_not_promise_a_later_week(self) -> None:
        """The sentence this replaced said saving arrived in week 10.

        Week 10 arrived and the sentence went with it, and a program that still
        says such a thing is lying about itself. **Generalised to any week
        number**, not to ten: what was wrong was promising a stage that had not
        arrived, and the next such sentence would be written with a different
        number in it -- which is not hypothetical, because this project has now
        written one twice.
        """
        self.presenter.stopped()
        drawn = self.drawn()[0]
        self.assertIn("Left where it stands.", drawn)
        self.assertIn("save", drawn)
        self.assertNotIn("week", drawn.lower())


class LockedChoiceTests(PresenterTestCase):
    """The option is visible and pressable; it just refuses."""

    LOCKED_OPTION = "Use the brass key"

    def test_a_locked_option_keeps_its_number(self) -> None:
        """Dropping it from the list would renumber everything under the reader's
        fingers between one turn and the next."""
        with self.typing("1"):
            self.presenter.ask(self.engine)
        line = next(line for line in self.plain() if self.LOCKED_OPTION in line)
        self.assertIn("▸ 2.", line)

    def test_a_locked_option_is_dimmed(self) -> None:
        with self.typing("1"):
            self.presenter.ask(self.engine)
        _, styled = self.drawn()
        self.assertEqual(
            codes_before(styled, self.LOCKED_OPTION),
            palette_codes(palette.LOCKED),
        )

    def test_a_locked_option_and_an_open_one_do_not_look_alike(self) -> None:
        with self.typing("1"):
            self.presenter.ask(self.engine)
        _, styled = self.drawn()
        self.assertNotEqual(
            codes_before(styled, self.LOCKED_OPTION),
            codes_before(styled, "Step into the workshop"),
        )

    def test_a_locked_option_says_why_beneath_itself(self) -> None:
        with self.typing("1"):
            self.presenter.ask(self.engine)
        lines = self.plain()
        option = next(i for i, line in enumerate(lines) if self.LOCKED_OPTION in line)
        hint = lines[option + 1].strip()
        self.assertEqual(hint, "you would need something small and metal")

    def test_the_reason_is_set_in_further_than_the_option_it_explains(self) -> None:
        """Or it reads as the next option rather than as a note about this one."""
        with self.typing("1"):
            self.presenter.ask(self.engine)
        lines = self.plain()
        option = next(i for i, line in enumerate(lines) if self.LOCKED_OPTION in line)
        self.assertEqual(len(lines[option + 1]) - len(lines[option + 1].lstrip()), palette.HINT_INDENT)

    def test_the_reason_is_quieter_than_the_option(self) -> None:
        with self.typing("1"):
            self.presenter.ask(self.engine)
        _, styled = self.drawn()
        self.assertEqual(
            codes_before(styled, "you would need something small and metal"),
            palette_codes(palette.LOCKED_HINT),
        )


class StatusLineTests(PresenterTestCase):
    def test_only_the_variables_marked_for_the_status_line_are_shown(self) -> None:
        """`hud: true` is the author asking for this. A variable without it is
        bookkeeping, and the reader should not be handed the workings."""
        with self.typing("1"):
            self.presenter.ask(self.engine)
        drawn = self.drawn()[0]
        self.assertIn(self.status("lamps_lit"), drawn)
        self.assertNotIn("trusted", drawn)
        self.assertNotIn("mood", drawn)

    def status(self, name: str) -> str:
        """The status line as it should read for a variable, right now.

        Built from the engine rather than written as a number, because the value
        is not what is being tested -- whether the presenter reads the value that
        is there is.
        """
        return f"{self.engine.story.variables[name].label} {self.engine.state.variables[name]}"

    def test_the_label_is_used_and_not_the_internal_name(self) -> None:
        """`lamps_lit` is the author's shorthand; `lamps lit` is the words."""
        with self.typing("1"):
            self.presenter.ask(self.engine)
        self.assertNotIn("lamps_lit", self.drawn()[0])

    def test_the_status_line_shows_what_is_true_now(self) -> None:
        """Not what was true when the story started. It is a status line."""
        with self.typing("1"):
            self.presenter.ask(self.engine)
        self.assertEqual(self.engine.state.variables["lamps_lit"], 3)
        self.assertIn(self.status("lamps_lit"), self.drawn()[0])

    def test_a_boolean_is_shown_as_a_word_and_not_as_python(self) -> None:
        """`engine.hud()` hands over raw values on purpose -- "turning `True` into
        `yes` is a presentation decision" -- so this is the layer that owns it.
        Without it the reader is shown `True`, which is not a word anybody wrote.
        """
        for initial, expected, unwanted in ((True, "yes", "True"), (False, "no", "False")):
            with self.subTest(initial=initial):
                document = minimal_document()
                # A variable marked for the status line needs a label to be
                # shown under -- the loader refuses one without, and rightly: the
                # alternative is the reader being shown `trusted`.
                document["variables"]["trusted"].update(
                    hud=True, label="trusted", initial=initial
                )
                self.setUp()
                self.engine = Engine.start(parse_story(document), seed=1)
                with self.typing("1"):
                    self.presenter.ask(self.engine)
                drawn = self.drawn()[0]
                self.assertIn(f"trusted {expected}", drawn)
                self.assertNotIn(unwanted, drawn)

    def test_what_the_reader_is_carrying_is_a_quiet_line(self) -> None:
        self.engine.take(1)  # the workshop, where the key is taken
        with self.typing("1"):
            self.presenter.ask(self.engine)
        self.assertIn("carrying: Small Brass Key", self.drawn()[0])

    def test_carrying_nothing_means_saying_nothing(self) -> None:
        """A line reading "carrying:" with nothing after it is furniture."""
        with self.typing("1"):
            self.presenter.ask(self.engine)
        self.assertNotIn("carrying", self.drawn()[0])

    def test_the_item_is_named_the_way_the_author_named_it(self) -> None:
        """`brass_key` is the id the story refers to it by, not what it is
        called."""
        self.engine.take(1)
        with self.typing("1"):
            self.presenter.ask(self.engine)
        self.assertNotIn("brass_key", self.drawn()[0])


class EndingTests(PresenterTestCase):
    def ending(self, kind: str) -> Ending:
        return Ending(
            id="somewhere", title="What Was Written", kind=kind, epilogue=(Paragraph("It is over."),)
        )

    def test_the_ending_is_ruled_off_from_what_came_before(self) -> None:
        self.presenter.ending(self.ending("warm"))
        self.assertEqual(self.plain()[0], " " * palette.PROSE_INDENT + "─" * (self.width - palette.PROSE_INDENT))

    def test_the_rule_reaches_the_edge_of_the_screen(self) -> None:
        """The one full-width thing in the layout. It is what says the story has
        stopped rather than paused."""
        self.presenter.ending(self.ending("warm"))
        self.assertEqual(len(self.plain()[0]), self.width)

    def test_each_mood_lands_in_its_own_colour(self) -> None:
        seen: dict[frozenset[str], str] = {}
        for kind in sorted(palette.ENDING_STYLES):
            with self.subTest(mood=kind):
                self.setUp()
                self.presenter.ending(self.ending(kind))
                styled = self.drawn()[1]
                codes = frozenset(codes_before(styled, "What Was Written"))
                self.assertEqual(
                    set(codes), palette_codes(palette.ENDING_STYLES[kind])
                )
                self.assertNotIn(codes, seen, f"looks the same as {seen.get(codes)}")
                seen[codes] = kind

    def test_the_title_carries_weight_and_not_only_colour(self) -> None:
        """Colour alone assumes a terminal that shows it."""
        self.presenter.ending(self.ending("bitter"))
        styled = self.drawn()[1]
        self.assertIn("1", codes_before(styled, "What Was Written"))

    def test_the_epilogue_follows_the_title(self) -> None:
        self.presenter.ending(self.ending("warm"))
        lines = self.plain()
        title = lines.index("  What Was Written")
        self.assertIn("It is over.", "\n".join(lines[title:]))


class OpeningTests(PresenterTestCase):
    def meta(self, **changes: object) -> Meta:
        return replace(self.story.meta, **changes)

    def test_the_title_card_names_the_story_and_who_wrote_it(self) -> None:
        self.presenter.opening(self.meta(), 7)
        drawn = self.drawn()[0]
        self.assertIn("Fixture", drawn)
        self.assertIn("by the test suite", drawn)
        self.assertIn("a story that exists only to be loaded", drawn)

    def test_the_seed_is_shown_so_that_a_run_can_be_reproduced(self) -> None:
        """Which is what it is for: "something odd happened" can be answered with
        a number."""
        self.presenter.opening(self.meta(), 7)
        self.assertIn("seed 7", self.drawn()[0])

    def test_a_title_card_paragraph_may_be_written_in_a_register(self) -> None:
        """It is prose like any other, and a register the presenter ignored here
        would be a `style` the author wrote that never took effect."""
        self.presenter.opening(
            self.meta(title_card=(Paragraph("Quietly now.", style="whisper"),)), 1
        )
        _, styled = self.drawn()
        self.assertEqual(
            codes_before(styled, "Quietly now."),
            palette_codes(palette.REGISTER_STYLES["whisper"]),
        )

    def test_the_title_card_is_not_typewritten(self) -> None:
        """It is on screen before the story starts, and nobody should have to wait
        for the front matter."""
        slept: list[float] = []
        console = Console(file=StringIO(), record=True, width=self.width, force_terminal=True)
        presenter = Presenter(console, sleep=slept.append, watch=lambda: False)
        self.assertTrue(presenter.reveals)
        presenter.opening(self.meta(), 1)
        self.assertEqual(slept, [])


class NoteTests(PresenterTestCase):
    def test_a_refusal_is_set_off_from_what_is_around_it(self) -> None:
        """What follows a refusal is the whole set of options again, and without
        the blank the explanation reads as the first item of the list it is
        apologising for."""
        self.presenter.note("There is no option 9.")
        lines = self.plain()
        self.assertEqual(lines[0], "")
        self.assertEqual(lines[1], "  There is no option 9.")
        self.assertEqual(lines[2], "")

    def test_leaving_says_that_nothing_is_being_saved(self) -> None:
        self.presenter.stopped()
        self.assertIn("Left where it stands.", self.drawn()[0])

    def test_a_refusal_that_wraps_over_two_lines_is_still_one_note(self) -> None:
        self.presenter.note("first\nsecond")
        lines = self.plain()
        self.assertIn("  first", lines)
        self.assertIn("  second", lines)


class EmphasisTests(PresenterTestCase):
    """`*surrounded by stars*`, which STORY_FORMAT.md promises to authors."""

    def test_the_stars_are_markers_and_are_not_shown(self) -> None:
        self.turn(body=(Paragraph("the *dome* turns"),))
        self.assertIn("the dome turns", self.drawn()[0])
        self.assertNotIn("*", self.drawn()[0])

    def test_the_words_between_the_stars_are_marked(self) -> None:
        self.turn(body=(Paragraph("the *dome* turns"),))
        _, styled = self.drawn()
        self.assertTrue(codes_before(styled, "dome"))

    def test_emphasis_is_visible_inside_every_register(self) -> None:
        """Bold alone would disappear inside a `sign`, which is already bold --
        and italic alone would disappear inside an `aside`, which already is.
        That is the whole argument for the pair, and it is checked here against
        the drawn output rather than against the palette."""
        for name in sorted(palette.REGISTER_STYLES):
            with self.subTest(register=name):
                self.setUp()
                self.turn(body=(Paragraph("on the *hillside*", style=name),))
                _, styled = self.drawn()
                plain_codes = palette_codes(palette.REGISTER_STYLES[name])
                marked = codes_before(styled, "hillside")
                self.assertNotEqual(marked, plain_codes)
                self.assertTrue(marked - plain_codes)

    def test_two_stars_around_something_else_are_left_alone(self) -> None:
        """Prose is allowed to contain an asterisk, and `2 * 3 * 4` is the shape
        that catches a careless rule."""
        self.assertEqual(emphasise("2 * 3 * 4", palette.BODY).plain, "2 * 3 * 4")

    def test_an_unmatched_star_is_left_alone(self) -> None:
        """A story about an observatory is allowed to contain a star."""
        self.assertEqual(emphasise("a lone * star", palette.BODY).plain, "a lone * star")

    def test_a_whole_paragraph_can_be_marked(self) -> None:
        self.assertEqual(emphasise("*nothing moves*", palette.BODY).plain, "nothing moves")

    def test_square_brackets_are_characters_and_not_markup(self) -> None:
        """`Text.from_markup` would swallow these. Story prose is not markup and
        must never be parsed as any -- an author writing `[the dome]` means
        exactly that."""
        self.assertEqual(
            emphasise("[the dome] and [bold] red", palette.BODY).plain,
            "[the dome] and [bold] red",
        )


class ResolveItemTests(RichTestCase):
    """Matching what the reader typed to what they are carrying.

    Deliberately not a `PresenterTestCase`: this is a pure function over items,
    so it is tested with no screen, no story and no engine. That it *can* be is
    the argument for the matcher being a module-level function rather than a
    method on the engine -- see `resolve_item`'s docstring.
    """

    KEY = Item(id="brass_key", name="Small Brass Key", description="Cold.", art="( o )")
    RING = Item(id="brass_ring", name="Brass Ring", description="Thin.")
    CAN = Item(id="oil_can", name="Oil Can", description="Half full.")

    def test_the_whole_name_matches(self) -> None:
        self.assertEqual(resolve_item((self.KEY,), "Small Brass Key"), (self.KEY,))

    def test_case_is_not_part_of_the_answer(self) -> None:
        """Refusing on case would be the program being pedantic about something
        it understood perfectly -- the same rule the commands are read under."""
        self.assertEqual(resolve_item((self.KEY,), "small brass key"), (self.KEY,))

    def test_the_id_is_accepted_with_its_underscores_turned_into_spaces(self) -> None:
        """Nothing displays the id. It is still what the author wrote, and the
        premise of the project is that the author is the one reading the file."""
        self.assertEqual(resolve_item((self.KEY,), "brass key"), (self.KEY,))

    def test_a_run_of_spaces_is_one_space(self) -> None:
        self.assertEqual(resolve_item((self.KEY,), "  small   brass  key  "), (self.KEY,))

    def test_a_name_that_begins_with_the_words_matches(self) -> None:
        self.assertEqual(resolve_item((self.KEY,), "small"), (self.KEY,))

    def test_a_word_from_the_middle_of_the_name_does_not_match(self) -> None:
        """**The sharp edge of prefix matching, written down so it stays put.**

        `key` is a word in `Small Brass Key` and a reader will certainly try it.
        It does not match, because the rule is "what this begins with" and not
        "what this contains" -- and the alternative has no floor: `a` occurs in
        nearly every name an author writes, so a contains-rule turns most
        questions into an ambiguity or, worse, matches something the reader never
        named.

        The way out is the item's `name`, which the reader is shown in the
        `carrying:` line every turn, and its id's words, which is what the author
        wrote. Both are things they can see; a fragment out of the middle is not.
        """
        self.assertEqual(resolve_item((self.KEY,), "key"), ())

    def test_an_exact_match_wins_over_a_name_that_merely_begins_differently(self) -> None:
        """Round one before round two, or `brass ring` would also drag in the key."""
        self.assertEqual(
            resolve_item((self.RING, self.KEY), "brass ring"), (self.RING,)
        )

    def test_two_matches_come_back_together_and_in_the_order_carried(self) -> None:
        """"brass" is two things here, and the program does not get to pick.

        Both by the name and by the id: the key's id-words begin with it, and the
        ring's name does.
        """
        self.assertEqual(
            resolve_item((self.KEY, self.RING), "brass"), (self.KEY, self.RING)
        )
        self.assertEqual(
            resolve_item((self.RING, self.KEY), "brass"), (self.RING, self.KEY)
        )

    def test_nothing_matched_is_empty(self) -> None:
        self.assertEqual(resolve_item((self.KEY,), "telescope"), ())

    def test_an_empty_question_matches_everything_and_therefore_nothing(self) -> None:
        """`look ` with a trailing space is a bare `look`, not a request for the
        whole inventory under a different name."""
        self.assertEqual(resolve_item((self.KEY,), "   "), ())

    def test_an_item_that_does_not_match_does_not_drag_in_a_match(self) -> None:
        self.assertEqual(resolve_item((self.KEY, self.CAN), "small"), (self.KEY,))


class LookTests(PresenterTestCase):
    """The command that makes `Item.description` and `Item.art` take effect.

    `STORY_FORMAT.md` has told authors since the schema landed that
    `description` is "what the reader is told when they look". Until this round
    there was no way to look, so every description in every story file was prose
    written that never took effect -- the cardinal sin of this project, committed
    by the schema itself.
    """

    NAME = "Small Brass Key"
    ART = "( o )"
    DESCRIPTION = "Cold, and worn smooth at the bow."

    def workshop(self, document: dict | None = None) -> None:
        """Stand in the workshop, which is where the fixture hands the key over.

        `document` is for the tests that need to be holding something the
        fixture's key cannot show them -- an item with no `art`, an item with no
        `description`, or a second thing whose name shares a word with the first.
        Replacing the document wholesale is clearer than fighting the fixture,
        and the fixture's job is exercising the schema rather than being a story.
        """
        self.engine = Engine.start(parse_story(document or minimal_document()), seed=1)
        for option in self.engine.options():
            if option.text == "Step into the workshop":
                self.engine.take(option.number)
                return
        raise AssertionError("the fixture no longer offers a way to the workshop")

    def looked(self, subject: str | None = None) -> tuple[str, str]:
        self.presenter.looked(self.engine, subject)
        return self.drawn()

    # -- bare `look` --------------------------------------------------------

    def test_bare_look_lists_what_is_in_hand(self) -> None:
        self.workshop()
        drawn = self.looked()[0]
        self.assertIn("You are carrying:", drawn)
        self.assertIn(self.NAME, drawn)

    def test_bare_look_lists_one_thing_per_line(self) -> None:
        """A comma-separated run is a summary; this is the answer to a question."""
        document = minimal_document()
        document["items"]["brass_ring"] = {"name": "Brass Ring", "description": "Thin."}
        document["scenes"]["workshop"]["on_enter"] = [
            {"take": "brass_key"},
            {"take": "brass_ring"},
        ]
        self.workshop(document)

        lines = [line.strip() for line in self.looked()[0].splitlines()]

        self.assertIn(self.NAME, lines)
        self.assertIn("Brass Ring", lines)

    def test_bare_look_with_empty_hands_says_so(self) -> None:
        """Said, not drawn as a heading with nothing under it."""
        drawn = self.looked()[0]
        self.assertIn("You are carrying nothing.", drawn)
        self.assertNotIn("You are carrying:", drawn)

    # -- looking at one thing ----------------------------------------------

    def test_looking_at_something_shows_its_name_its_picture_and_its_words(self) -> None:
        self.workshop()
        drawn = self.looked("brass key")[0]
        self.assertIn(self.NAME, drawn)
        self.assertIn(self.ART, drawn)
        self.assertIn(self.DESCRIPTION, drawn)

    def test_the_thing_is_named_the_way_the_author_named_it(self) -> None:
        """`brass_key` is what the story file calls it, not what it is called."""
        self.workshop()
        self.assertNotIn("brass_key", self.looked("brass key")[0])

    def test_the_picture_is_drawn_on_its_own_line_under_the_name(self) -> None:
        self.workshop()
        lines = [line.strip() for line in self.looked("brass key")[0].splitlines()]
        self.assertEqual(lines[lines.index(self.ART) - 1], self.NAME)

    def test_the_name_and_the_picture_are_warm_and_weighed(self) -> None:
        """The palette's own rule: warmth is spent on things that were *made*.

        Asked for by one word rather than by the whole name, which is also the
        only test that reaches for something through the presenter by prefix.
        """
        self.workshop()
        _, styled = self.looked("small")
        self.assertEqual(
            codes_before(styled, self.NAME), palette_codes(palette.ITEM_NAME)
        )
        self.assertEqual(
            codes_before(styled, self.ART), palette_codes(palette.ITEM_ART)
        )

    def test_the_description_is_left_to_the_narrator(self) -> None:
        """A description is prose the author wrote about a thing, and prose is
        the terminal's own default colour -- the commonest text on the screen is
        the one thing the palette does not touch."""
        self.workshop()
        _, styled = self.looked("brass key")
        self.assertEqual(codes_before(styled, "Cold, and worn smooth"), set())

    def test_the_description_is_prose_and_not_a_label(self) -> None:
        """It goes through the paragraph path, so emphasis works inside it --
        which is the difference between the words an author wrote and a name."""
        document = minimal_document()
        document["items"]["brass_key"]["description"] = "Cold, and *worn* smooth."
        self.workshop(document)

        drawn = self.looked("brass key")[0]

        self.assertIn("Cold, and worn smooth.", drawn)
        self.assertNotIn("*", drawn)

    def test_an_item_with_no_picture_draws_no_line_for_one(self) -> None:
        """`art` is optional, and an absent one is not an error."""
        document = minimal_document()
        document["scenes"]["workshop"]["on_enter"] = [{"take": "oil_can"}]
        self.workshop(document)

        drawn = self.looked("oil")[0]

        self.assertIn("Oil Can", drawn)
        self.assertIn("Half full, and older than the stair.", drawn)
        self.assertNotIn(self.ART, drawn)

    def test_an_item_with_no_description_is_still_named(self) -> None:
        """Declining to answer a question it can answer would be worse than
        answering it briefly. `description` is documented as optional."""
        document = minimal_document()
        del document["items"]["oil_can"]["description"]
        document["scenes"]["workshop"]["on_enter"] = [{"take": "oil_can"}]
        self.workshop(document)

        drawn = self.looked("oil")[0]

        self.assertIn("Oil Can", drawn)

    def test_an_asterisk_in_a_picture_is_a_character(self) -> None:
        """**Why `art` is not run through the emphasis rule.**

        A picture is drawn as written. `*.*` is a five-pointed star to the author
        who typed it, and the ordinary prose path would eat the stars and show
        them a full stop -- an author's drawing silently replaced by something
        they did not draw, which is the failure this project is arranged against.
        """
        document = minimal_document()
        document["items"]["brass_key"]["art"] = " *.* "
        self.workshop(document)

        drawn = self.looked("brass key")[0]

        self.assertIn("*.*", drawn)

    # -- asking for something that is not there ----------------------------

    def test_asking_for_something_you_are_not_carrying_is_a_diagnosis(self) -> None:
        """The house style: what was asked for, and what is actually here."""
        self.workshop()
        said = " ".join(self.looked("telescope")[0].split())
        self.assertIn('"telescope" is not something you are carrying.', said)
        self.assertIn(f"You have: {self.NAME}.", said)

    def test_the_same_sentence_ends_empty_handed_and_full_handed_ones(self) -> None:
        """The one string, reached two ways. A reader who meets it twice should
        meet the same sentence."""
        document = minimal_document()
        document["scenes"]["workshop"]["on_enter"] = []
        self.workshop(document)

        said = " ".join(self.looked("telescope")[0].split())

        self.assertIn(
            '"telescope" is not something you are carrying. You are carrying nothing.',
            said,
        )

    def test_two_matches_are_named_rather_than_chosen_between(self) -> None:
        """Taking the first would be the program choosing, silently, and showing
        the reader a different thing from the one they asked for."""
        document = minimal_document()
        document["items"]["brass_ring"] = {"name": "Brass Ring", "description": "Thin."}
        document["scenes"]["workshop"]["on_enter"] = [
            {"take": "brass_key"},
            {"take": "brass_ring"},
        ]
        self.workshop(document)

        drawn = self.looked("brass")[0]

        self.assertIn("Brass Ring", drawn)
        self.assertIn(self.NAME, drawn)
        # Neither one is *shown*: no picture, no description, because the reader
        # has not said which they meant.
        self.assertNotIn(self.ART, drawn)
        self.assertNotIn(self.DESCRIPTION, drawn)

    # -- how it is typed ---------------------------------------------------

    def test_look_is_a_command_and_not_an_option(self) -> None:
        self.answer("look")
        self.assertEqual(self.reply.command, "look")
        self.assertIsNone(self.reply.number)

    def test_bare_look_does_not_ask_a_second_question(self) -> None:
        """Asking "look at what?" would be the program demanding another
        keypress for an answer it can already give. The `1` behind it is the
        proof: a presenter that asked again would come back with a number."""
        self.answer("look", "1")
        self.assertEqual(self.reply.command, "look")
        self.assertIsNone(self.reply.subject)
        self.assertIsNone(self.reply.number)

    def test_something_after_look_is_the_thing_to_look_at(self) -> None:
        self.answer("look brass key")
        self.assertEqual(self.reply.command, "look")
        self.assertEqual(self.reply.subject, "brass key")

    def test_look_is_read_however_it_is_typed(self) -> None:
        for typed in ("Look", "LOOK", "look   brass   key"):
            with self.subTest(typed=typed):
                self.answer(typed)
                self.assertEqual(self.reply.command, "look")

    def test_a_reply_carries_a_subject_only_beside_a_command(self) -> None:
        """The invariant, restated: exactly one of the first two, and `subject`
        rides along with a command or is absent."""
        self.answer("1")
        self.assertIsNone(self.reply.subject)
        self.assertIsNone(self.reply.command)

    def test_prose_is_never_handed_to_the_markup_parser(self) -> None:
        """The same claim, made where it would actually break."""
        self.turn(body=(Paragraph("[bold]not a tag[/bold]"),))
        self.assertIn("[bold]not a tag[/bold]", self.drawn()[0])


class RevealTests(PresenterTestCase):
    """The typewriter, and the keypress that cuts it short."""

    def terminal_console(self) -> Console:
        """A console that believes it is a terminal, so the reveal is on."""
        self.console = Console(
            file=StringIO(), record=True, width=self.width, force_terminal=True
        )
        return self.console

    def terminal(self, watch=None, slept=None) -> Presenter:
        """A presenter drawing to one, with the waiting taken out.

        Nothing here sleeps: `sleep` is a list's `append`, so the delays can be
        asserted on as numbers. A test that really waited would be a test that
        gets skipped.
        """
        self.slept = slept if slept is not None else []
        return Presenter(
            self.terminal_console(),
            sleep=self.slept.append,
            watch=watch or (lambda: False),
        )

    def test_nothing_is_typewritten_when_nobody_is_watching(self) -> None:
        """There is no reader at the other end of a pipe, and a test that slept
        is a test that gets skipped."""
        self.assertFalse(Presenter(self.console).reveals)

    def test_the_typewriter_can_be_turned_off_on_a_terminal(self) -> None:
        """For a scripted demo or a screen recording, where a typewriter is only
        a way of making the recording longer."""
        self.assertTrue(self.terminal().reveals)
        self.assertFalse(
            Presenter(self.terminal_console(), instant=True).reveals
        )

    def test_a_typewritten_paragraph_says_the_same_thing_as_an_instant_one(self) -> None:
        body = (Paragraph("A draught moves under the door, and keeps moving for a while."),)
        self.turn(body=body)
        instant = self.drawn()[0]

        presenter = self.terminal()
        presenter.turn(Turn(messages=(), entered=self.view(body=body)))
        self.assertEqual(self.console.export_text(styles=False), instant)

    def test_the_speed_comes_from_the_palette(self) -> None:
        """Not a number written into the presenter, where it could never be
        changed with the rest of the look."""
        slept: list[float] = []
        body = (Paragraph("A draught, and then nothing at all for a long while."),)
        presenter = self.terminal(slept=slept)
        presenter.turn(Turn(messages=(), entered=self.view(body=body, pace="slow")))
        self.assertEqual(set(slept), {palette.delay_for("slow", len(body[0].text))})

    def test_a_paragraph_s_own_pace_wins_over_the_scene_s(self) -> None:
        """The scene sets the tempo, the paragraph overrides it -- which is the
        only reason a paragraph is allowed to name one."""
        fast: list[float] = []
        presenter = self.terminal(slept=fast)
        presenter.turn(
            Turn(
                messages=(),
                entered=self.view(body=(Paragraph("word " * 40, pace="fast"),), pace="slow"),
            )
        )
        self.assertEqual(set(fast), {palette.delay_for("fast", len("word " * 40))})

    def test_a_keypress_shows_the_rest_of_the_paragraph_at_once(self) -> None:
        """Which is what "any key skips" means, and it must not change what is
        on screen -- only when it got there."""
        body = (Paragraph("A draught moves under the door, and keeps on moving."),)
        self.turn(body=body)
        instant = self.drawn()[0]

        calls = {"n": 0}

        def watch() -> bool:
            calls["n"] += 1
            return calls["n"] == 5

        presenter = self.terminal(watch=watch)
        presenter.turn(Turn(messages=(), entered=self.view(body=body)))
        self.assertEqual(self.console.export_text(styles=False), instant)
        self.assertLess(
            calls["n"], len(body[0].text), "the reveal was not actually cut short"
        )


class KeyPressTests(RichTestCase):
    """The poll and the drain, which is the one bug in here nobody can see.

    Checking whether a key is waiting, deciding to skip, and leaving it in the
    buffer means the key that skipped a paragraph is answered at the next choice
    instead. The reader presses `2` to hurry the prose along and the game picks an
    option for them -- intermittently, depending on how fast they read, and
    looking exactly like a fault in the story. So the poll and the consume have to
    be one call, and these are the tests that say so.
    """

    def setUp(self) -> None:
        self.queue = list("abc")
        self.waited = 0
        self.taken: list[str] = []

        def waiting() -> bool:
            self.waited += 1
            return bool(self.queue)

        def take() -> None:
            self.taken.append(self.queue.pop(0))

        patches = [
            mock.patch.object(present_module, "_key_waiting", waiting),
            mock.patch.object(present_module, "_take_key", take),
            mock.patch.object(present_module, "msvcrt", object()),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_keypress_is_reported(self) -> None:
        self.assertTrue(keys_pressed())

    def test_every_key_waiting_is_taken_not_just_one(self) -> None:
        """Someone impatient enough to press three keys to skip one paragraph
        would otherwise leave two of them to answer the next question."""
        keys_pressed()
        self.assertEqual(self.taken, ["a", "b", "c"])
        self.assertEqual(self.queue, [])

    def test_the_check_stops_once_the_buffer_is_empty(self) -> None:
        """And so does not spin: three keys, four looks."""
        keys_pressed()
        self.assertEqual(self.waited, 4)

    def test_nothing_waiting_is_reported_as_nothing(self) -> None:
        self.queue = []
        self.assertFalse(keys_pressed())
        self.assertEqual(self.taken, [])

    def test_no_keyboard_at_all_is_not_a_keypress(self) -> None:
        """A piped run has no keyboard to poll, and the guard stops the poll
        before it reaches a platform that would raise."""
        with mock.patch.object(present_module, "msvcrt", None), mock.patch.object(
            present_module, "select", None
        ):
            self.assertFalse(keys_pressed())
        self.assertEqual(self.waited, 0)


if __name__ == "__main__":
    unittest.main()

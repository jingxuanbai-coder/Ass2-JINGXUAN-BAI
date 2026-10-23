"""Tests for the palette.

`palette.py` is the one module in the package that can be tested exhaustively,
because it decides nothing. It maps each word the schema lets an author write
onto a style, and a style can be compared -- so the whole of it is assertions
rather than samples.

Two kinds, and the first is the one that matters:

**Coverage.** Every member of `PARAGRAPH_STYLES`, `ENDING_KINDS` and `PACES` has
a look. Those vocabularies live in `model.py` and are enforced by the loader, so
this file's job is to fail when a word is added there and not here. Without it a
fifth register would load perfectly happily, reach the presenter during a
playthrough, and raise `KeyError` in front of whoever was reading. It is the same
move as the loader's "the fixture uses every condition operator" test.

**Distinctness.** A look that is the same as another look is not a look. If
`aside` and `whisper` rendered identically, one of them would be prose written
that never takes effect -- discoverable only by reading this file.
"""

from __future__ import annotations

import unittest

from branchline.model import ENDING_KINDS, PACES, PARAGRAPH_STYLES

try:
    from rich.style import Style

    from branchline import palette
except ImportError:  # pragma: no cover - an interpreter with no Rich
    # `palette` is a module of styles, so without Rich there is no palette to
    # test -- and the import has to be *here*, beside the one for Style, rather
    # than further down the file. A `from branchline import palette` outside this
    # block fails the moment the module is read, which takes the whole run with
    # it: a suite that dies at import cannot skip anything.
    Style = None  # type: ignore[assignment]
    palette = None  # type: ignore[assignment]

#: The attributes `EMPHASIS` could plausibly have been written with. Used to ask
#: whether emphasis would be *visible* in each register, rather than merely
#: different from it -- see `EmphasisTests`.
WEIGHT = ("bold", "italic", "underline")


def worn_by(style: Style) -> set[str]:
    """Which of those attributes a style already turns on."""
    return {name for name in WEIGHT if getattr(style, name)}


@unittest.skipUnless(palette is not None, "rich is not installed")
class PaletteTestCase(unittest.TestCase):
    """Skipped where Rich is absent rather than fatal.

    The loader and the engine still run there, and this module knows nothing
    about either of them -- the only reason it cannot run is the library the
    palette is written in. Skipping is the difference between a suite that has
    one optional dependency and a suite that has one hard one.
    """


class DeclaredVocabularyTests(PaletteTestCase):
    """Every word an author may write has a look, and nothing else does."""

    def test_every_register_has_a_look(self) -> None:
        self.assertEqual(set(palette.REGISTER_STYLES), set(PARAGRAPH_STYLES))

    def test_every_ending_mood_has_a_colour(self) -> None:
        self.assertEqual(set(palette.ENDING_STYLES), set(ENDING_KINDS))

    def test_every_pace_has_a_delay(self) -> None:
        self.assertEqual(set(palette.PACE_DELAYS), set(PACES))

    def test_the_default_pace_is_a_declared_pace(self) -> None:
        """Otherwise a paragraph with no `pace` would raise instead of reading."""
        self.assertIn(palette.DEFAULT_PACE, PACES)

    def test_body_prose_is_not_styled_at_all(self) -> None:
        """The narrator is the terminal's own default, on purpose.

        This is the commonest text on the screen. Painting it would mean the
        story's ordinary sentences arrived in a colour the reader did not choose,
        on a terminal whose colours they did choose -- and the registers, which
        are the exception, would stop looking like one.
        """
        self.assertEqual(palette.BODY, Style())


class DistinctnessTests(PaletteTestCase):
    """Two words that look the same are one word with extra typing."""

    def test_no_two_registers_look_alike(self) -> None:
        styles = list(palette.REGISTER_STYLES.values())
        self.assertEqual(len(set(styles)), len(styles))

    def test_no_two_moods_look_alike(self) -> None:
        styles = list(palette.ENDING_STYLES.values())
        self.assertEqual(len(set(styles)), len(styles))

    def test_every_register_looks_like_something(self) -> None:
        """A register styled as plain prose would be invisible in play.

        The author would have written `"style": "whisper"`, the loader would have
        accepted it, and the reader would have seen the narrator. That is the
        failure this whole suite is arranged against, one level down.
        """
        for name, style in palette.REGISTER_STYLES.items():
            with self.subTest(register=name):
                self.assertNotEqual(style, Style())

    def test_every_mood_is_distinguished_by_weight_and_not_only_colour(self) -> None:
        """An ending is the one moment the reader should not have to look for.

        Colour alone assumes a terminal that shows it. Weight survives being
        piped somewhere, resized, or set to a monochrome theme.
        """
        for kind, style in palette.ENDING_STYLES.items():
            with self.subTest(mood=kind):
                self.assertIn("bold", worn_by(style))

    def test_the_registers_are_set_in_further_than_the_narrator(self) -> None:
        self.assertGreater(palette.REGISTER_INDENT, palette.PROSE_INDENT)

    def test_a_locked_hint_sits_beside_the_option_it_explains(self) -> None:
        """Further in than the option, or it reads as the next option."""
        self.assertGreater(palette.HINT_INDENT, palette.CHOICE_INDENT)


class CarriedItemTests(PaletteTestCase):
    """The two styles `look` draws a thing it is being shown with.

    They are checked here rather than only in `test_present.py` because the
    claims are about the palette: an item's name is a look that must not collide
    with any other look, and that is exactly the rule the registers and the moods
    are already held to.
    """

    def test_an_item_name_does_not_look_like_any_ending(self) -> None:
        """`gold3` bold is the warm ending's title, and this was one word away
        from being spelled that way.

        A name and a title that look identical is the same fault as two registers
        that do -- which is why the registers are all italic and the moods are
        all bold, and why this one had to be a paler warm rather than the warm
        that was already taken.
        """
        for kind, style in palette.ENDING_STYLES.items():
            with self.subTest(mood=kind):
                self.assertNotEqual(palette.ITEM_NAME, style)

    def test_an_item_name_carries_weight_and_not_only_colour(self) -> None:
        """Colour alone assumes a terminal that shows it -- the same argument
        every ending is held to."""
        self.assertIn("bold", worn_by(palette.ITEM_NAME))

    def test_the_name_and_the_picture_are_not_the_same_style(self) -> None:
        """A picture that looked like the name above it would read as a second
        name. The difference is the weight, which is what says "this is not
        text"."""
        self.assertNotEqual(palette.ITEM_NAME, palette.ITEM_ART)

    def test_the_picture_is_not_plain_prose_either(self) -> None:
        """It is a made thing, and warmth is spent on made things."""
        self.assertNotEqual(palette.ITEM_ART, palette.BODY)

    def test_a_listed_entry_sits_under_the_line_introducing_it(self) -> None:
        """But less far in than a locked hint, which sets in beneath an *option*
        and has to be told apart from the next option rather than from a
        heading."""
        self.assertGreater(palette.LIST_INDENT, palette.PROSE_INDENT)
        self.assertLess(palette.LIST_INDENT, palette.HINT_INDENT)


class EmphasisTests(PaletteTestCase):
    """`*surrounded by stars*`, and the one register it would disappear in."""

    def test_emphasis_turns_something_on(self) -> None:
        self.assertTrue(worn_by(palette.EMPHASIS))

    def test_emphasis_is_heavier_than_everything_it_can_be_written_in(self) -> None:
        """The reason it is bold and not italic.

        Italic is what three of the four registers are already. `*the dome*`
        inside an `aside` would then be marked and look unmarked -- the words
        doing nothing, which is exactly what this project refuses. Bold compounds
        with whatever it is written in: plain prose becomes bold, an aside becomes
        bold italic, and emphasis is heavier than its surroundings in every
        register there is.
        """
        emphasised = worn_by(palette.EMPHASIS)
        for name, style in palette.REGISTER_STYLES.items():
            with self.subTest(register=name):
                self.assertTrue(
                    emphasised - worn_by(style),
                    f"emphasis inside '{name}' would change nothing",
                )
        self.assertEqual(emphasised - worn_by(palette.BODY), emphasised)


class DelayTests(PaletteTestCase):
    """How fast prose arrives, and the cap that keeps it from being a wait.

    Arithmetic, and nothing else -- but it lives here anyway, because the
    numbers are part of the look and belong beside the colours rather than in
    the presenter. A pace that meant the wrong thing would be invisible in every
    assertion about layout, and the delay is the one where "the same number for
    all three paces" is a real fault rather than a tidy simplification.
    """

    def test_a_short_paragraph_reads_at_its_declared_speed(self) -> None:
        for pace, delay in palette.PACE_DELAYS.items():
            with self.subTest(pace=pace):
                self.assertEqual(palette.delay_for(pace, 40), delay)

    def test_no_pace_means_the_default_pace(self) -> None:
        self.assertEqual(
            palette.delay_for(None, 40), palette.PACE_DELAYS[palette.DEFAULT_PACE]
        )

    def test_an_empty_paragraph_is_not_a_divide_by_zero(self) -> None:
        self.assertEqual(
            palette.delay_for("normal", 0), palette.PACE_DELAYS["normal"]
        )

    def test_no_paragraph_takes_longer_than_the_cap(self) -> None:
        """The cap is the reason this is a function and not a dictionary lookup.

        Without it a long paragraph takes proportionally longer than a short one,
        so the reveal punishes an author for writing more.
        """
        for pace in palette.PACE_DELAYS:
            for length in (1, 100, 1_000, 10_000):
                with self.subTest(pace=pace, length=length):
                    self.assertLessEqual(
                        palette.delay_for(pace, length) * length,
                        palette.MAX_REVEAL_SECONDS + 1e-9,
                    )

    def test_the_paces_keep_their_order_however_long_the_paragraph(self) -> None:
        """The fault that made this a scaling factor rather than three caps.

        Capping each pace on its own engages the cap for `slow` first -- at about
        seventy characters, which is most paragraphs -- and past that point all
        three return the same number. The author's `pace` then does nothing,
        silently, which is the failure this project refuses in every other layer.
        """
        for length in (10, 200, 1_000, 10_000):
            slow = palette.delay_for("slow", length)
            normal = palette.delay_for("normal", length)
            fast = palette.delay_for("fast", length)
            with self.subTest(length=length):
                self.assertGreater(slow, normal)
                self.assertGreater(normal, fast)

    def test_scaling_preserves_the_ratio_between_the_paces(self) -> None:
        """Not just the order -- the proportions the author chose between them."""
        for length in (50, 500, 5_000):
            slow = palette.delay_for("slow", length)
            normal = palette.delay_for("normal", length)
            with self.subTest(length=length):
                self.assertAlmostEqual(
                    normal / slow, palette.PACE_DELAYS["normal"] / palette.PACE_DELAYS["slow"]
                )

    def test_a_paragraph_is_never_slowed_down_by_the_cap(self) -> None:
        """The cap only ever shortens. A "cap" that made prose slower to arrive
        would be a floor with the wrong name on it."""
        for pace, delay in palette.PACE_DELAYS.items():
            for length in (0, 5, 50, 500, 5_000):
                with self.subTest(pace=pace, length=length):
                    self.assertLessEqual(palette.delay_for(pace, length), delay)


if __name__ == "__main__":
    unittest.main()

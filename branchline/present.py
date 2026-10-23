"""Drawing a story on a terminal.

Everything the reader sees passes through this module, and nothing else in the
package knows a terminal exists. The engine hands over a scene, some prose and a
list of things that can be pressed; this turns that into lines, colour and a
prompt.

**Why the colours are not here.** They are in `palette.py`, which is data. This
module decides *where* things go; that one decides *what they look like*. The
split is what lets the palette be tested exhaustively without drawing anything.

**Why nothing is a global.** The `Console` is handed in, never created here. A
module-level console would make every test's output depend on which test ran
first and on whether the suite was piped somewhere, and it would make
``export_text`` -- the seam the whole test suite for this module rests on --
useless, because the output would have gone to a terminal instead.

**Why this is not exported from `branchline/__init__.py`.** Importing it imports
`rich`. The package's `__init__` is the one everyone reaches for, and an engine
that "knows nothing about terminals" must not drag a terminal library in behind
it. `main.py` imports this by name, and only when it is actually playing.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from rich.console import Console
from rich.style import Style
from rich.text import Text

from . import palette
from .engine import Engine, Option, Turn
from .errors import StoryError
from .model import Ending, Item, Meta, Paragraph

# ---------------------------------------------------------------------------
# Keys, and the bug that lives in them
# ---------------------------------------------------------------------------

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

try:  # POSIX
    import select
except ImportError:  # pragma: no cover - Windows
    select = None  # type: ignore[assignment]


def _key_waiting() -> bool:
    """Whether a keypress is sitting in the buffer, without consuming it."""
    if msvcrt is not None:
        return bool(msvcrt.kbhit())
    if select is None or not sys.stdin.isatty():
        return False
    return bool(select.select([sys.stdin], [], [], 0)[0])


def _take_key() -> None:
    """Consume exactly one keypress."""
    if msvcrt is not None:
        msvcrt.getwch()
    else:
        sys.stdin.read(1)


def keys_pressed() -> bool:
    """True if a key is waiting -- and eats every key that is.

    **The poll and the consume have to happen together, and this function is the
    only place that happens.** The obvious implementation is to check whether a
    key is waiting, decide to skip the reveal, and carry on::

        if _key_waiting():
            return          # <- wrong: the key is still in the buffer

    The key that skipped the paragraph is then *still queued*. The next thing to
    read stdin is the prompt, so the reader presses `2` to hurry a paragraph
    along and the `2` is silently spent answering the next choice for them. What
    they see is the game picking an option they never chose, intermittently,
    depending on how fast they read -- which is the hardest kind of fault to
    report and the easiest to blame on the story.

    So: one call, both halves. It is also the only genuinely platform-specific
    code in the project, which is why it is four lines and heavily commented
    rather than clever.
    """
    if msvcrt is None and (select is None or not sys.stdin.isatty()):
        return False

    pressed = False
    while _key_waiting():
        _take_key()
        pressed = True
    return pressed


# ---------------------------------------------------------------------------
# Emphasis: *surrounded by stars*
# ---------------------------------------------------------------------------

#: A pair of stars with no space just inside them marks the words between.
#:
#: The "no space just inside" part is not decoration. Without it, `2 * 3 * 4`
#: -- and any other line of prose that happens to contain two asterisks -- would
#: silently turn ` 3 ` into emphasis. Requiring a non-space immediately after the
#: opening star and immediately before the closing one rules that out, while
#: leaving `*the dome*` and `*one word*` working exactly as an author expects.
#:
#: An asterisk that is not part of such a pair is left alone, because the prose
#: in a story about an observatory is allowed to contain a star.
_EMPHASIS = re.compile(r"\*(\S(?:.*?\S)?)\*")


def emphasise(text: str, style: Style) -> Text:
    """Prose as a `Text`, with `*starred*` runs heavier than the rest.

    Note what is *not* done here: the text is never handed to Rich's markup
    parser. An author writing `[the dome]` in a story means square brackets, and
    `Text(...)` treats them as literal characters -- `Text.from_markup` would
    swallow them. Story prose is not markup and must never be parsed as any.
    """
    out = Text(style=style)
    cursor = 0
    for match in _EMPHASIS.finditer(text):
        out.append(text[cursor : match.start()])
        out.append(match.group(1), style=palette.EMPHASIS)
        cursor = match.end()
    out.append(text[cursor:])
    return out


# ---------------------------------------------------------------------------
# What the reader can type
# ---------------------------------------------------------------------------

#: The words the prompt accepts besides a number. They are *not* options: they are
#: not drawn with a number, they are not passed to the engine, and
#: `engine.options()` never contains them. Saving, loading and looking are things
#: the program does, not things the story offers, and the engine's whole test
#: suite exists to keep it from learning otherwise.
#:
#: **This tuple is what the prompt line and the near-miss sentence are built
#: from**, and that is the whole reason it is a tuple instead of three constants
#: used one at a time. It used to be `(SAVE, LOAD)` and nothing read it, while
#: the sentence that tells a reader what they may type named the two words by
#: hand one screen below -- so adding a third word meant remembering to edit two
#: strings, and the constant was a description of the prompt rather than a part
#: of it. Now a word added here is on the prompt line and in the refusal, or it
#: is nowhere, and either way the two cannot disagree.
SAVE = "save"
LOAD = "load"
LOOK = "look"
COMMANDS = (SAVE, LOAD, LOOK)

#: Said when the reader asks to see something and their hands are empty.
#:
#: One string rather than two, because it is the same fact reached two ways --
#: asked of everything they have, and asked of one thing they have not got -- and
#: a reader who meets it twice should meet the same sentence.
NOTHING_CARRIED = "You are carrying nothing."


def _word_list(words: Sequence[str]) -> str:
    """"save, load or look" -- the words as a reader would say them."""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " or " + words[-1]


@dataclass(frozen=True, slots=True)
class Reply:
    """What the reader typed at a prompt: an option number, or a word.

    Exactly one of the first two is ever set. It is a small object rather than an
    `int | str` union because the two mean genuinely different things -- a number
    is handed to the engine and a word is handled by the program around it -- and
    a union would make `if isinstance(reply, str)` the test that decides which
    part of the program runs next.

    `subject` is set only beside a command that takes one, which today is `look`
    alone, and it holds the words **as typed** rather than a resolved item. That
    is deliberate: this object is a record of what the reader said, and working
    out what they meant is a question about the screen and the story -- which is
    the presenter's business, not an answer's.
    """

    number: int | None = None
    command: str | None = None
    subject: str | None = None


def resolve_item(carried: Iterable[Item], words: str) -> tuple[Item, ...]:
    """Everything in `carried` the reader's words could mean, in the order carried.

    Two rounds, and the first that finds anything wins:

    1. the whole of the item's `name`, or its id with the underscores turned into
       spaces, ignoring case and runs of whitespace;
    2. failing that, everything whose name or id-words *begin* with the words.

    Returns a tuple rather than one item, because two matches is a question for
    the reader and not a coin for the program to flip. Empty means nothing
    matched; one is the answer; more than one means they have to say which.

    **Why the id is accepted when nothing ever displays it.** The premise of the
    whole project is that the story file is readable by the person who wrote it,
    and that person writes ``brass_key``. Telling them "brass key" is not
    something they are carrying, when the story they are reading calls it exactly
    that, would be the program being pedantic about a name it made up.

    **Why this is not on the engine.** Matching is policy -- case folding,
    underscores, prefixes, and what to do when two things match -- and none of it
    is a fact about the story. The engine has no vocabulary for it and no test
    file that would naturally cover it, and the engine's charter is that it knows
    nothing about which *words* exist. Everything this needs, `Engine.carried()`
    already hands over.
    """
    def normalise(text: str) -> str:
        return " ".join(text.lower().replace("_", " ").split())

    wanted = normalise(words)
    if not wanted:
        return ()

    # Id-words are accepted, the name is what is shown, and both are matched
    # against -- a reader may reasonably type either.
    def spoken(item: Item) -> tuple[str, str]:
        return normalise(item.name), normalise(item.id)

    exact = tuple(
        item for item in carried if wanted in spoken(item)
    )
    if exact:
        return exact
    return tuple(
        item
        for item in carried
        if any(form.startswith(wanted) for form in spoken(item))
    )


# ---------------------------------------------------------------------------
# The presenter
# ---------------------------------------------------------------------------


class Presenter:
    """Draws a run of the story. One is built per playthrough, and holds a console."""

    def __init__(
        self,
        console: Console,
        *,
        instant: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        watch: Callable[[], bool] = keys_pressed,
    ) -> None:
        self.console = console
        #: Turn every reveal off. For a scripted demo or a screen recording,
        #: where a typewriter is only a way to make the recording longer.
        self.instant = instant
        # Injected so that the reveal can be tested without a real keyboard and
        # without actually waiting -- a test that sleeps is a test that gets
        # skipped.
        self._sleep = sleep
        self._watch = watch

    @property
    def reveals(self) -> bool:
        """Whether prose arrives a character at a time.

        Off when nothing is watching: piped, redirected, or captured by a test.
        A typewriter is an effect for a reader, and there is no reader at the
        other end of a pipe.
        """
        return not self.instant and self.console.is_terminal

    # -- the shape of a screen ----------------------------------------------

    def opening(self, meta: Meta, seed: int | None) -> None:
        """The title card, before the first scene."""
        self._blank()
        self.console.print(self._line(meta.title, palette.PROSE_INDENT, palette.TITLE))
        if meta.author:
            self.console.print(
                self._line(f"by {meta.author}", palette.PROSE_INDENT, palette.FOOTNOTE)
            )
        if meta.subtitle:
            self.console.print(
                self._line(meta.subtitle, palette.PROSE_INDENT, palette.TITLE_CARD)
            )
        for paragraph in meta.title_card:
            # A title card paragraph can name a register like any other, so it
            # gets it. Ignoring it here would be prose written that never takes
            # effect -- the failure this project refuses everywhere else.
            if paragraph.style is None:
                style = palette.TITLE_CARD
            else:
                style = palette.REGISTER_STYLES[paragraph.style]
            self._fixed(paragraph.text, palette.PROSE_INDENT, style)
        # Printed so that "something odd happened" can be answered with a number,
        # and the run reproduced exactly.
        self.console.print(
            self._line(f"seed {seed}", palette.PROSE_INDENT, palette.FOOTNOTE)
        )

    def turn(self, turn: Turn) -> None:
        """Draw a turn: the scene arrived at, then anything said on the way.

        Prose first, messages second -- the messages are the world's reply to
        what the reader just did, so they come after the room they did it in.
        """
        view = turn.entered
        self._title(view.title)
        self._prose(view.body, view.pace)
        self._prose(turn.messages, view.pace)

    def ending(self, ending: Ending) -> None:
        """The last thing the reader reads.

        A full-width rule, then the title in the mood's own colour, then the
        epilogue. No box: an ending is distinguished by weight and colour, and a
        container would put a frame around the one moment that should feel like
        it opened out rather than closed down.
        """
        style = palette.ENDING_STYLES[ending.kind]
        # No blank line first: the ending is always drawn directly after the
        # scene that ended, and that scene already left one.
        self.console.print(
            self._line("─" * max(0, self.console.width - palette.PROSE_INDENT), palette.PROSE_INDENT, palette.ENDING_RULE)
        )
        self.console.print(self._line(ending.title, palette.PROSE_INDENT, style))
        self._blank()
        self._prose(ending.epilogue, None)

    def note(self, text: str) -> None:
        """A line of plain feedback, such as a refusal to accept a keypress.

        Blank lines on both sides, because what follows a refusal is the whole
        set of options again -- and without the second blank the explanation
        reads as though it were the first item of the list it is apologising for.
        """
        self._blank()
        for line in text.splitlines():
            self.console.print(self._line(line, palette.PROSE_INDENT, palette.FOOTNOTE))
        self._blank()

    # -- asking -------------------------------------------------------------

    def ask(self, engine: Engine, *, can_load: bool = False) -> Reply | None:
        """Offer the options and read an answer. None if the reader stops.

        The options are drawn once and then read from, in a loop, because a
        wrong keypress is not an error -- it is someone typing. Redrawing the
        whole screen to say "that is not a number" would throw away the prose
        they are still reading.

        `can_load` says whether there is a save file to go back to. It is the
        caller's to know because the caller owns the file -- and it is passed in
        rather than discovered here so that `load` with nothing saved can say so
        *instead of* asking the reader to confirm throwing away a run for
        nothing.
        """
        for option in engine.options():
            self._option(option)

        hud = engine.hud()
        if hud:
            self._blank()
            # "pages read 0". The number is the fact, so it is the warm thing;
            # the words around it are the interface, so they are not.
            status = Text(" " * palette.PROSE_INDENT)
            for index, (decl, value) in enumerate(hud):
                if index:
                    status.append("   ")
                status.append(decl.label or decl.name, style=palette.HUD_LABEL)
                status.append(" ")
                status.append(self._value(value), style=palette.HUD_VALUE)
            self.console.print(status)

        carry = engine.carried()
        if carry:
            self.console.print(
                self._line(
                    "carrying: " + ", ".join(item.name for item in carry),
                    palette.PROSE_INDENT,
                    palette.CARRYING,
                )
            )

        self._blank()
        # The one line that makes the commands findable. A command a reader can
        # only discover by guessing is the same failure as prose with no
        # implementation, one level up -- so it is drawn every turn, quietly,
        # where the prompt is. Built from `COMMANDS`, so a word added there is on
        # this line without anyone remembering to edit it.
        self.console.print(
            self._line(
                " · ".join(COMMANDS) + " · or a number",
                palette.PROSE_INDENT,
                palette.FOOTNOTE,
            )
        )

        while True:
            typed = self._read()
            if typed is None:
                return None
            if not typed:
                # A bare Enter. Not a mistake worth explaining, and explaining it
                # would mean quoting an empty string back at the reader, which
                # reads as a fault in the program rather than as a keypress.
                continue

            # `str.isdigit()` is true for characters `int()` refuses -- a circled
            # or superscript digit pasted in from somewhere else -- so the
            # conversion is what decides, not the test. Falling through lets the
            # message further down say what happened; a reader must not be able
            # to reach a traceback from the prompt, and one pasted character is
            # the whole of that promise's remaining gap.
            if typed.isdigit():
                try:
                    return Reply(number=int(typed))
                except ValueError:
                    pass

            # Split once, so a command can carry something after it. `look` is
            # the only one that does; `save` and `load` never see the tail.
            word, _, rest = typed.partition(" ")
            word = word.lower()
            if word == SAVE:
                return Reply(command=SAVE)
            if word == LOAD and self._agree_to_load(can_load):
                return Reply(command=LOAD)
            if word == LOAD:
                # Said no, or there was nothing to go back to. Both are answers
                # to the question; neither is a mistake, so the loop just asks
                # again rather than treating it as bad input.
                continue
            if word == LOOK:
                # Bare `look` is an answer and not a question about which thing
                # to look at: asking "look at what?" would be the program
                # demanding a second keypress for something it can already say.
                return Reply(command=LOOK, subject=rest.strip() or None)

            # The escape hatch stays in this message, where it has always been:
            # a reader who has just been told they typed the wrong thing is
            # exactly the reader who may be looking for the way out.
            self.console.print(
                self._line(
                    f'"{typed}" is not one of the options here — type a number, '
                    f"{_word_list(COMMANDS)}. Press Ctrl+Z to stop.",
                    palette.PROSE_INDENT,
                    palette.FOOTNOTE,
                )
            )

    def _read(self) -> str | None:
        """One line of input, cleaned, or None if the reader stopped.

        A character the reader cannot see is not an answer. `.strip()` does not
        remove a byte-order mark, and a BOM is what PowerShell 5.1 puts on the
        first line of a pipe -- so a scripted demo would silently lose its first
        answer and shift every keypress by one, which looks exactly like an
        engine bug and is not one. Dropping unprintable characters catches that
        without this file having to name a character nobody can see.
        """
        try:
            return "".join(
                ch for ch in self.console.input(self._prompt()) if ch.isprintable()
            ).strip()
        except EOFError:
            # Ctrl+Z then Enter in PowerShell. Not an error, just someone
            # leaving -- and without this the traceback is a wall of noise.
            return None

    def _agree_to_load(self, can_load: bool) -> bool:
        """Whether the reader means to throw this run away. False on anything else.

        Running out of input is a *no*. A piped run whose answers end exactly at a
        `load` has not consented to anything, and reading silence as agreement
        would make the last command of a script destroy the run it was checking.
        """
        self._blank()
        if not can_load:
            self.console.print(
                self._line(
                    "Nothing is saved yet.", palette.PROSE_INDENT, palette.FOOTNOTE
                )
            )
            self._blank()
            return False

        self.console.print(
            self._line(
                "This will put you back where you saved, and everything since will "
                "be lost.",
                palette.PROSE_INDENT,
                palette.FOOTNOTE,
            )
        )
        self.console.print(
            self._line('Type "yes" to go on.', palette.PROSE_INDENT, palette.FOOTNOTE)
        )
        answer = self._read()
        agreed = answer is not None and answer.lower() == "yes"
        self._blank()
        if not agreed:
            self.console.print(
                self._line(
                    "Nothing was loaded.", palette.PROSE_INDENT, palette.FOOTNOTE
                )
            )
        return agreed

    def loaded(self, engine: Engine) -> None:
        """The run was picked up: say so, then draw the room it left off in.

        The seed is printed a second time because the one at the top of the
        screen belonged to the run just thrown away. It is the one piece of state
        that opening screen advertises -- the whole point of it is that a strange
        run can be reproduced -- so leaving the stale number there would be a
        false statement about the run now being played.

        There are no messages to draw with the room, and that is not an omission.
        Entering a scene is what runs its `on_enter`, and a resumed run
        deliberately does not re-enter: doing so would count the visit again,
        re-roll anything chancy, and replay prose the reader has already read.
        """
        self._blank()
        self.console.print(
            self._line(
                f"Loaded — seed {engine.state.seed}.",
                palette.PROSE_INDENT,
                palette.FOOTNOTE,
            )
        )
        view = engine.view()
        self._title(view.title)
        self._prose(view.body, view.pace)

    def saved(self, path: Path | str) -> None:
        """Say that the run was written down, and *where*.

        The path is the one thing the reader cannot work out for themselves, and
        naming it is also how they learn that an earlier save has just been
        replaced -- which is worth knowing before, not after.
        """
        self.note(f"Saved to {path}.")

    def refused(self, error: StoryError) -> None:
        """A save that could not be used, and the reassurance that follows it.

        The diagnosis is the same one a broken story gets, because a save file is
        a document that has to satisfy rules and this program has exactly one way
        of explaining that. What it needs on top is the second half: a refused
        load is not a crash and the run in progress is untouched.
        """
        self.note(f"{error}\n\nThe run in progress was left alone.")

    def looked(self, engine: Engine, subject: str | None) -> None:
        """The reader asked to see what they are carrying, or one thing in it.

        **Why this is here and not in `main.py` beside `save` and `load`.** Those
        two leave `ask()` as a `Reply` because they touch *files*, which the
        presenter must never own. A `look` touches nothing outside data `ask()`
        is already holding: `engine.carried()` is called every turn anyway to
        draw the `carrying:` line above the prompt. So a `look` is the reader
        addressing the interface rather than the story, it is not an answer the
        engine could be given, and it prints and asks again -- exactly as a
        declined `load` does.

        The payoff is that adding this to the game tells the engine nothing. That
        is the same claim the presentation and the save system each made, and it
        is worth it staying true on the last round too.

        There is no `look` at an ending, and nothing here handles one: the run
        ends when the character does, and the prompt is gone by then. Leaving
        that unsaid is how somebody later adds a branch that can never run.

        The overlapping with the `carrying:` line is deliberate. That line is a
        *summary* at the foot of every screen; this is the answer to a question,
        and a reader who asks is entitled to the whole of it.
        """
        self._blank()
        if subject is None:
            self._carried(engine)
            self._blank()
            return

        matches = resolve_item(engine.carried(), subject)
        if not matches:
            self._not_carried(engine, subject)
            self._blank()
        elif len(matches) > 1:
            self._ambiguous(subject, matches)
            self._blank()
        else:
            # Ends with a blank of its own, because whether there is one to end
            # with depends on whether the author wrote a description -- and a
            # caller adding a second one would leave a gap in the one case.
            self._examined(matches[0])

    def _carried(self, engine: Engine) -> None:
        """Bare `look`: everything in the reader's hands, one per line."""
        carry = engine.carried()
        if not carry:
            self._literal(NOTHING_CARRIED, palette.PROSE_INDENT, palette.FOOTNOTE)
            return
        self._literal("You are carrying:", palette.PROSE_INDENT, palette.FOOTNOTE)
        for item in carry:
            self._literal(item.name, palette.LIST_INDENT, palette.ITEM_NAME)

    def _examined(self, item: Item) -> None:
        """One item: its name, its art if it has any, then what the author wrote about it.

        An item with no `art` loses a line and an item with no `description`
        loses a paragraph, and neither is an error. `description` is documented
        as optional, and a `look` that refused to name something because nobody
        described it would be the program declining to answer a question it can
        answer.
        """
        self._literal(item.name, palette.PROSE_INDENT, palette.ITEM_NAME)
        if item.art:
            self._literal(item.art, palette.PROSE_INDENT, palette.ITEM_ART)
        self._blank()
        if item.description:
            # A `Paragraph` with no register, so the description is the narrator
            # speaking -- which is what it is -- and goes through the ordinary
            # prose path, where `*stars*` mean what they always mean and the
            # reveal applies. It is a sentence somebody wrote, not a label.
            self._prose((Paragraph(item.description),), None)

    def _not_carried(self, engine: Engine, subject: str) -> None:
        """The house diagnosis: what was asked for, and what is actually here."""
        carry = engine.carried()
        tail = (
            "You have: " + ", ".join(item.name for item in carry) + "."
            if carry
            else NOTHING_CARRIED
        )
        self._literal(
            f'"{subject}" is not something you are carrying. {tail}',
            palette.PROSE_INDENT,
            palette.FOOTNOTE,
        )

    def _ambiguous(self, subject: str, matches: tuple[Item, ...]) -> None:
        """More than one thing matches, so the reader says which.

        Taking the first would be the program choosing, and it would choose
        silently -- the reader would be shown a different thing from the one they
        asked for and would have no way to tell.
        """
        names = ", ".join(item.name for item in matches)
        self._literal(
            f'"{subject}" could be more than one thing you are carrying — say '
            f"which: {names}.",
            palette.PROSE_INDENT,
            palette.FOOTNOTE,
        )

    def _literal(self, text: str, indent: int, style: Style) -> None:
        """One or more lines drawn exactly as written, and never revealed.

        **Deliberately not `emphasise`, and `art` is why.** A picture is a
        picture: `( o )` comes out the same either way, but an author who draws a
        star as `*.*` would have the stars eaten by the emphasis rule and be
        shown something that is not what they wrote. A name, a picture and a
        sentence quoting the reader back at themselves are all *text*, not prose.

        Also never revealed, because a name and a picture are the answer to a
        question rather than the telling of something -- and because the
        diagnosis below is addressed to somebody who is waiting for it. The one
        thing here that *is* prose, an item's `description`, goes through
        `_prose` and arrives at the ordinary tempo.
        """
        for line in self._lines(Text(text, style=style), indent):
            self.console.print(line)

    def stopped(self) -> None:
        """The reader left in the middle, taking the run with them."""
        self._blank()
        self.console.print(
            self._line("Left where it stands.", palette.PROSE_INDENT, palette.FOOTNOTE)
        )
        self.console.print(
            self._line(
                f"Leaving does not save — type {SAVE} at the prompt to keep a run.",
                palette.PROSE_INDENT,
                palette.FOOTNOTE,
            )
        )

    # -- the pieces a screen is made of -------------------------------------

    def _title(self, text: str) -> None:
        """A scene title, with a rule sized to the title rather than to the screen.

        A fixed-width rule was what this replaced. A title that grows can be
        longer than a constant somebody chose months ago, and then the rule
        either wraps or stops short of the words it is underlining.
        """
        self._blank()
        self.console.print(self._line(text, palette.PROSE_INDENT, palette.TITLE))
        self.console.print(
            self._line("─" * len(text), palette.PROSE_INDENT, palette.TITLE_RULE)
        )
        self._blank()

    def _option(self, option: Option) -> None:
        """One pressable choice: its number, its marker, and -- if locked -- its hint."""
        style = palette.LOCKED if option.locked else palette.CHOICE
        number = Text(
            "▸ ",
            style=palette.CHOICE_MARKER if not option.locked else palette.LOCKED,
        )
        number.append(f"{option.number}. ", style=style)
        number.append(option.text, style=style)
        self.console.print(self._indent(number, palette.CHOICE_INDENT))

        if option.locked and option.locked_hint:
            self.console.print(
                self._line(
                    option.locked_hint, palette.HINT_INDENT, palette.LOCKED_HINT
                )
            )

    def _prose(self, paragraphs: Iterable[Paragraph], scene_pace: str | None) -> None:
        """A run of paragraphs, each in its own register and at its own pace.

        A blank line between paragraphs, and one after the last. The blank is
        what separates two paragraphs the *author* separated -- without it, a
        body and an aside run together into one block and the register stops
        reading as a change of voice.
        """
        written = False
        for paragraph in paragraphs:
            if written:
                self._blank()
            written = True
            if paragraph.style is None:
                style, indent = palette.BODY, palette.PROSE_INDENT
            else:
                # Indexed, not looked up with a default. An unknown register
                # should be a loud failure naming the register; falling back to
                # plain prose would render it as the narrator and take away the
                # only evidence that anything went wrong.
                style, indent = palette.REGISTER_STYLES[paragraph.style], palette.REGISTER_INDENT

            self._write(
                emphasise(paragraph.text, style),
                indent,
                paragraph.pace or scene_pace,
            )
        if written:
            self._blank()

    # -- writing, at one speed or another -----------------------------------

    def _fixed(self, text: str, indent: int, style: Style) -> None:
        """One paragraph, wrapped and styled, never revealed.

        For the title card, which is on screen before the story starts and
        should not have to be waited for.
        """
        for line in self._lines(emphasise(text, style), indent):
            self.console.print(line)

    def _write(self, text: Text, indent: int, pace: str | None) -> None:
        """Print a paragraph, either all at once or a character at a time."""
        if not self.reveals:
            for line in self._lines(text, indent):
                self.console.print(line)
            return

        self._reveal(text, indent, pace)

    def _reveal(self, text: Text, indent: int, pace: str | None) -> None:
        """Reveal a paragraph character by character, until a key cuts it short.

        The per-paragraph cap in `palette.delay_for` is what makes this bearable:
        without it a long paragraph would take proportionally longer than a short
        one, and the effect meant to draw a reader in would start punishing an
        author for writing more.
        """
        delay = palette.delay_for(pace, len(text.plain))
        for line in self._lines(text, indent):
            offset = 0
            while offset < len(line.plain):
                self.console.print(line[offset], end="", soft_wrap=True)
                offset += 1
                self._sleep(delay)
                if self._watch():
                    # The key has already been consumed by `watch`. Printing the
                    # rest of the line at once is what "any key skips" means.
                    self.console.print(line[offset:], end="", soft_wrap=True)
                    break
            self.console.print()

    def _lines(self, text: Text, indent: int) -> list[Text]:
        """A paragraph broken to the console's width, with every line set in.

        The indent is applied per *wrapped* line rather than to the paragraph,
        because the alternative -- prefixing the paragraph once -- leaves the
        continuation lines hard against the left margin, so a set-in paragraph
        stops being set in on its second line.
        """
        width = max(20, self.console.width - indent)
        lines: list[Text] = []
        for line in text.wrap(self.console, width):
            # `Text.rstrip()` strips in place and returns None, and `wrap()` may
            # hand back the very `Text` it was given when nothing needed
            # breaking -- so the copy is not tidiness, it is what stops a
            # one-line paragraph being stripped for every caller that ever
            # renders it again.
            trimmed = line.copy()
            trimmed.rstrip()
            lines.append(Text(" " * indent) + trimmed)
        return lines

    # -- small helpers ------------------------------------------------------

    def _line(self, text: str, indent: int, style: Style) -> Text:
        """One unwrapped line, at an indent, in a style."""
        return Text(" " * indent + text, style=style)

    def _indent(self, text: Text, indent: int) -> Text:
        return Text(" " * indent) + text

    def _blank(self) -> None:
        self.console.print()

    def _prompt(self) -> Text:
        return Text("  " + "> ", style=palette.FOOTNOTE)

    def _value(self, value: object) -> str:
        """A status-line value, as words rather than as Python.

        `engine.hud()` hands over raw values on purpose -- turning `True` into
        "yes" is a presentation decision -- so this is the layer that owns it.
        Without this, a story with a boolean on its status line would read
        "True" at the reader, which is not a word anybody wrote.
        """
        if value is True:
            return "yes"
        if value is False:
            return "no"
        return str(value)

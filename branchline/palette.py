"""What the story looks like: registers, moods, and the spacing between them.

This module is **pure data and arithmetic**. It draws nothing and reads nothing,
which is what makes it testable in isolation -- the presenter next door owns the
drawing, and `engine.py` owns the game.

**Why it is separate from `present.py`.** `model.py` already says so, in the
comment above the vocabularies:

    These live here rather than in the presentation layer because they are
    *schema*: the loader rejects a word that is not in them ... How each one
    looks is a separate question, answered in `palette.py` when the Rich layer
    lands.

So the split is not a matter of taste. `model.py` owns the *words an author may
write*; this module owns *what each word looks like*. Nothing here may add a
register or a mood of its own, and `test_palette.py` iterates the declared
vocabularies and fails if one of them has no look -- otherwise adding a fifth
register in `model.py` would produce a `KeyError` during play, months later, in
front of someone.

**The colours are cool-dominant.** Every structural thing -- the rules, the
choices, the dimmed text -- is blue, grey or violet. Warmth is spent only on
things that were *made*: brass, paper, a lamp. The story this palette was drawn
for is about something built to outlast the person who built it, so the contrast
it needs is already there: the natural and the cold on one side, the made and the
warm on the other. Spending warmth everywhere would lose it.
"""

from __future__ import annotations

from rich.style import Style

# ---------------------------------------------------------------------------
# Structure
#
# The bones of a screen: a title and the rule under it, the marker beside a
# choice, the dimmed and italic asides of the interface itself. All cool.
# ---------------------------------------------------------------------------

TITLE = Style(bold=True)
TITLE_RULE = Style(color="steel_blue3")
TITLE_CARD = Style(color="grey62", italic=True)
ENDING_RULE = Style(color="grey50")

CHOICE_MARKER = Style(color="sky_blue2")
CHOICE = Style()
LOCKED = Style(color="grey50")
LOCKED_HINT = Style(color="grey50", italic=True)

HUD_LABEL = Style(color="grey50")
HUD_VALUE = Style(color="tan")
CARRYING = Style(color="grey50")
FOOTNOTE = Style(color="grey50")

# ---------------------------------------------------------------------------
# What the reader is carrying, when they ask to see it
#
# The palette's rule is that warmth is spent only on things that were *made* --
# and of everything an author can declare, an item is the most obviously made:
# it was built, someone held it, and that is usually the story. So the two lines
# that name it and draw it take the warm colour, and the description underneath
# does not, because that is the narrator talking and the narrator is never
# coloured.
# ---------------------------------------------------------------------------

#: The name of an item, as `look` draws it.
#:
#: Warm and *weighted*, and the weight is doing a job rather than decorating.
#: `gold3` bold is already the warm ending's title, and a name and a title that
#: look identical is the same fault as a register and a mood that do -- which is
#: why the registers are all italic and the moods are all bold, and why this is
#: a paler warm plus bold rather than the warm they already use.
ITEM_NAME = Style(color="wheat1", bold=True)

#: An item's `art`: the one purely decorative thing an author can write.
#:
#: The same warmth without the weight, so it reads as a picture beneath the name
#: rather than as a second name. Drawn exactly as written and never parsed for
#: emphasis -- `present._literal` argues that, and it is why a star in a picture
#: is a character rather than a bracket.
ITEM_ART = Style(color="wheat1")

# ---------------------------------------------------------------------------
# The registers a paragraph can be written in
#
# One entry per member of `model.PARAGRAPH_STYLES`, and no entry that is not one
# of them. Body prose -- a paragraph with no style -- is the narrator, and is
# deliberately *not* in here: it is the terminal's own default, so that the
# commonest text on screen is the one thing this palette does not touch.
# ---------------------------------------------------------------------------

REGISTER_STYLES: dict[str, Style] = {
    # Someone thinking aloud, beside the narration rather than in it.
    "aside": Style(color="sky_blue2", italic=True),
    # A document. Warm, because paper is made; the one register that gets to be.
    "letter": Style(color="tan"),
    # Something fixed to a wall. Weight without colour-saturation: a sign is
    # manufactured, but it is a message rather than an object.
    "sign": Style(color="steel_blue1", bold=True),
    # The quietest thing on the page. Grey rather than a dimmed blue, because
    # dimming a colour leaves a colour, and this is meant to be almost absent.
    "whisper": Style(color="grey50", italic=True),
}

#: The narrator's own voice: a paragraph written with no style at all.
#:
#: Deliberately empty rather than a colour. This is the commonest text on the
#: screen, and styling it would mean the story's ordinary sentences arrived in a
#: colour the reader did not choose -- on a terminal whose colours they did
#: choose. The registers are the exception, and should look like one.
BODY = Style()

#: How far prose is set in from the edge of the terminal.
PROSE_INDENT = 2

#: How far a paragraph *in a register* is set in.
#:
#: The same distance for all four, deliberately. Indentation has one job here --
#: saying "this is not the narrator" -- and it does that job for every register
#: alike. Which of the four it is, is the palette's job, and an author who had to
#: remember four indent depths as well as four looks would be remembering the
#: implementation instead of the story.
REGISTER_INDENT = 4

CHOICE_INDENT = 2
HINT_INDENT = 6

#: How far an entry in a list is set in from the line that introduces it.
#:
#: Further in than the line above it, so the entries read as belonging to it --
#: and less far than a locked hint, which sets in beneath an *option* and has to
#: be told apart from the next option rather than from a heading.
LIST_INDENT = PROSE_INDENT + 2

# ---------------------------------------------------------------------------
# The mood of an ending
#
# One entry per member of `model.ENDING_KINDS`. Cool/warm does the work: "warm"
# and "bitter" are the two poles, "neutral" is the grey that belongs to neither,
# and "ambiguous" gets the one colour that is genuinely between them rather than
# being a third temperature.
# ---------------------------------------------------------------------------

ENDING_STYLES: dict[str, Style] = {
    "warm": Style(color="gold3", bold=True),
    "bitter": Style(color="steel_blue3", bold=True),
    "ambiguous": Style(color="medium_purple", bold=True),
    "neutral": Style(color="grey62", bold=True),
}

# ---------------------------------------------------------------------------
# Emphasis: *surrounded by stars*
# ---------------------------------------------------------------------------

#: What `*surrounded by stars*` does to the words between the stars.
#:
#: **Bold and underlined together, and each of those is load-bearing.**
#:
#: Not italic, because italic is what two of the four registers already use: an
#: `aside` or a `whisper` would swallow the emphasis entirely -- the words marked
#: and looking unmarked, which is the failure this project is against.
#:
#: But bold *alone* is not enough either, and the reason is the `sign`. It is
#: already bold, so `*No entry*` on a sign would change nothing at all. Bold is
#: the right weight for a sign and it is the right weight for emphasis; they
#: cannot both have it and mean something. Underline is the one attribute no
#: register wears, so it is what always shows: prose becomes bold, an aside
#: becomes bold italic, a sign gets the underline it did not have, and emphasis
#: is visible in every register -- including any fifth one an author is given
#: later, which is the part that makes this worth solving rather than dodging by
#: restyling signs.
#:
#: `test_palette.py` asserts this, register by register, rather than trusting it.
EMPHASIS = Style(bold=True, underline=True)

# ---------------------------------------------------------------------------
# Pace: how fast prose arrives
# ---------------------------------------------------------------------------

#: Seconds per character. One entry per member of `model.PACES`.
PACE_DELAYS: dict[str, float] = {"slow": 0.035, "normal": 0.018, "fast": 0.008}

#: What a paragraph or scene gets when it does not name a pace.
DEFAULT_PACE = "normal"

#: The longest any one paragraph may take to arrive, however long it is.
MAX_REVEAL_SECONDS = 2.5


def delay_for(pace: str | None, length: int) -> float:
    """Seconds between characters, for a paragraph of `length` characters.

    The cap is the part worth arguing about, and it is why this is not just a
    dictionary lookup. Without it, a long paragraph takes proportionally longer
    than a short one, so **the reveal punishes an author for writing more**. A
    reader who chose `slow` asked for a tempo, not a duration; past a couple of
    seconds the only thing a long reveal produces is impatience, and the effect
    meant to draw someone in starts pushing them away.

    So a long paragraph is scaled down. Short paragraphs are unaffected.

    **What is scaled, and why it is not each pace on its own.** The obvious
    version caps every pace separately -- `min(base, MAX_REVEAL_SECONDS / length)`
    -- and it has a fault that only shows up once the numbers are run. The cap
    engages for `slow` first, at about seventy characters, which is to say for
    most paragraphs anyone would actually write. Past that point all three paces
    return the *same* delay, and `"pace": "slow"` stops being read at all: a word
    the author writes that does nothing, in the one layer whose whole job is
    timing.

    So all three are scaled by the single factor that brings the *slowest* pace
    inside the cap. A reader who chose `slow` gets the longest of the three
    timings for this paragraph and one that still finishes in
    `MAX_REVEAL_SECONDS`; the three paces keep their order and their ratios
    however long the paragraph is; and the worst case is still bounded.
    """
    base = PACE_DELAYS[pace or DEFAULT_PACE]
    if length <= 0:
        return base
    slowest = PACE_DELAYS["slow"] * length
    if slowest <= MAX_REVEAL_SECONDS:
        return base
    return base * MAX_REVEAL_SECONDS / slowest

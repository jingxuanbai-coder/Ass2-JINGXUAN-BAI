"""Paragraphs: JSON in the story file -> `Paragraph` objects.

A paragraph is the smallest thing a reader reads. It appears in five places -- a
scene's `body`, a variant's `body`, a meta `title_card`, an ending's `epilogue`,
and a `message` -- and it must mean the same thing in all five, or an author
learns that prose behaves differently depending on where it is written, which is
exactly the kind of rule a non-programmer cannot be expected to hold.

**Why this is not in `loader.py`.** It used to be, and moving it out is the whole
reason this module exists. `loader.py` imports `parse_actions` from `effects.py`,
so the moment a `message` needed to accept a register or a pace, `effects.py`
would have had to import the paragraph parser back out of `loader.py` -- a cycle.
The fix is not to break the cycle but to put the shared thing somewhere neither
of them owns. This is the pattern the rest of the package already uses:
`conditions.py` owns conditions, `effects.py` owns actions, `prose.py` owns
paragraphs. The alternative, hanging this parser off `effects.py`, would put
*scene body* parsing inside the actions module.

`optional_pace` came along for the same reason, and it is the subtle half. It is
called both from here and from `loader.py` (a scene has a pace, and so does a
variant). Leaving it behind would have reconnected the cycle through the back
door, and the error you get from that names neither of the two modules
responsible.
"""

from __future__ import annotations

from typing import Any, Mapping

from .errors import Pointer, StoryError
from .model import PACES, PARAGRAPH_STYLES, Paragraph
from .shape import (
    describe,
    reject_unknown_keys,
    require_choice_of,
    require_keys_present,
    require_list,
    require_text,
)

#: The keys an author may write on the object form of a paragraph.
PARAGRAPH_KEYS = frozenset({"text", "style", "pace"})

#: What a paragraph is called in an error, when nothing more specific applies.
GENERIC = "a paragraph"


def parse_paragraphs(raw: Any, pointer: Pointer, what: str = "prose") -> tuple[Paragraph, ...]:
    """Parse a list of paragraphs.

    `what` only ever changes the wording of a *list-level* error, such as
    `expected a list for prose`. It defaults to "prose" because the commonest
    caller is a scene body, where the author wrote ``"body"`` and the key is
    already named in the pointer above it.

    Each item is parsed with the generic wording, not with `what`. That is
    deliberate: it is what this function produced before it moved out of
    `loader.py`, and a move that quietly reworded every paragraph diagnostic
    would be a change no test could see and every author would.
    """
    items = require_list(raw, pointer, what)
    return tuple(
        parse_paragraph(item, pointer.index(i)) for i, item in enumerate(items)
    )


def parse_paragraph(raw: Any, pointer: Pointer, what: str = GENERIC) -> Paragraph:
    """A paragraph is either bare text, or an object adding a register or a pace.

    ``"The bus leaves you where the tarmac gives up."``

    ``{ "text": "you have wanted to see this since you were eleven.",
        "style": "aside", "pace": "slow" }``

    The bare form is not a convenience for short paragraphs. It is the form that
    has to keep working forever, because it is the one a `message` has always
    accepted -- and a story written before paragraphs could carry a register must
    still load.
    """
    if isinstance(raw, str):
        return Paragraph(require_text(raw, pointer, what))

    if not isinstance(raw, dict):
        raise StoryError(
            f'{what} should be text, or an object with "text" in it, but this is {describe(raw)}',
            pointer=pointer,
            hint='either write "a line of prose", or { "text": "...", "style": "aside" }',
        )

    obj: Mapping[str, Any] = raw
    reject_unknown_keys(obj, pointer, PARAGRAPH_KEYS, what)
    require_keys_present(obj, pointer, ("text",), what)

    return Paragraph(
        text=require_text(obj["text"], pointer.key("text"), what),
        style=(
            require_choice_of(
                obj["style"],
                pointer.key("style"),
                "the registers a paragraph can be written in",
                PARAGRAPH_STYLES,
            )
            if "style" in obj
            else None
        ),
        pace=optional_pace(obj, pointer),
    )


def optional_pace(obj: Mapping[str, Any], pointer: Pointer) -> str | None:
    """The `pace` on a paragraph, a scene or a variant -- or None if unwritten."""
    if "pace" not in obj:
        return None
    return require_choice_of(
        obj["pace"], pointer.key("pace"), "the paces available", PACES
    )

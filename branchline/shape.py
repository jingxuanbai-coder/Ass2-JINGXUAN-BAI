"""Shape checks for author-supplied JSON, with located errors.

Every check here reports *what was found* as well as what was expected. A message
like "expected a list of paragraphs, found a piece of text ("The quay was...")"
tells the author what to change; "expected list, got str" does not.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from .errors import Pointer, StoryError

if TYPE_CHECKING:  # avoids a circular import at runtime; used for annotations only
    from .model import VarDecl, Vocabulary

_ANNOTATION_PREFIX = "_"


def user_keys(raw: Mapping[str, Any]) -> list[str]:
    """The keys the author actually wrote.

    Any key beginning with an underscore is an annotation and is ignored
    everywhere. JSON has no comments, and a story file written by a person will
    want them -- this is the one affordance that keeps the schema livable without
    inventing a comment syntax.
    """
    return [key for key in raw if not key.startswith(_ANNOTATION_PREFIX)]


def describe(value: Any) -> str:
    """A plain-English description of a value, for use in error messages."""
    if value is None:
        return "nothing (null)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f"a piece of text ({shorten(value)})"
    if isinstance(value, (int, float)):
        return f"a number ({value})"
    if isinstance(value, list):
        count = len(value)
        return f"a list of {count} item{'s' if count != 1 else ''}"
    if isinstance(value, dict):
        keys = ", ".join(user_keys(value)) or "only annotations"
        return f"an object with keys {keys}"
    return f"a {type(value).__name__}"


def shorten(text: str, limit: int = 40) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return f'"{flat}"'
    return f'"{flat[:limit]}..."'


def suggest(word: str, options: Iterable[str]) -> str:
    """', did you mean "choices"?' -- or an empty string when nothing is close.

    Returned with its leading punctuation so call sites can interpolate it
    directly onto the end of a sentence.
    """
    matches = difflib.get_close_matches(word, list(options), n=1, cutoff=0.6)
    return f', did you mean "{matches[0]}"?' if matches else ""


def require_object(raw: Any, pointer: Pointer, what: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StoryError(
            f"expected an object for {what}, found {describe(raw)}",
            pointer=pointer,
        )
    return raw


def require_list(raw: Any, pointer: Pointer, what: str) -> list[Any]:
    if not isinstance(raw, list):
        raise StoryError(
            f"expected a list for {what}, found {describe(raw)}",
            pointer=pointer,
            hint="wrap a single item in square brackets: [ ... ]",
        )
    return raw


def require_text(raw: Any, pointer: Pointer, what: str) -> str:
    if not isinstance(raw, str):
        raise StoryError(
            f"expected text for {what}, found {describe(raw)}",
            pointer=pointer,
        )
    if not raw.strip():
        raise StoryError(f"{what} is empty", pointer=pointer)
    return raw


def require_bool(raw: Any, pointer: Pointer, what: str) -> bool:
    if not isinstance(raw, bool):
        raise StoryError(
            f"expected true or false for {what}, found {describe(raw)}",
            pointer=pointer,
        )
    return raw


def require_number(raw: Any, pointer: Pointer, what: str) -> float:
    # bool is a subclass of int, so it must be excluded explicitly.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise StoryError(
            f"expected a number for {what}, found {describe(raw)}",
            pointer=pointer,
        )
    return float(raw)


def require_integer(raw: Any, pointer: Pointer, what: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise StoryError(
            f"expected a whole number for {what}, found {describe(raw)}",
            pointer=pointer,
        )
    return raw


#: What counts as each declared variable type. `bool` is a subclass of `int`, so
#: it has to be excluded from "int" by hand -- otherwise `true` would satisfy a
#: variable the author declared as a number.
_TYPE_TESTS = {
    "int": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "bool": lambda value: isinstance(value, bool),
    "string": lambda value: isinstance(value, str),
}


def require_matches_type(
    value: Any, declared: str, pointer: Pointer, name: str, phrase: str
) -> None:
    """Check a value against the type its variable was declared with.

    Three places ask this question -- a value about to be *set* by an action, one
    being *compared* in a condition, and the *initial* value on a declaration --
    and it is the same question with different words in the sentence. So the
    table of what counts as an int, a bool and a string lives here once, and each
    caller passes the phrase its own error should read with, because "it cannot
    start as ..." and "it cannot be set to ..." are the difference between an
    author reading the message and an author having to translate it.
    """
    if not _TYPE_TESTS[declared](value):
        raise StoryError(
            f'"{name}" is declared as {declared}, so it cannot {phrase} {describe(value)}',
            pointer=pointer,
        )


def require_id_or_list(value: Any, pointer: Pointer, what: str) -> tuple[str, ...]:
    """Accept either one id or a list of them, and normalise to a tuple.

    Story authors write both forms interchangeably ("take this" / "take these
    two"), so the schema accepts both and the normalisation happens once, here.
    """
    if isinstance(value, str):
        return (require_text(value, pointer, what),)
    items = require_list(value, pointer, what)
    if not items:
        raise StoryError(f"{what} is an empty list", pointer=pointer)
    return tuple(
        require_text(item, pointer.index(i), f"{what} entry {i}")
        for i, item in enumerate(items)
    )


def require_choice_of(
    raw: Any, pointer: Pointer, what: str, allowed: Iterable[str]
) -> str:
    options = sorted(allowed)
    if not isinstance(raw, str) or raw not in options:
        raise StoryError(
            f"'{raw}' is not one of {what}",
            pointer=pointer,
            hint=f"choose one of: {', '.join(options)}",
        )
    return raw


def reject_unknown_keys(
    raw: Mapping[str, Any],
    pointer: Pointer,
    allowed: Iterable[str],
    what: str,
) -> None:
    """Reject keys the schema does not define.

    This is what catches `choises`, `effcts` and `alll` -- misspellings that would
    otherwise be silently ignored and produce a story that quietly does not do
    what its author wrote.
    """
    allowed_set = set(allowed)
    for key in user_keys(raw):
        if key not in allowed_set:
            raise StoryError(
                f'unexpected key "{key}" in {what}{suggest(key, allowed_set)}',
                pointer=pointer.key(key),
                hint=f"{what} accepts: {', '.join(sorted(allowed_set))}",
            )


def require_declared(
    name: str, pointer: Pointer, vocab: "Vocabulary", kind: str
) -> "VarDecl | None":
    """Check that a referenced id exists in the story's declared vocabulary.

    This is the check a string mini-language could never perform: because items,
    scenes and variables are all *declared*, a typo is caught at load time with a
    suggested correction rather than silently doing nothing at run time.

    Returns the declaration for a variable (callers need its type), else None.
    """
    if kind == "scene":
        if name not in vocab.scenes:
            raise StoryError(
                f'"{name}" is not a scene in this story{suggest(name, vocab.scenes)}',
                pointer=pointer,
                hint=f"declared scenes: {vocab.declared_names('scene')}",
            )
        return None

    if kind == "item":
        if name not in vocab.items:
            raise StoryError(
                f'"{name}" is not an item this story declares{suggest(name, vocab.items)}',
                pointer=pointer,
                hint=f"declared items: {vocab.declared_names('item')}",
            )
        return None

    decl = vocab.variable(name)
    if decl is None:
        raise StoryError(
            f'"{name}" is not a variable this story declares{suggest(name, vocab.variables)}',
            pointer=pointer,
            hint=(
                f"declared variables: {vocab.declared_names('variable')}. "
                'A story must declare a variable under "variables" before it uses one'
            ),
        )
    return decl


def require_keys_present(
    raw: Mapping[str, Any], pointer: Pointer, required: Iterable[str], what: str
) -> None:
    for key in required:
        if key not in raw:
            raise StoryError(
                f"{what} is missing required key \"{key}\"",
                pointer=pointer,
                hint=f"{what} must include: {', '.join(sorted(required))}",
            )

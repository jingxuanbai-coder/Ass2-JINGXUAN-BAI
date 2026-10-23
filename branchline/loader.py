"""Reading a story file: JSON on disk -> a `Story`.

The loader is the boundary where a file written by a person becomes data the
engine can trust. Everything checkable is checked here, at load time, with a
message naming the exact place in the file -- because the alternative is an
author staring at a game that silently does not do what they wrote.

It is also the answer to "how do we know the author never has to touch Python?":
every rule in this module is a rule the author can *see* fail, in their own file,
in their own words.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .conditions import parse_condition
from .effects import parse_actions
from .errors import Pointer, StoryError
from .model import (
    ENDING_KINDS,
    VARIABLE_TYPES,
    Action,
    Choice,
    Ending,
    Goto,
    Item,
    Meta,
    Scene,
    Story,
    VarDecl,
    Variant,
    Vocabulary,
)
from .prose import optional_pace, parse_paragraphs
from .shape import (
    describe,
    reject_unknown_keys,
    require_bool,
    require_choice_of,
    require_declared,
    require_keys_present,
    require_list,
    require_matches_type,
    require_object,
    require_text,
    user_keys,
)

REQUIRED_FORMAT = "branchline.story"
SUPPORTED_FORMAT_VERSIONS = frozenset({1})

#: Choices are picked by pressing a single digit.
MAX_CHOICES_PER_SCENE = 9

TOP_LEVEL_KEYS = frozenset(
    {"format", "format_version", "start", "meta", "variables", "items", "endings", "scenes"}
)
META_KEYS = frozenset({"title", "author", "subtitle", "title_card"})
VARIABLE_KEYS = frozenset({"type", "initial", "label", "hud"})
ITEM_KEYS = frozenset({"name", "description", "art"})
ENDING_KEYS = frozenset({"title", "kind", "epilogue"})
SCENE_KEYS = frozenset({"title", "pace", "body", "variants", "on_enter", "choices", "ending"})
CHOICE_KEYS = frozenset(
    {"text", "to", "id", "once", "when", "enabled_when", "locked_hint", "effects"}
)
VARIANT_KEYS = frozenset({"when", "title", "body", "pace"})

#: Shared by the three rules about a scene that always jumps away on entry.
#: They are one idea -- "this scene is a corridor, not a room" -- so they say so
#: once, and say the same thing, rather than three near-misses.
_CONNECTIVE_HINT = (
    "a scene that always jumps away is passed through, never shown. Carry the "
    'prose with the jump instead: "on_enter": [ { "message": [ ... ] }, '
    '{ "goto": ... } ]'
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_story(path: str | Path) -> Story:
    """Read a story file and return it as a `Story`, or explain precisely why not."""
    source = Path(path)

    # Checked rather than caught: on Windows, reading a directory raises
    # PermissionError rather than IsADirectoryError, which would be reported as a
    # permissions problem the author cannot act on.
    if source.is_dir():
        raise StoryError("this is a folder, not a story file", path=source)

    try:
        # utf-8-sig is a superset of utf-8 that also tolerates the byte order mark
        # Notepad writes. Plain utf-8 would otherwise mangle the file's first key.
        text = source.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise StoryError("there is no story file here", path=source) from None
    except PermissionError:
        raise StoryError(
            "this file could not be read", path=source, hint="is it open in another program?"
        ) from None
    except UnicodeDecodeError as exc:
        raise StoryError(
            f"this file is not readable as text ({exc.reason})",
            path=source,
            hint="a story file must be saved as UTF-8",
        ) from None

    try:
        raw = json.loads(
            text,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_no_exotic_numbers,
        )
    except json.JSONDecodeError as exc:
        raise StoryError(
            f"this is not valid JSON: {exc.msg}",
            path=source,
            line=exc.lineno,
            column=exc.colno,
            hint="a missing comma, or a comma left after the last item, are the usual causes",
        ) from None
    except StoryError as exc:
        exc.path = source
        raise

    return parse_story(raw, source)


def parse_story(raw: Any, source: Path | None = None) -> Story:
    """Interpret an already-parsed story document.

    Split out from `load_story` so that "reading a file" and "understanding what
    is in it" are separable. Tests use this directly to hand the loader a
    deliberately broken document without writing one to disk first.

    `source` is used only to label errors; pass it whenever the document came
    from a file, so that a diagnosis can name the file it is about.
    """
    try:
        return _build_story(raw, source)
    except StoryError as exc:
        if exc.path is None and source is not None:
            exc.path = source
        raise


def _build_story(raw: Any, source: Path | None) -> Story:
    root = Pointer()
    obj = require_object(raw, root, "the story file")

    version = _check_format(obj, root)
    reject_unknown_keys(obj, root, TOP_LEVEL_KEYS, "the story file")
    require_keys_present(obj, root, ("start", "meta", "scenes"), "the story file")

    meta = _parse_meta(obj["meta"], root.key("meta"))
    variables = _parse_variables(obj.get("variables", {}), root.key("variables"))
    items = _parse_items(obj.get("items", {}), root.key("items"))
    endings = _parse_endings(obj.get("endings", {}), root.key("endings"))

    scenes_raw = require_object(obj["scenes"], root.key("scenes"), '"scenes"')
    scene_ids = user_keys(scenes_raw)
    if not scene_ids:
        raise StoryError(
            "this story has no scenes",
            pointer=root.key("scenes"),
            hint="a story needs at least one scene for the reader to begin in",
        )

    # Scene ids are known before any scene is parsed, which is what lets every
    # link inside a scene be checked as it is read.
    vocab = Vocabulary(
        scenes=frozenset(scene_ids),
        items=frozenset(items),
        variables=variables,
    )

    start = require_text(obj["start"], root.key("start"), '"start"')
    if start not in vocab.scenes:
        raise StoryError(
            f'"start" points at "{start}", which is not a scene',
            pointer=root.key("start"),
            hint=f"declared scenes: {vocab.declared_names('scene')}",
        )

    scenes = {
        scene_id: _parse_scene(
            scene_id, scenes_raw[scene_id], root.key("scenes").key(scene_id), vocab, endings
        )
        for scene_id in scene_ids
    }

    return Story(
        start=start,
        scenes=scenes,
        variables=variables,
        items=items,
        endings=endings,
        meta=meta,
        format_version=version,
        source=source,
    )


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject an object that names the same key twice.

    `json` silently keeps the last one, so an author who pastes a scene in twice
    loses the earlier copy with no warning at all. This runs for every object in
    the file, at every depth.
    """
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise StoryError(
                f'"{key}" appears twice in the same object',
                hint="JSON keeps only the last one, so the first would be lost silently",
            )
        seen[key] = value
    return seen


def _no_exotic_numbers(name: str) -> Any:
    """Reject NaN and Infinity, which Python accepts but strict JSON does not."""
    raise StoryError(
        f'"{name}" is not valid JSON',
        hint="NaN and Infinity are a Python extension; other editors will reject this file",
    )


def _check_format(obj: dict[str, Any], root: Pointer) -> int:
    if "format" not in obj:
        raise StoryError(
            "this file does not say what it is",
            pointer=root,
            hint=f'a BranchLine story begins with "format": "{REQUIRED_FORMAT}"',
        )
    fmt = obj["format"]
    if fmt != REQUIRED_FORMAT:
        raise StoryError(
            f"this is not a BranchLine story (its format is {describe(fmt)})",
            pointer=root.key("format"),
            hint=f'expected "format": "{REQUIRED_FORMAT}"',
        )

    version = obj.get("format_version")
    if version is None:
        raise StoryError(
            "the story does not say which version of the format it uses",
            pointer=root,
            hint=f'add "format_version": {max(SUPPORTED_FORMAT_VERSIONS)}',
        )
    if isinstance(version, bool) or not isinstance(version, int):
        raise StoryError(
            f'"format_version" should be a whole number, found {describe(version)}',
            pointer=root.key("format_version"),
        )
    if version not in SUPPORTED_FORMAT_VERSIONS:
        known = ", ".join(str(v) for v in sorted(SUPPORTED_FORMAT_VERSIONS))
        raise StoryError(
            f"this story uses format version {version}, which this build does not know",
            pointer=root.key("format_version"),
            hint=f"this build reads format versions: {known}",
        )
    return version


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


def _parse_meta(raw: Any, pointer: Pointer) -> Meta:
    obj = require_object(raw, pointer, '"meta"')
    reject_unknown_keys(obj, pointer, META_KEYS, '"meta"')
    require_keys_present(obj, pointer, ("title",), '"meta"')

    return Meta(
        title=require_text(obj["title"], pointer.key("title"), "the story title"),
        author=_optional_text(obj, "author", pointer),
        subtitle=_optional_text(obj, "subtitle", pointer),
        title_card=parse_paragraphs(obj.get("title_card", []), pointer.key("title_card")),
    )


def _parse_variables(raw: Any, pointer: Pointer) -> dict[str, VarDecl]:
    """Parse the story's declared variables.

    Declaring them is what buys the closed vocabulary: a `set` or `inc` aimed at
    a name the story never declared is a load-time error with a spelling
    suggestion, rather than a silent no-op discovered during play.
    """
    obj = require_object(raw, pointer, '"variables"')
    out: dict[str, VarDecl] = {}

    for name in user_keys(obj):
        here = pointer.key(name)
        what = f'the declaration of variable "{name}"'
        spec = require_object(obj[name], here, what)
        reject_unknown_keys(spec, here, VARIABLE_KEYS, what)
        require_keys_present(spec, here, ("type", "initial"), what)

        vtype = require_choice_of(
            spec["type"], here.key("type"), "the types a variable can have", VARIABLE_TYPES
        )
        require_matches_type(spec["initial"], vtype, here.key("initial"), name, "start as")

        hud = (
            require_bool(spec["hud"], here.key("hud"), f'"hud" on "{name}"')
            if "hud" in spec
            else False
        )
        label = _optional_text(spec, "label", here)
        if hud and not label:
            raise StoryError(
                f'"{name}" is shown on the status line but has no "label"',
                pointer=here,
                hint=f'add "label": "{name}" so the status line can name it',
            )

        out[name] = VarDecl(
            name=name, type=vtype, initial=spec["initial"], label=label, hud=hud
        )

    return out


def _parse_items(raw: Any, pointer: Pointer) -> dict[str, Item]:
    obj = require_object(raw, pointer, '"items"')
    out: dict[str, Item] = {}

    for item_id in user_keys(obj):
        here = pointer.key(item_id)
        what = f'the declaration of item "{item_id}"'
        spec = require_object(obj[item_id], here, what)
        reject_unknown_keys(spec, here, ITEM_KEYS, what)
        require_keys_present(spec, here, ("name",), what)

        out[item_id] = Item(
            id=item_id,
            name=require_text(spec["name"], here.key("name"), f'the name of "{item_id}"'),
            description=_optional_text(spec, "description", here) or "",
            art=_optional_text(spec, "art", here),
        )

    return out


def _parse_endings(raw: Any, pointer: Pointer) -> dict[str, Ending]:
    obj = require_object(raw, pointer, '"endings"')
    out: dict[str, Ending] = {}

    for ending_id in user_keys(obj):
        here = pointer.key(ending_id)
        what = f'the declaration of ending "{ending_id}"'
        spec = require_object(obj[ending_id], here, what)
        reject_unknown_keys(spec, here, ENDING_KEYS, what)
        require_keys_present(spec, here, ("title", "epilogue"), what)

        epilogue = parse_paragraphs(spec["epilogue"], here.key("epilogue"))
        if not epilogue:
            raise StoryError(
                f'ending "{ending_id}" has no epilogue',
                pointer=here.key("epilogue"),
                hint="an ending is the last thing the reader reads; give it some prose",
            )

        kind = (
            require_choice_of(
                spec["kind"], here.key("kind"), "the kinds of ending", ENDING_KINDS
            )
            if "kind" in spec
            else "neutral"
        )

        out[ending_id] = Ending(
            id=ending_id,
            title=require_text(spec["title"], here.key("title"), f'the title of "{ending_id}"'),
            epilogue=epilogue,
            kind=kind,
        )

    return out


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


def _parse_scene(
    scene_id: str,
    raw: Any,
    pointer: Pointer,
    vocab: Vocabulary,
    endings: dict[str, Ending],
) -> Scene:
    what = f'scene "{scene_id}"'
    obj = require_object(raw, pointer, what)
    reject_unknown_keys(obj, pointer, SCENE_KEYS, what)
    require_keys_present(obj, pointer, ("title",), what)

    choices = tuple(
        _parse_choice(choice, pointer.key("choices").index(i), vocab, scene_id, i)
        for i, choice in enumerate(_optional_list(obj, "choices", pointer))
    )
    _reject_duplicate_choice_ids(choices, pointer.key("choices"), scene_id)

    on_enter = (
        parse_actions(obj["on_enter"], pointer.key("on_enter"), vocab)
        if "on_enter" in obj
        else ()
    )
    ending = _parse_scene_ending(obj, pointer, endings)

    forced_exit = any(isinstance(action, Goto) for action in on_enter)

    if ending is not None and choices:
        raise StoryError(
            f'{what} has both an "ending" and choices',
            pointer=pointer,
            hint=(
                "it cannot do both -- the ending would stop the reader before the "
                "choices were ever shown. Give the ending its own scene and link to it"
            ),
        )
    if forced_exit and choices:
        raise StoryError(
            f'{what} always jumps away on entry, so its {len(choices)} choices can never be reached',
            pointer=pointer.key("on_enter"),
            hint=(
                "the unconditional \"goto\" fires before the reader sees anything. "
                "Either remove it, or guard it with {\"when\": ..., \"do\": [{\"goto\": ...}]}"
            ),
        )
    if not choices and ending is None and not forced_exit:
        raise StoryError(
            f"{what} is a dead end",
            pointer=pointer,
            hint=(
                'it has no "choices", no "ending", and no unconditional "goto" in '
                '"on_enter", so the reader would be stuck with nothing to do'
            ),
        )
    if len(choices) > MAX_CHOICES_PER_SCENE:
        raise StoryError(
            f'{what} offers {len(choices)} choices, but only {MAX_CHOICES_PER_SCENE} can be shown',
            pointer=pointer.key("choices"),
            hint="choices are picked with a single keypress, so nine is the limit",
        )

    # The scene is only ever passed through, so anything the reader was supposed
    # to see must travel with the jump. Rejecting this is the whole point: prose
    # that is written and never read is invisible in play, and the only place to
    # notice it is here.
    if forced_exit:
        if "body" in obj:
            raise StoryError(
                f'{what} always jumps away on entry, so nobody would ever read its "body"',
                pointer=pointer.key("body"),
                hint=_CONNECTIVE_HINT,
            )
        if "variants" in obj:
            raise StoryError(
                f'{what} always jumps away on entry, so nobody would ever see its "variants"',
                pointer=pointer.key("variants"),
                hint=_CONNECTIVE_HINT,
            )
        if ending is not None:
            raise StoryError(
                f'{what} always jumps away on entry, so its ending is never reached',
                pointer=pointer.key("ending"),
                hint=_CONNECTIVE_HINT,
            )

    if choices and all(choice.when is not None for choice in choices):
        raise StoryError(
            f"every one of {what}'s {len(choices)} choices can be hidden",
            pointer=pointer.key("choices"),
            hint=(
                "if none of their conditions hold, the reader is left with nothing "
                "to press and the story stops there. Leave at least one choice "
                "without a \"when\""
            ),
        )

    return Scene(
        id=scene_id,
        title=require_text(obj["title"], pointer.key("title"), f"the title of {what}"),
        body=parse_paragraphs(obj["body"], pointer.key("body")) if "body" in obj else (),
        choices=choices,
        variants=(
            _parse_variants(obj["variants"], pointer.key("variants"), vocab)
            if "variants" in obj
            else ()
        ),
        on_enter=on_enter,
        ending=ending,
        pace=optional_pace(obj, pointer),
    )


def _parse_scene_ending(
    obj: dict[str, Any], pointer: Pointer, endings: dict[str, Ending]
) -> str | None:
    if "ending" not in obj:
        return None
    ending_id = require_text(obj["ending"], pointer.key("ending"), '"ending"')
    if ending_id not in endings:
        declared = ", ".join(sorted(endings)) or "(none declared)"
        raise StoryError(
            f'"{ending_id}" is not an ending this story declares',
            pointer=pointer.key("ending"),
            hint=f"declared endings: {declared}",
        )
    return ending_id


def _parse_choice(
    raw: Any, pointer: Pointer, vocab: Vocabulary, scene_id: str, index: int
) -> Choice:
    what = f'choice {index + 1} of scene "{scene_id}"'
    obj = require_object(raw, pointer, what)
    reject_unknown_keys(obj, pointer, CHOICE_KEYS, what)
    require_keys_present(obj, pointer, ("text", "to"), what)

    if "enabled_when" in obj and "locked_hint" not in obj:
        raise StoryError(
            f'{what} is gated with "enabled_when" but has no "locked_hint"',
            pointer=pointer,
            hint=(
                "the reader will see it dimmed and find that it will not open. "
                'Without a hint they cannot tell whether that is the story or the '
                'program. Say what it wants, e.g. "locked_hint": "the lock wants a key"'
            ),
        )

    destination = require_text(obj["to"], pointer.key("to"), f'the destination of {what}')
    require_declared(destination, pointer.key("to"), vocab, "scene")

    once = (
        require_bool(obj["once"], pointer.key("once"), f'"once" on {what}')
        if "once" in obj
        else False
    )
    choice_id = _optional_text(obj, "id", pointer)
    if once and not choice_id:
        raise StoryError(
            f"{what} is marked \"once\" but has no \"id\"",
            pointer=pointer,
            hint=(
                'give it one, e.g. "id": "read_the_notice". Without an id the engine '
                "would have to remember the choice by its position in the list, and "
                "inserting a new choice above it later would move that memory onto "
                "the wrong option"
            ),
        )

    return Choice(
        text=require_text(obj["text"], pointer.key("text"), f'the text of {what}'),
        to=destination,
        id=choice_id,
        once=once,
        when=(
            parse_condition(obj["when"], pointer.key("when"), vocab)
            if "when" in obj
            else None
        ),
        enabled_when=(
            parse_condition(obj["enabled_when"], pointer.key("enabled_when"), vocab)
            if "enabled_when" in obj
            else None
        ),
        locked_hint=_optional_text(obj, "locked_hint", pointer),
        effects=(
            parse_actions(obj["effects"], pointer.key("effects"), vocab)
            if "effects" in obj
            else ()
        ),
    )


def _reject_duplicate_choice_ids(
    choices: tuple[Choice, ...], pointer: Pointer, scene_id: str
) -> None:
    seen: set[str] = set()
    for choice in choices:
        if choice.id is None:
            continue
        if choice.id in seen:
            raise StoryError(
                f'scene "{scene_id}" uses the choice id "{choice.id}" twice',
                pointer=pointer,
                hint="ids must be unique within a scene -- they are how the engine remembers what has been used",
            )
        seen.add(choice.id)


def _parse_variants(raw: Any, pointer: Pointer, vocab: Vocabulary) -> tuple[Variant, ...]:
    items = require_list(raw, pointer, '"variants"')
    out: list[Variant] = []

    for index, item in enumerate(items):
        here = pointer.index(index)
        what = f"variant {index + 1}"
        obj = require_object(item, here, what)
        reject_unknown_keys(obj, here, VARIANT_KEYS, what)
        require_keys_present(obj, here, ("when",), what)

        title = _optional_text(obj, "title", here)
        body = parse_paragraphs(obj["body"], here.key("body")) if "body" in obj else None
        pace = optional_pace(obj, here)

        if title is None and body is None and pace is None:
            raise StoryError(
                f"{what} changes nothing",
                pointer=here,
                hint='a variant must override "title", "body" or "pace" to be worth writing',
            )

        out.append(
            Variant(
                when=parse_condition(obj["when"], here.key("when"), vocab),
                title=title,
                body=body,
                pace=pace,
            )
        )

    return tuple(out)


# ---------------------------------------------------------------------------
# Small shared readers
# ---------------------------------------------------------------------------


def _optional_text(obj: dict[str, Any], key: str, pointer: Pointer) -> str | None:
    if key not in obj:
        return None
    return require_text(obj[key], pointer.key(key), f'"{key}"')


def _optional_list(obj: dict[str, Any], key: str, pointer: Pointer) -> list[Any]:
    if key not in obj:
        return []
    return require_list(obj[key], pointer.key(key), f'"{key}"')


# Re-exported so callers can catch one exception type without knowing the module layout.
__all__ = [
    "load_story",
    "parse_story",
    "StoryError",
    "REQUIRED_FORMAT",
    "SUPPORTED_FORMAT_VERSIONS",
]

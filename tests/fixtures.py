"""Shared helpers for the test suite.

Tests build story documents by mutating a fresh copy of the happy-path fixture
rather than keeping a file per failure mode. One file per breakage means a reader
has to diff two near-identical JSON files to see what went wrong; mutating in
place shows the single broken line right next to the assertion about it.

Only failures that *cannot* be expressed as a Python dict -- duplicate keys,
malformed JSON, exotic numbers -- need real files, because they are properties of
the text rather than of the parsed document.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from branchline import StoryError, load_story, parse_story
from branchline.errors import Pointer
from branchline.model import Paragraph, Story, Vocabulary

FIXTURE_DIR = Path(__file__).parent / "fixtures"
MINIMAL_PATH = FIXTURE_DIR / "minimal_story.json"


def said(*texts: str) -> tuple[Paragraph, ...]:
    """Prose the world offers, in the plain register.

    A `message` used to be a tuple of bare strings; it is a tuple of `Paragraph`
    now, so that the world's reply can be an aside like anything else. Spelling
    the objects out at each comparison would bury the sentence being asserted
    under the machinery carrying it, so they are built here instead.
    """
    return tuple(Paragraph(text) for text in texts)


def minimal_document() -> dict[str, Any]:
    """A fresh, valid copy of the happy-path story, safe to mutate."""
    return json.loads(MINIMAL_PATH.read_text(encoding="utf-8"))


def minimal_story() -> Story:
    return parse_story(minimal_document())


def minimal_vocabulary() -> Vocabulary:
    return minimal_story().vocabulary()


def root_pointer() -> Pointer:
    return Pointer()


def load_raw_text(text: str) -> Story:
    """Load story text from a throwaway file, for failures that live in the text."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "story.json"
        path.write_text(text, encoding="utf-8")
        return load_story(path)


class StoryTestCase(unittest.TestCase):
    """Assertions about *what the author is told*, not merely that something raised."""

    def assertRejects(
        self,
        document: Any,
        *,
        mentions: tuple[str, ...] = (),
        pointer: str | None = None,
    ) -> StoryError:
        with self.assertRaises(StoryError) as caught:
            parse_story(document)
        self._assert_diagnosis(caught.exception, mentions=mentions, pointer=pointer)
        return caught.exception

    def assertRejectsText(
        self,
        text: str,
        *,
        mentions: tuple[str, ...] = (),
        pointer: str | None = None,
    ) -> StoryError:
        with self.assertRaises(StoryError) as caught:
            load_raw_text(text)
        self._assert_diagnosis(caught.exception, mentions=mentions, pointer=pointer)
        return caught.exception

    def assertRejectsCondition(
        self,
        condition: Any,
        *,
        mentions: tuple[str, ...] = (),
        pointer: str | None = None,
    ) -> StoryError:
        from branchline.conditions import parse_condition

        with self.assertRaises(StoryError) as caught:
            parse_condition(condition, root_pointer(), minimal_vocabulary())
        self._assert_diagnosis(caught.exception, mentions=mentions, pointer=pointer)
        return caught.exception

    def assertRejectsAction(
        self,
        action: Any,
        *,
        mentions: tuple[str, ...] = (),
        pointer: str | None = None,
    ) -> StoryError:
        from branchline.effects import parse_action

        with self.assertRaises(StoryError) as caught:
            parse_action(action, root_pointer(), minimal_vocabulary())
        self._assert_diagnosis(caught.exception, mentions=mentions, pointer=pointer)
        return caught.exception

    def _assert_diagnosis(
        self, error: StoryError, *, mentions: tuple[str, ...], pointer: str | None
    ) -> None:
        rendered = str(error)
        for fragment in mentions:
            self.assertIn(
                fragment,
                rendered,
                f"the message should mention {fragment!r}, but reads:\n{rendered}",
            )
        if pointer is not None:
            self.assertIn(
                pointer,
                rendered,
                f"the message should locate the problem at {pointer!r}, but reads:\n{rendered}",
            )


def clone(document: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(document)


__all__ = [
    "StoryTestCase",
    "clone",
    "load_raw_text",
    "minimal_document",
    "minimal_story",
    "minimal_vocabulary",
    "root_pointer",
]

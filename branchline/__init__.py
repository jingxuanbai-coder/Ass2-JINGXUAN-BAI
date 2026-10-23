"""BranchLine -- an interactive fiction engine in which the story lives in data.

The engine knows how to combine condition trees, apply actions and (from W9) draw
scenes. It does not know one word of any story. Everything the reader reads comes
out of a JSON file, which is the whole claim this project is making.
"""

from .engine import (
    ChoiceLocked,
    Engine,
    EngineError,
    NoSuchOption,
    Option,
    SceneView,
    Turn,
)
from .errors import StoryError
from .loader import load_story, parse_story
from .model import Story
from .state import GameState

__version__ = "0.2.0"

__all__ = [
    "ChoiceLocked",
    "Engine",
    "EngineError",
    "GameState",
    "NoSuchOption",
    "Option",
    "SceneView",
    "Story",
    "StoryError",
    "Turn",
    "__version__",
    "load_story",
    "parse_story",
]

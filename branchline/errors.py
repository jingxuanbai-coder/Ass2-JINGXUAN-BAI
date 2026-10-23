"""Located errors for the files this program reads.

The whole premise of BranchLine is that someone who does not program can edit the
story JSON safely. That premise only holds if a mistake produces a message naming
the file, the exact place inside it, and what is wrong, in plain words -- never a
bare ``KeyError``. This module exists so that precise reporting is the default
rather than something remembered at each raise site.

A story file is not the only one. A save file, which is binary and therefore
*less* legible than the story, is diagnosed through this same class and rendered
in this same shape (:mod:`branchline.save`) -- one way of explaining a file, for
both kinds of file, so that a reader never has to tell the two apart.
"""

from __future__ import annotations

from pathlib import Path


class Pointer:
    """A path into the story JSON, e.g. ``scenes.quay.choices[1].to``.

    Built up as parsing descends, so the location is known at the point of
    failure instead of reconstructed afterwards.
    """

    __slots__ = ("_parts",)

    def __init__(self, parts: tuple[str, ...] = ()) -> None:
        self._parts = parts

    def key(self, name: object) -> "Pointer":
        """Descend into an object member."""
        return Pointer(self._parts + (str(name),))

    def index(self, position: int) -> "Pointer":
        """Descend into a list element."""
        return Pointer(self._parts + (f"[{position}]",))

    @property
    def is_root(self) -> bool:
        return not self._parts

    def __str__(self) -> str:
        out = ""
        for part in self._parts:
            if part.startswith("["):
                out += part          # list subscripts bind tight: choices[1]
            elif out:
                out += "." + part
            else:
                out = part
        return out or "(root)"


class StoryError(Exception):
    """A problem in a file, located precisely enough for whoever it belongs to.

    Rendered as::

        story/sample.json: scenes.quay.choices[1].to
          -> 'carrage_9' is not a defined scene
          hint: declared scenes are: carriage_7, quay, signal_box

    ``path`` is attached by the loader, which is the only layer that knows which
    file is being read; the parsers below it supply the pointer alone.
    """

    def __init__(
        self,
        message: str,
        *,
        pointer: Pointer | None = None,
        path: Path | str | None = None,
        hint: str = "",
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.pointer = pointer if pointer is not None else Pointer()
        self.path = Path(path) if path is not None else None
        self.hint = hint
        self.line = line
        self.column = column

    def __str__(self) -> str:
        # Prefer a line/column (for syntax errors) over a JSON pointer, and omit
        # the location entirely when the problem is the file itself.
        if self.line is not None:
            location = f"line {self.line}, column {self.column}"
        elif not self.pointer.is_root:
            location = str(self.pointer)
        else:
            location = ""

        if self.path is not None:
            head = f"{self.path}: {location}" if location else str(self.path)
        else:
            head = location or "(no location)"

        lines = [head, f"  -> {self.message}"]
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        return "\n".join(lines)

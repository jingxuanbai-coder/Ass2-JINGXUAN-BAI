# BranchLine

An interactive fiction engine that runs in the terminal.

**The claim:** *story in data, not in code.* Everything the reader sees lives in
a JSON file. A person who does not program can add a whole chapter by editing
that file and never opening a Python one.

This is an art project rather than a tool. The comparison it is drawing is with
the usual beginner interactive fiction, where the story is written *inside* the
program — a chain of `if` and `elif` where the prose and the control flow are the
same text, so editing a sentence means editing program logic. BranchLine is an
attempt to see how far that separation can be pushed before something has to
break. The terminal is the entire stage: no game engine, no framework.

---

## Running it

Requires **Python 3.12**. *Playing* a story also needs Rich; *checking* one needs
nothing but Python itself.

```powershell
# one-time setup
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```powershell
# play the demo story
.\.venv\Scripts\python.exe main.py story\observatory.json --play

# report what the loader found in a story, without playing it
.\.venv\Scripts\python.exe main.py story\observatory.json --check

# a seed makes a run reproducible; it is printed at the start
.\.venv\Scripts\python.exe main.py story\observatory.json --play --seed 1

# no typewriter, for a recording or a script
.\.venv\Scripts\python.exe main.py story\observatory.json --play --instant
```

```powershell
# run the tests
.\.venv\Scripts\python.exe -m unittest discover -t . -s tests
```

`--check` loads a story, validates it, and prints its scene graph. That output is
not decoration — it is how you can see that the file was understood. It then
reports anything the author wrote that no reader will ever see: a scene nothing
links to, an ending nothing reaches, an item nothing takes, a variable nothing
reads. **If there is anything in that report, `--check` exits non-zero.** A check
that finds a problem and succeeds anyway is not a check; a story with nothing to
report exits 0 and says so out loud.

`--play` walks through the story from the keyboard, in the story's own voice. The
prose arrives a character at a time at the pace the author asked for; **any key
skips to the end of the paragraph**, and every paragraph after it. An `aside` is
set in and italic, a `letter` is warm, a `whisper` is barely there. Locked
options are dimmed with the author's hint beneath them, and the ending lands in
the colour of its mood.

The typewriter turns itself off whenever the output is not a terminal — a pipe, a
redirect, a test — because there is no reader at the other end of one.

### Keeping a run

Under the status line, every turn, the prompt says what it accepts:

```
  save · load · look · or a number
```

Type `save` and the run is written to `saves/observatory.save` and the path is
said back. Type `load` in a later session — after a confirmation, because it
discards whatever has happened since — and you are standing where you stood.
Leaving the game does not save: closing the terminal ends the run, and the only
way to keep one is to ask.

Type `look` and you are told what you are carrying. Type `look` and part of a
name — `look brass key` — and you are shown that thing: its name, the picture the
author drew for it, and the sentence they wrote about it. Items have no location
in this format and exist only in the inventory, so `look` can only ever examine
what the reader is holding; asking about anything else is answered rather than
ignored. All three words come from one tuple in `present.py`, so the prompt line
and the sentence that says what may be typed cannot drift apart.

A save holds **the reader, not the story**. It is a pickle rather than JSON,
because the story is JSON *so that a human can write it* and nobody writes a save
file; and it is gitignored, because a pickle is executable when it is read — a
save is a local file you made, not a document to hand to someone else.

If the story has changed so much that the save no longer fits — the scene you are
standing in was renamed, or an item you are carrying was — the load is refused
and *nothing* is half-applied, with every problem listed at once rather than one
per attempt. Rewriting the prose is not a change that breaks a save — that is the
entire point of storing the run and re-reading the story.

---

## What is here, and what is not

This was built in five stages, one per week. **This is stage 5 of 5, and it is
finished.**

| | | |
|---|---|---|
| ✅ | **W7** | story schema + loader — a story file becomes a checked, typed object |
| ✅ | **W8** | the engine loop: state, condition evaluation, action application |
| ✅ | **W9** | presentation: the palette, the typewriter, registers and endings |
| ✅ | **W10** | save files: a run written to disk, closed, and picked up again |
| ✅ | **W11** | the story itself, and `--check`'s report of what nobody will ever see |

W11 was the round the other four were arranged for. The demo story's prose is
finished and the draft notice that used to sit at the top of the file is gone.
The four lines the logbook has always been about are now actually delivered —
quoted in the `letter` register, the last one stopping mid-sentence because the
person writing it did. And `Item.description` and `Item.art` had been in the
schema since W7 and rendered by nothing; `look` was built so that they take
effect, and the linter so that an item which can never be looked at is a thing
the program says out loud.

The stage table used to describe W10 as save/load *plus* "paths gated on what you
are carrying". The gating half was delivered in **W8** — `enabled_when:
has_item` and a `locked_hint` are what the demo's gate has always used. Rather
than build a redundant second one, W10 proves the existing one survives a save,
which is the question a file actually raises.

---

## Layout

```
branchline/
  errors.py       StoryError, and the "path: JSON pointer" locator it renders
  model.py        the story as frozen dataclasses; the declared vocabularies
  shape.py        shared shape checks, all of which report what they found
  conditions.py   JSON -> condition tree, and how to evaluate one
  effects.py      JSON -> action list, and how to apply one
  prose.py        JSON -> paragraphs. The parser five places share
  loader.py       JSON -> Story, and every rule the file must satisfy
  state.py        GameState — everything the engine needs to answer "what now?"
  engine.py       the loop: enter a scene, offer options, take one, end
  save.py         a run written to a file, and fitted to the story on the way back
  lint.py         what the story declares that no reader will ever see
  palette.py      what a register and a mood look like. Pure data
  present.py      the drawing: reveal prose, draw a turn, ask for a number or a word
main.py           check a story, or play it
story/sample.json     a placeholder, showing the shape of a story
story/observatory.json  the demo story — ten scenes, three branch points, three endings
saves/            one slot per story, named after the story file. gitignored
tests/            556 tests, including fixtures that exercise all 18 node kinds
STORY_FORMAT.md   how to write a story — the author's document
```

`palette.py` and `present.py` sit *outside* the package's front door. Neither is
exported from `branchline/__init__.py`, and the presenter is imported by name, by
`main.py`, inside the function that plays a story — so `import branchline` never
needs Rich installed, and `--check` works on a machine that has none. The split
between the two is that `palette.py` decides *what things look like* and
`present.py` decides *where they go*; the first is data and can be tested
exhaustively, the second never invents a colour.

`conditions.py` and `effects.py` are separate from `loader.py` on purpose.
Parsing and evaluating are two halves of one job: the loader's half turns a file
into objects and rejects bad ones, and it finishes before the game starts;
*applying* a condition or an action to a live state is the engine's half.
`engine.py` decides **when** to ask — it never knows **how** to compute.

`prose.py` is separate for a duller reason that is worth recording anyway: a
`message` had to be able to carry a register, and parsing one means the paragraph
parser — which used to live in `loader.py`, which already imports `effects.py`.
So `effects.py` could not reach it, and the fix was not to break the cycle but to
give the shared thing a home that neither of them owns. That is the pattern the
rest of the package already uses, applied one more time.

`save.py` holds the run, not the story: what the reader has *done*, which is a
scene id, an inventory, some variables, some visit counts and a seeded generator.
The sentences are supplied on the way back by reading the story file again, from
disk. That way an author who rewrites a paragraph has rewritten it for everyone —
including readers who saved — and a save can never quietly serve prose that no
longer exists in the story it belongs to. It sits beside `engine.py` and needs
nothing but the standard library, so `--check` still works on a machine where
nothing has been installed.

`lint.py` is the newest file, and it is one idea: **a finding is anything the
author declared that no reader will ever perceive.** The loader already refuses
the small versions of that fault — an action written after a `goto` that always
fires, a `body` on a scene that always jumps away — but it can only see them
because both halves sit in the same list. An orphaned scene is that same fault at
the scale of the whole graph, and it takes a walk to find. Four rules, standard
library only, and it is the reason `--check` is allowed to fail: a report that
cannot be acted on is decoration.

The import graph runs one way and does not cycle:

```
errors   model   palette        import nothing from the package
  ↓
shape    state   lint
  ↓
conditions   prose
  ↓
effects
  ↓
loader
  ↓
engine   save
  ↓
present
  ↓
main
```

Each row imports only from rows above it. The arrow is a *layer*, not an edge:
`engine` and `save` reach past `loader` to the modules `loader` is itself built
on, and `palette` is reached by nothing but `present` — which is what keeps Rich
out of every path that does not draw.

**`engine.py` imports neither `rich` nor `input()`.** It is a pure state machine
driven by a presenter, which is what let W9 replace the rendering wholesale
without touching it, and what W10's save files rest on — the engine is the thing
being written to a file, so it had better not depend on a terminal. That is
asserted mechanically, not just intended — one test parses the file and checks
that no `input()` is called anywhere in it, and others run a **fresh interpreter**
to check that importing the engine — or the package — leaves `rich` out of
`sys.modules`. A fresh interpreter rather than the running one, because asking
in-process answers whether some *other* test imported Rich first.

---

## Writing a story

See **[STORY_FORMAT.md](STORY_FORMAT.md)**. It is written for someone who does
not program — that is the point of it, not a sideline.

The short version of why the format looks the way it does:

- **Conditions are data, not code.** `{"all": [{"has_item": "brass_key"},
  {"flag": "trusted"}]}` is a declarative tree the program walks. The program
  knows how to evaluate `all`, `any`, `not` and six other operators; it does not
  know a single thing about your story. A string mini-language would have been
  the obvious rival approach and was rejected precisely because it is opaque —
  a validator cannot walk `"has_item('key')"` and therefore cannot tell you that
  `cellar` is spelled `cellers`.
- **`when` and `enabled_when` are different questions.** Does this option *exist*
  for you (hidden if not), versus can you *do* it (shown, dimmed, with a hint if
  not). Which of the two a locked door should be is an authorial decision, so it
  is the author's data that makes it — not a rule buried in Python.
- **Declared vocabularies.** Items, variables, scenes and endings are all
  declared up front, which is what makes a typo an error at load time with a
  suggested correction, rather than a choice that silently does nothing.
- **Randomness only ever happens in an action, never in a condition.** A
  condition is evaluated several times per turn, so a random one would answer
  differently each time it was asked — a heisenbug with no visible cause.
- **Nothing may be written that can never happen.** A `goto` ends the list it is
  in, so anything after one is dead; a scene that always jumps away is never
  displayed, so its prose is unreadable. Both are refused at load time, and
  `--check` reports the ones that take a walk over the whole story to see — a
  scene nothing links to, an ending nothing reaches, an item nothing takes, a
  variable nothing reads. This is the project's own thesis turned on itself:
  prose that no reader will ever see is invisible in play, and the only way to
  find it is to hold the program in your head. The program holds it instead.

### Errors are the product

The authoring experience *is* the argument this project is making, so the error
messages are load-bearing. A story with a misspelled scene name does not produce
a traceback. It produces this:

```
story/your-story.json: scenes.carriage.choices[0].to
  -> "termnus" is not a scene in this story, did you mean "terminus"?
  hint: declared scenes: back, carriage, guard, platform, terminus, ticket_window
```

File, the exact place inside the JSON, what is wrong, and what to write instead.

---

## Testing

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

556 tests, in seven groups.

The first is the engine's own half — the *loader*, plus the three modules it
parses into, `conditions.py`, `effects.py` and `state.py`. The loader is tested
against a fixture built to exercise every corner of the schema, and its tests
assert on the text of error messages, not merely that something raised — a
message that names the wrong place is a bug in this project in a way it would
not be in most. One of them exists solely to assert that the fixture uses all
ten condition kinds and all eight action verbs, so the schema cannot quietly
lose a feature.

The second tests the *demo story*, against the design it is meant to implement:
that the building cannot be entered without the key, that the key is findable
from a cold start, that the story is clean, and that giving up is never gated.
They do not assert on prose, and the point of that was to find out whether they
could survive W11 rewriting every sentence in the file. They did, untouched —
which is the only evidence that the claim was ever worth making.

W11 added four of them that do assert on prose, because W11 found the fault in
the prose: the reader used to be told about four lines twice and shown none, and
`letter` was a register with a look, a chapter in the author's document and no
story that used it. So the story file is now held to handing the four lines over,
to the last one stopping mid-sentence with no mark after it, to `letter` actually
being written in, and to the epilogue not restating the scene it follows — which
it used to, sentence for sentence, which is a whole scene of prose that took
effect exactly nowhere.

The third plays the story. `test_playthrough.py` walks the real
`observatory.json` from its first scene to each of its three endings, and drives
the engine directly rather than feeding a keyboard — a test that needs someone to
type is a test that does not get run. Its sharpest assertion is that **the same
scene numbers its options differently on two visits**: at the gate without the
key the options are `1. Search the flowerbed … 4. Turn around and go home`, and
holding the key they are `1. Unlock the gate, 2. Turn around and go home`. Same
scene, same code path, different numbers and different meanings.

It also finishes the demo the long way round, **split in two at the gate** — the
first half written to a file, the second half played by an engine that read that
file back. The ending has to be the one the unsplit run reached, and it is.

The fourth is the *presentation*, and it is where the design leans hardest on a
seam that Rich happens to provide. A layer whose output is "what it looks like"
is usually left untested; but the presenter takes its `Console` as an argument,
`export_text()` returns everything that was drawn, and `export_text(styles=True)`
returns it **with the real ANSI escapes**. So "an aside is drawn as an aside" is
an assertion rather than a matter of taste, and so is "the narrator is drawn
identically everywhere else". `test_palette.py` additionally iterates the
declared vocabularies and fails if a register or a mood the schema allows has no
look — otherwise a fifth register would load perfectly happily and raise during
someone's playthrough.

The fifth tests **save files**, and its most useful test is one that would be
tempting to skip: save a run, then rewrite *every sentence in every body and
every epilogue* of the story, and assert that the save still loads with identical
state — and that the engine assembled from it then draws the **new** words. That
is this round's acceptance criterion written as an assertion, and it is the test
that fails if anyone ever "simplifies" the save by pickling the engine. A second
test reads the file's raw bytes and asserts that no sentence of the story appears
in them, which is the same claim made against the artifact rather than the code.
The rest is the reconciliation table: one test per row, each built by changing
the *state* — a save that no longer fits is what a mismatch actually is — plus a
refusal that lists every problem at once and leaves the run in progress untouched.

The sixth tests the **linter**, which is four rules and one idea: a finding is
anything the author declared that no reader will perceive. One class per rule,
plus the regression for the bug it inherited — `Story.reached_scenes()` followed
a choice's `to` but never looked inside its `effects`, so a scene reachable
*only* through a `goto` there was reported as unreachable, which is a tool crying
wolf about a story that works. Both real story files are asserted clean, and that
assertion is the same call `--check` makes.

The seventh tests `main.py` itself, by running it in a new interpreter — one of
them with `rich` made unimportable, because the format document opens by promising
an author that they need to install nothing to write a story, and `--check` is
how they check one. *Nothing imported `main.py` before this*, which is exactly
how W9 could rewire the whole entry point while the suite stayed green. Saving is
checked here the only way it can honestly be checked: **two processes**, one that
plays and types `save`, and a second that starts fresh, types `load`, and is
found standing in the room the first one walked into.

The suite passes on **Python 3.12.10**. With `rich` made unimportable it still
runs all 556 and *skips* 142, rather than dying at import — so the loader, the
engine, the save files and the linter are exercised on an interpreter that has no
presentation library at all, which is the same interpreter the promise above is
made to.

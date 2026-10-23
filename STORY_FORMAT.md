# Writing a BranchLine story

A BranchLine story is one JSON file. Everything the reader sees comes out of that
file, and nothing the reader sees is written in Python. This document describes
the whole language. If you can edit a text file, you can write one of these.

You do not need to install anything to *write* a story, and you do not need to
tell anyone which errors you made — the game reads the file before it starts, and
if something is wrong it tells you exactly where:

```
story/your-story.json: scenes.carriage.choices[0].to
  -> "termnus" is not a scene in this story, did you mean "terminus"?
  hint: declared scenes: back, carriage, guard, platform, terminus, ticket_window
```

Fix the line it names and run it again.

---

## The shape of a file

```jsonc
{
  "format": "branchline.story",   // required; tells the game this is a story
  "format_version": 1,            // required

  "start": "platform",            // the scene the reader begins in

  "meta":    { ... },             // title, author, what shows on the title card
  "variables": { ... },           // the facts the story remembers
  "items":   { ... },             // the things the reader can carry
  "endings": { ... },             // the ways it can finish
  "scenes":  { ... }              // the story itself
}
```

Anything you write whose key starts with an underscore is ignored. JSON has no
comments, so this is how you leave notes for yourself:

```json
"_todo": "the ending here is too abrupt, come back to it",
```

**A key may appear only once.** Writing the same key twice in one object is
refused rather than quietly resolved, because JSON keeps the last one and throws
the first away — which is how an author who pastes a scene in twice loses the
earlier copy without being told:

```
story/your-story.json
  -> "s" appears twice in the same object
  hint: JSON keeps only the last one, so the first would be lost silently
```

### `meta`

The few things that are true of the story rather than of anywhere inside it.

```jsonc
"meta": {
  "title": "First Light",                               // required
  "author": "Xuan",                                     // optional
  "subtitle": "an abandoned observatory, after dark",   // optional
  "title_card": [                                       // optional
    "This is a sample.",
    { "text": "Replace this file.", "style": "aside" }
  ]
}
```

`title` is the story's name and the only required key here. `author` is drawn
under it as `by <name>`, and `subtitle` is the quiet line under that — a mood, a
place, a date, whatever the title does not say by itself.

`title_card` is a list of paragraphs shown **once**, before the first scene, while
the reader is still arriving. It takes the same paragraph syntax as a scene's
`body`, so a line on it can carry a register — an `aside` on the title card is set
in like an aside anywhere else. These lines are never shown again, which is what
makes them worth writing: they are the only prose that the story says before the
reader can do anything about it.

---

## Scenes

A scene is a place the reader arrives at. It has prose, and then either a set of
choices or an ending.

```json
"ticket_window": {
  "title": "The Ticket Window",
  "pace": "slow",
  "body": [
    "The glass is scratched opaque.",
    { "text": "someone is waiting behind it.", "style": "aside" }
  ],
  "choices": [
    { "text": "Ask for a ticket", "to": "carriage" },
    { "text": "Walk away", "to": "platform" }
  ]
}
```

| key | meaning |
|---|---|
| `title` | what the scene is called, shown above the prose. Required. |
| `body` | the prose. A list of paragraphs. Optional. |
| `choices` | what the reader can do. Up to **nine**. |
| `ending` | instead of choices — the id of an ending this scene finishes on. |
| `on_enter` | things that happen on arrival, before anything is shown. |
| `variants` | alternative prose, for when the same place reads differently. See *Variants* below. |
| `pace` | `slow`, `normal` or `fast` — how quickly the prose appears. A reader can skip ahead with any key. |

**A paragraph** is either a line of text, or an object:

```json
"body": [
  "Just a line.",
  { "text": "A quieter line.", "style": "aside", "pace": "fast" }
]
```

`style` names a *register*, not a font. There are four:

| register | for |
|---|---|
| `aside` | someone thinking aloud, beside the narration rather than in it |
| `letter` | a document — a page, a note, anything written down that the reader is reading |
| `sign` | something fixed to a wall: a message that was manufactured rather than written |
| `whisper` | the quietest thing on the page, almost absent |

How a register looks is decided by the game, not by you, and no two of them look
alike. `letter` is the one worth knowing first: **quoting a document is how a story
hands the reader something the narrator did not write**, and a paragraph in a
register is the only prose on screen that is visibly not the narrator talking.

`pace` on a paragraph beats the `pace` on the scene, for that paragraph only.

### Variants

A variant is the same scene read differently. It is how you write *"this room,
but not the first time"* without writing the room twice.

```json
"vestibule": {
  "title": "Inside",
  "body": [ "A stair spirals up into the dark of the dome." ],
  "variants": [
    {
      "when": { "has_item": "brass_key" },
      "title": "Inside, At Last",
      "body": [ "You have been carrying that key for an hour." ]
    }
  ]
}
```

| key | meaning |
|---|---|
| `when` | when this variant applies. Required. |
| `title` | replaces the scene's `title`. |
| `body` | replaces the scene's `body`. |
| `pace` | replaces the scene's `pace`. |

**First match wins.** The list is read in order and the first variant whose
`when` holds is the one used. A variant is not a patch layered on the others, so
two that both apply do not combine — write the specific case first.

**A variant must change something.** One that overrides none of `title`, `body`
or `pace` is refused at load time, because there is nothing it could ever do:

```
scenes.vestibule.variants[0]
  -> variant 1 changes nothing
  hint: a variant must override "title", "body" or "pace" to be worth writing
```

**A variant is presentation only.** It changes what the reader *sees* and never
what the story *does*: the choices on offer, the things carried and the value of
every variable are the same whichever variant is showing. If you want the options
themselves to change, that belongs on the choice, in `when` or `enabled_when`.

### Emphasis

Writing `*surrounded by stars*` gives you emphasis:

```json
"body": ["The dome is *still turning*."]
```

The stars are markers and are not shown. They work in every register — the marked
words are heavier than the words around them whatever those words are already
wearing, so `*no entry*` on a `sign` and `*still turning*` inside an `aside` both
read as marked.

**A star on its own is just a star.** Nothing needs escaping: an asterisk that is
not part of a pair is printed as written, so prose about an observatory may
contain one, and `2 * 3 * 4` says what it looks like it says. Only a `*` with no
space after it, closed by a `*` with no space before it, marks anything.

**A scene must lead somewhere** — it needs choices, or an ending, or an
unconditional `goto` in `on_enter`. A scene with none of those is a dead end and
the game will refuse to start.

### Scenes that only pass through

A scene whose `on_enter` jumps away **unconditionally** is never displayed. It is
a hinge, not somewhere the reader is: useful for sending them somewhere else
based on what they are carrying, or for saying one line on the way past.

```json
"the_fall": {
  "title": "Down",
  "on_enter": [
    { "message": ["The stair gives way."] },
    { "goto": "cellar" }
  ]
}
```

Note where the prose lives. Writing it as `body` would be a mistake the game
refuses at load time rather than a mistake you find by reading carefully:

```
scenes.the_fall.body
  -> scene "the_fall" always jumps away on entry, so nobody would ever read its "body"
  hint: a scene that always jumps away is passed through, never shown. Carry the prose
        with the jump instead: "on_enter": [ { "message": [ ... ] }, { "goto": ... } ]
```

That refusal is the point of the whole design, applied to itself. A `body` here
is not merely untidy — **it is prose that no reader will ever see**, and the only
way to notice it is to hold the code in your head. The game holds it for you. The
same goes for `variants` and for `ending` on such a scene: an ending that is
declared but never reached is the same failure, and it is refused the same way.

A scene that jumps away *conditionally* is fine — it is sometimes displayed, so
its prose is sometimes read. This is refused only when the jump is unavoidable.

Passing through still counts as a visit, so `{ "visited": "the_fall" }` is
meaningful even though `the_fall` is never shown.

---

## Choices

A choice is one option. `text` is what the reader reads; `to` is where it goes.

```json
{
  "text": "Use the small brass key",
  "to": "cellar",
  "id": "unlock_with_key",
  "once": true,
  "enabled_when": { "has_item": "brass_key" },
  "locked_hint": "you would need something small and metal",
  "effects": [{ "set": { "trusted": true } }]
}
```

### The two kinds of gate

This is the most important thing in this document, and the two are not
interchangeable.

| | the question it asks | when it fails |
|---|---|---|
| `when` | does this option **exist** for you? | the option is not shown at all |
| `enabled_when` | can you **do** it? | the option is shown, dimmed, with `locked_hint` under it |

Use `when` for story: *"Ask the guard about the branch line"* should not appear
before you have met the guard. Use `enabled_when` for an obstacle the reader
should be able to see: a locked door they lack the key for. Showing the locked
option is usually the better story — it tells the reader what kind of world they
are in — and it saves you writing a second version of the scene for readers who
have not got there yet.

A choice with `enabled_when` **must** have a `locked_hint`. A dimmed option with
no explanation is the game shrugging at the reader: they can see there is a way
forward and cannot tell what it wants. The hint is one line, in the story's
voice, and it is the difference between a puzzle and a wall.

```json
{
  "text": "Unlock the gate",
  "to": "vestibule",
  "enabled_when": { "has_item": "brass_key" },
  "locked_hint": "the lock wants something small and metal"
}
```

Note what the hint does *not* do: it names the *kind* of thing wanted, not where
it is. Telling the reader the key is in the flowerbed would solve the puzzle for
them.

### A scene cannot hide all of its options

At least one choice in a scene must have no `when` at all. If every option can be
hidden, there is a state the reader can reach with nothing on screen to press,
and the story stops without saying why. The game refuses to load a scene that
could do this — the failure is unreachable by inspection and unmissable in play.

`enabled_when` is deliberately *not* covered by this rule. A room where every
option is locked until you come back with the key is a real thing to write, and
the reader is fine: they can see the options, read the hints, and leave.

### Numbering

The reader picks options by number, so the numbers have to line up with what is
on screen. Two consequences worth knowing, because they are visible:

- **Hidden choices do not use up a number.** If the first choice is hidden, the
  second one is `1`, not `2`. A gap would be a number that does nothing, which in
  a terminal reads as a broken program rather than as a hidden option.
- **Locked choices keep their number.** They are on screen, so they can be
  pressed — they simply refuse, and say why.

So the same scene can number its options differently on two visits, if a choice
in it is gated:

| at the gate, no key | at the gate, holding the key |
|---|---|
| `1. Search the flowerbed` | `1. Unlock the gate` |
| `2. Push at the door` | `2. Turn around and go home` |
| `3. Unlock the gate` *(dimmed)* | |
| `4. Turn around and go home` | |

This is not a special case in the engine; it is what "number what is on screen"
means when what is on screen can change. But it is worth seeing once, because an
author who expects fixed numbers will write prose that refers to them.

`once` means the choice disappears after it has been used. A choice with `once`
**must** have an `id`. The id is how the game remembers which choice was taken;
without one it would have to remember by position in the list, and the next time
you inserted a choice above it, the memory would silently move to the wrong
option.

**An `id` must be unique within its scene.** Two choices on the same scene cannot
share one, because the game would have no way to tell which of them it had
already remembered:

```
story/your-story.json: scenes.carriage.choices
  -> scene "carriage" uses the choice id "look" twice
  hint: ids must be unique within a scene -- they are how the engine remembers what has been used
```

---

## Conditions

A condition is a question about the reader's state. You can ask it in `when`,
`enabled_when`, a `variant`, or a guarded action.

```json
{ "has_item": "brass_key" }
{ "flag": "trusted" }
{ "var": "lamps_lit", "at_least": 4 }
{ "var": "mood", "is": "generous" }
{ "visited": "signal_box" }
{ "visits": { "scene": "hall", "at_least": 2 } }
{ "first_time": true }
{ "not": { "has_item": "brass_key" } }
{ "all": [ { "has_item": "brass_key" }, { "flag": "trusted" } ] }
{ "any": [ { "flag": "trusted" }, { "var": "lamps_lit", "at_least": 4 } ] }
```

Read `all` as "all of these", `any` as "at least one of these", and `not` as
"the opposite of this". Conditions nest inside each other up to **32 levels
deep** — deeper than anything a person would write, and shallow enough that a
runaway file is told so rather than crashing the game. So "either of these two
roads, but only if you came back" is:

```json
{
  "all": [
    { "any": [ { "has_item": "brass_key" }, { "flag": "trusted" } ] },
    { "visits": { "scene": "hall", "at_least": 2 } }
  ]
}
```

A condition holds **exactly one** operator. To combine two, put them in `all` or
`any` — the game will tell you so if you forget.

### `first_time`, and when it is true

`first_time` is true only on the first visit to the scene being entered. It is
shorthand for `{ "visits": { "scene": "this one", "at_least": 1 } }`, and it
exists because *"the first time you see the room"* is a sentence authors write
constantly and should not have to spell out.

**The order inside a turn is: the visit is counted, then `on_enter` runs, then
the prose is chosen and shown.** So `first_time` is already true while `on_enter`
is running — which is exactly what makes this work:

```json
"on_enter": [
  { "when": { "first_time": true }, "do": [ { "message": ["You have not been here before."] } ] }
]
```

This is worth stating plainly because the opposite choice is just as reasonable
and would be just as invisible: if the counter went up *after* the scene had been
played, `first_time` would be false in the one place it is most useful, and every
author would eventually write it, see nothing happen, and conclude the feature
was broken.

`first_time` is about **the scene you are standing in**, so it stays true for the
whole of that visit — including while the options are on screen. A choice guarded
with `first_time` therefore behaves the way you would expect on a first visit,
and stops being offered once the reader has left and come back.

---

## Actions

An action changes something. Actions appear in `on_enter` and in a choice's
`effects`, and they run in order.

| action | what it does |
|---|---|
| `{ "set": { "mood": "generous" } }` | gives a variable a value |
| `{ "inc": { "lamps_lit": 1 } }` | adds to a number (use `-1` to subtract) |
| `{ "take": "brass_key" }` | puts something in the reader's hands |
| `{ "take": ["brass_key", "oil_can"] }` | …several things |
| `{ "drop": "oil_can" }` | takes something away |
| `{ "goto": "cellar" }` | jumps straight to another scene |
| `{ "message": ["He holds it out."] }` | the world answers. A list of paragraphs like a `body` |

An action holds **exactly one** verb. To do two things, write two actions:

```json
"effects": [
  { "drop": "oil_can" },
  { "set": { "mood": "settled" } },
  { "message": ["The wick catches."] }
]
```

All the messages from one turn are shown together, **after the new scene's prose
and before its options**. If you take a choice whose `effects` produce a message
and whose destination also says something on arrival, both are shown, the
choice's own message first — the world answering what you did, and then the room
you did it in.

### What a message can say

A message is prose, so it is written exactly like a `body`: one line, or an object
naming a register and a pace.

```json
{
  "message": [
    "He holds it out.",
    { "text": "you have waited a long time for this.", "style": "aside" }
  ]
}
```

Everything a `body` accepts, a message accepts — the same four registers, the same
`pace`, the same `*emphasis*`. That matters most for `aside`, which is how the
world says something quietly over the top of what just happened. The game draws it
the way it draws an aside anywhere else, so a message is not a plain-text channel
with a special voice of its own.

### Where a `goto` ends

**The first `goto` that actually runs takes effect and ends the list.** Nothing
after it runs, and if it was nested inside `when`/`do` or a `chance` branch, the
jump ends the *enclosing* list too.

This is what makes the ordinary "go inside if you have the key, otherwise stay
here" idiom work:

```json
"on_enter": [
  { "when": { "has_item": "brass_key" }, "do": [ { "goto": "vestibule" } ] },
  { "goto": "gate" }
]
```

The author means one thing or the other. The first matching jump wins, so the
second one is skipped when the key is held — which is only true because `goto`
stops the list. Reading it as "the last one wins" would make the branch above
dead and send every reader to the gate.

Because a `goto` ends the list, actions written after one can never run. The game
refuses to load them rather than letting them sit there looking meaningful:

```
scenes.hall.on_enter[0]
  -> 2 actions follow an unconditional "goto", which ends the list, so they can never run
  hint: move them into the scene being jumped to, or guard the jump with
        { "when": ..., "do": [ { "goto": ... } ] } so the list carries on when it
        does not fire
```

The number in the pointer is the index of the `goto` itself, so the fix is the line
above it as often as the line below.

A jump that is *guarded* is fine — it only sometimes runs, so what follows it
still has a chance to.

### Doing something only sometimes

```json
{
  "when": { "first_time": true },
  "do": [ { "inc": { "lamps_lit": 1 } } ]
}
```

This is the one wrapper for every "but only if…" you will want, which is why the
language has no separate `on_first_enter` or `on_return` fields.

### Doing something by chance

```json
{
  "chance": {
    "p": 0.4,
    "then": [ { "take": "oil_can" } ],
    "else": [ { "message": ["Only grit behind the stair."] } ]
  }
}
```

`p` is the chance of `then`, between 0 and 1. `else` is optional — leave it out
if nothing happens the rest of the time.

> **Chance is an action, never a condition.** There is no `{ "chance": 0.3 }`
> condition, and there will not be one. A condition gets asked several times in
> the same turn — once to decide what to show, again when the screen redraws — so
> a random one would answer differently each time it was asked. Rolling once, as
> an action, and writing the result into a variable keeps the game predictable
> and replayable from a seed.

---

## Variables

Variables are the facts your story remembers. Declare them at the top of the
file; the game will refuse a story that uses one it has not been told about.

```json
"variables": {
  "lamps_lit":  { "type": "int",  "initial": 4, "label": "lamps lit", "hud": true },
  "trusted":    { "type": "bool", "initial": false },
  "mood":       { "type": "string", "initial": "wary" }
}
```

`type` is `int`, `bool` or `string`. Setting a variable to a value of the wrong
type is an error, not a surprise.

`"hud": true` shows the variable on the status line while the reader plays, named
by its `label`. Use it for **at most one or two** facts — the ones you would
mention out loud. A status line of six numbers turns the story into a dashboard.

---

## Items

```json
"items": {
  "brass_key": {
    "name": "Small Brass Key",
    "description": "Not much longer than your thumb. Worn smooth at the bow, where someone used to hold it every day.",
    "art": "( o )"
  }
}
```

`name` is what the inventory calls it. `art` is optional decoration, drawn exactly
as written. `description` is **what the reader is told when they look** — which
they do by typing `look` and naming the thing:

```
  save · load · look · or a number
  > look brass key

  Small Brass Key
  ( o )

  Not much longer than your thumb. Worn smooth at the bow, where someone used to
  hold it every day.
```

Bare `look` lists what is in the reader's hands, so a player who never guesses the
next word still finds it. `look` followed by words matches any item whose name —
or whose id, with the underscores turned into spaces — *is* what they typed, or
*begins* with it. So the key above answers to `look small`, `look brass`,
`look brass key` and `look brass_key` alike.

It does **not** answer to `look key`. That is deliberate and worth knowing when
you name things: `key` is not how this name begins, and a rule that accepted any
word from anywhere would have no answer for an author holding both a `brass_key`
and an `iron_key` — the reader would type the one word that tells them apart and
the game would have to pick. The rule is *the beginning of the name or the id*,
which is the one rule a reader can predict without being told it.

Asking for something they are not carrying is answered rather than shrugged off —
`"telescope" is not something you are carrying. You have: Small Brass Key.` — and
if their words could mean two things they are carrying, they are asked which one,
rather than shown whichever the program happened to reach first.

### The limit of `look`: items have no place

**An item is only ever in the reader's hands.** Nothing in this format puts an item
*anywhere* — there is no way to write a key lying in a flowerbed, a coat on a hook,
a telescope in a room. Items exist in the inventory and nowhere else, and `look` can
therefore only examine what the reader is carrying.

That is worth knowing before you write a description, because it is the one kind of
prose here the game cannot warn you about as you write it: a `description` on an item
no action ever `take`s is a paragraph nobody can read. It is the same fault as a
scene nothing links to — *written, and never seen* — and `--check` reports both.
Run it after every editing session.

Items only do things through conditions and actions — `has_item`, `take`,
`drop`. There is no damage, no weight and no durability, because this is not that
kind of story.

---

## Endings

```json
"endings": {
  "steady_light": {
    "title": "Steady Light",
    "kind": "warm",
    "epilogue": ["Six lamps. The quay is a sentence again."]
  }
}
```

A scene reaches an ending with `"ending": "steady_light"`. The scene shows its
prose first, then the ending shows its epilogue and stops.

`kind` is `warm`, `bitter`, `ambiguous` or `neutral`, and decides how the ending
is coloured. Two endings to start with is plenty; the ending should land, not
merely arrive.

---

## Checking your story

Editing a file this size, you will eventually write a scene and forget to link it,
or declare an ending no scene ever reaches. Neither is a syntax error. The file
loads, the game plays, and the passage sits there looking exactly like the ones
that work.

`--check` is the tool for that. It reads the story without playing it, and — like
everything else on the writing side — it needs nothing installed:

```
python main.py story/your-story.json --check
```

It prints what the file declares, and then the scene graph: which places lead to
which, and how each one finishes.

```
  scene graph, from "platform":

  → platform       Platform Three
      · Ask for a ticket → ticket_window
      · Get on anyway → carriage
    terminus       The Terminus
      ▸ ends: Arrival (ambiguous)
```

`→` marks where the reader starts. `▸ ends:` marks a scene that finishes the story,
and names the ending. `(shown only sometimes)` and `(can be locked)` mark a choice
carrying a `when` or an `enabled_when`, so you can see at a glance which options
are not always on screen.

### The part that can fail

Then it reports anything **written that no reader will ever see**:

```
  written, and never seen:

    scene "cellar"        nothing links to it, so its prose is never read
    ending "steady_light" no scene ends here, so its epilogue is never read
    item "oil_can"        nothing in the story takes it, so it can never be looked at
    variable "lamps_lit"  nothing reads it and it is not on the status line
```

Those four lines are one fault written four ways, and it is the fault this whole
format is arranged against: prose that is in your file, that you can read, and that
nobody playing the game will ever be shown. The loader already refuses the small
version of it — an action written after a `goto` that always fires, which could
never run — and this is the same refusal one scale up, at the size only a walk over
the whole graph can see.

**If anything is in that list, `--check` reports failure.** A check that finds
something and succeeds anyway is not a check, and the alternative is an author
finding out from a reader who walked into a dead end.

When there is nothing to report it says so:

```
  nothing written here is unseen
```

It says it out loud because silence is indistinguishable from the check never
having run — and running it is the only reason you asked.

**None of this stops the story.** A finding is not an error in your file; the story
still loads and still plays. Only the loader's own complaints — a misspelling, a
scene that is not there — stop anything.

---

## Adding a chapter without touching any code

This is the whole point of the format, so here it is end to end.

Say the story currently ends at a scene called `terminus`. You want a new chapter
in between: the reader gets off the train, meets someone on the platform, and
only then does the story finish.

1. **Add the new scene** under `"scenes"`:

```json
"the_platform": {
  "title": "A Platform With No Name",
  "pace": "slow",
  "body": [
    "The doors open onto cold air and a sign that has been painted over.",
    { "text": "someone is waiting, and has been for a while.", "style": "aside" }
  ],
  "choices": [
    { "text": "Ask where you are", "to": "the_answer" },
    { "text": "Say nothing", "to": "terminus" }
  ]
}
```

2. **Add whatever it needs** — a second scene, a variable, an item — the same
   way, in their own blocks at the top of the file.

3. **Point the old scene at it**: change the choice that used to lead to
   `terminus` so that it leads to `the_platform` instead.

4. **Run it.** If you misspelled `the_platform` anywhere, the game will say so,
   name the line, and suggest the spelling you probably meant. If you spelled it
   right and forgot to point anything at it, `--check` will say *that* — see
   [Checking your story](#checking-your-story) just above.

No Python was edited. Nothing needed to be recompiled, and nobody needed to be
asked. That is the claim this project is making, and this is the procedure that
demonstrates it.

---

## What your edits do to somebody's saved run

Saving is something the player does, and there is nothing to write for it. It is
worth knowing about anyway, because it is the one place where editing your file
has a consequence you cannot see from inside it.

**A save holds the reader, not the story.** It remembers where they are standing,
what they are carrying, what your variables are set to, how many times they have
visited each scene, and the position of the random generator. It does **not**
contain one word of your prose. The words are read out of your story file every
time, so **rewriting a sentence, a title, or a whole epilogue changes it for
everybody** — including someone who saved a run last week.

That is deliberate, and it is the reason a save is not a second copy of your
story. The other way round would mean an author editing `observatory.json` and
finding that the edit takes effect for every reader *except* the ones who saved,
who go on being shown the old paragraphs from a file on disk, with nothing in the
game to say so.

The cost is this table. When someone loads a run and the story has moved on:

| you changed… | what happens | why |
|---|---|---|
| a sentence, a title, an epilogue | **loads normally** | the words come from your file |
| added a variable | it starts at its `initial` | the reader has never seen it |
| deleted a variable | it is dropped | nothing reads it any more |
| deleted a scene from the middle | its visit count and its used-choice records are dropped | nothing the reader can see |
| **renamed the scene someone is standing in** | **load is refused** | they would be put somewhere that is not where they saved |
| **renamed an item someone is carrying** | **load is refused** | what they can do depends on what they hold |

A refusal is not a crash. It explains itself, lists *every* problem at once
rather than one per attempt — an author who fixed one and reloaded only to be
told about the next would be reading the save file by hand to find out what is
wrong with it — and it leaves the run they were in the middle of exactly where
it was:

```
saves/observatory.save
  -> this save is from an earlier version of the story:
  · you are standing in "vestibule", which is not a scene in this story
  · you are carrying "brass_key", which is not an item this story declares
```

So: rewrite prose freely. Rename a scene or an item and you have mildly
inconvenienced the people who saved — which is the honest trade, since the
alternative is silently lying to them.

**Why it is not JSON.** The story is JSON *so that you can write it*. Nobody
writes a save file, so it is written in Python's own binary format, which is
smaller and exact about types. One thing follows from that and is worth saying
plainly: **a save is a local file you made, not a document to trade.** Reading
one runs Python's unpickling, so treat a save someone else sends you the way you
would treat any other program they sent you. The `saves/` folder is excluded from
version control for the same reason.

---

## Vocabulary, in one place

| | allowed values |
|---|---|
| variable `type` | `int`, `bool`, `string` |
| paragraph `style` | `aside`, `letter`, `sign`, `whisper` |
| `pace` | `slow`, `normal`, `fast` |
| ending `kind` | `warm`, `bitter`, `ambiguous`, `neutral` |
| condition operators | `all`, `any`, `not`, `has_item`, `flag`, `var`, `visited`, `visits`, `first_time` |
| action verbs | `set`, `inc`, `take`, `drop`, `goto`, `message`, `when`/`do`, `chance` |

Anything outside these lists is rejected when the story loads, with a message
naming the closest thing that *is* allowed. That strictness is deliberate: a
misspelled `choises` would otherwise be silently ignored, and you would be left
with a scene that quietly does nothing.

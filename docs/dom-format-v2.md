# `.dom` format version 2: the rectangle frame — DRAFT

Status: **decisions taken 2026-10-05** (below). **Stage 1a implemented 2026-10-06**
(`homemaker-py-8b2u.2`, `src/homemaker_layout/dom_v2.py`, DESIGN.md §39.94): the
reader and writer exist, the in-memory tree is still v1 -- see *Stage 1a* at the
end for what that means. Epic: `homemaker-py-8b2u`.
Evidence: DESIGN.md §39.88.

## Why a new version

1. **The rectangle-frame pivot** (§39.88): a building is a slicing tree over an
   orthogonally aligned rectangle enclosing the plot, cropped to the plot before
   scoring. Experiment 1 showed every orthogonal design translates into this
   form EXACTLY (2,577 of 2,577 cells), so v2 changes how cuts are written
   down, not which buildings exist.
2. **A v1 file does not say what it means.** The same v1 file is a different
   building depending on the `HOMEMAKER_ORTHOGONAL_DIVISION` environment
   variable. That is why the objective stamp carries `+orth`, why every scorer
   and diagnostic must be told the switch per file, and how an unattended
   landing tripped on 2026-10-05 (§39.89). A file must carry its own geometry
   convention.
3. **The plot must be allowed to be any polygon.** v1's root is a quad; the
   crop works against any polygon (L-shaped sites, set-backs, several plots).

## Version detection

- A v2 file is a YAML mapping whose FIRST key is `format`:

  ```yaml
  format: homemaker-dom
  version: 2
  ```

- A file without `format` is **v1** (Urb's format, as written by Urb and by
  this repo to date). v1 stays readable forever: 98 of the 218 tracked `.dom`
  files are non-orthogonal and cannot be expressed in v2 (§ Migration).
- A reader that meets a `version` it does not know refuses, naming the
  version. It never guesses.
- `version` is an integer and changes only on a change a v2 reader cannot
  safely ignore. New optional keys do not bump it.

## Structure

```yaml
format: homemaker-dom
version: 2
frame:
  u: [0.99996, 0.00872]      # unit vector of the frame's first axis (v is u rotated +90 deg)
plot:                        # the site polygon, OUTER boundary, any number of vertices, CCW;
                             # collinear vertices allowed and meaningful (see Perimeter)
  - [1.671, 11.917]
  - [8.721, 13.712]
  - [6.796, 21.380]
  - [-0.422, 19.937]
perimeter: [private, null, null, null]   # one entry per plot edge, in plot order
wall_inner: 0.08
wall_outer: 0.25
storeys:
  - elevation: 0.0
    height: 3.0
    tree: { cut: u, at: 0.4909, low: {...}, high: {...} }
  - elevation: 3.0
    height: 3.0
    tree: { ... }
meta:                        # optional, ignored by geometry and scoring
  objective: 59d8aa1+orth
  search: f067db8/4549a418fc
  seed: 0
```

### Perimeter: a status per plot EDGE, not per side

`perimeter` has one entry per plot edge, in plot order. A plot side whose
status changes part-way -- street for its first 6 m, party wall after that --
is written as two edges with a **collinear vertex** between them (owner,
2026-10-05: "we will have plots where the private/street edge will change
even when there is no change in direction"). So:

- collinear plot vertices are legal and must be PRESERVED by every reader,
  writer and geometry routine -- a polygon clean-up that drops collinear
  points (as `diag_8b2u_rect_frame.py`'s `dedupe` does) would erase the
  status change;
- a cell's wall along such a side is partly street and partly party wall;
  geometry splits that wall at the status vertex, so each part carries its own
  status (and the rooms document gives each part its own `face_styles` entry,
  `docs/rooms-format.md`);
- the frame is unaffected: a collinear vertex adds no direction.

### The frame

- `frame.u` is stored, not derived. Today it is derived from the plot's
  longest boundary edge (`geometry._reference_axes`); writing it down makes the
  orientation part of the design, lets a designer override it, and stops a
  plot edit from silently rotating every wall.
- The frame RECTANGLE is the plot's bounding box in (u, v), after the
  `wall_outer` inset. It is derived, not stored: it must always enclose the plot
  exactly, so storing it could only make it wrong.

### Nodes

A node is either a **cut** or a **cell**:

```yaml
{ cut: u, at: 0.4909, low: <node>, high: <node> }   # a full line across the parent rectangle
{ cell: t3 }                                         # a leaf, with its type
{ cell: b1, share: 2 }                               # optional leaf fields as in v1 (share, co_type)
```

- `cut: u` means the line runs ALONG u (it fixes v); `cut: v` runs along v.
- `at` is the line's position as a fraction of the PARENT RECTANGLE's extent
  across the cut, in (0, 1). Not of the cropped cell: positions are in the
  frame, so a cell may crop to nothing.
- `low` is the side nearer the frame's minimum on that axis, `high` the other.
- **v1's `rotation` and two-valued `division` disappear.** In v1 they say which
  pair of a quad's edges a cut joins and where on each; in a rectangle there is
  one answer for each, so they carry no information. This is the main
  simplification v2 buys.

### Storeys

- `storeys` lists every level, lowest first; it replaces v1's nested `above`.
- An upper storey's tree mirrors the storey below by PATH (a node's path is
  its `low`/`high` route from the root). Where the storey below has a cut at a
  path, the upper storey **inherits** it and must not write its own `cut`/`at`
  there -- in v1 those fields were written and silently ignored ("dead
  fields"); v2 makes the rule visible. An upper storey may cut further inside
  an inherited cell, and may leave a path undivided that is divided below
  (the cell then spans what is two cells downstairs).

### Cropping and odd cells

- A cell's shape is its rectangle intersected with the plot polygon (after the
  wall inset). It may be a quad, a triangle, a pentagon or larger, or EMPTY.
- Empty cells are legal and are not rooms: they hold no area and take no part
  in adjacency. A writer may emit them; a reader must accept them.
- Triangles, pentagons and larger polygons are legal. The owner's first ruling
  (2026-10-04) was to score them down; refined 2026-10-05: **vertex count is
  the wrong test** -- "some five sided spaces are actually quads and some are
  awkward pentagons that are only good for garden space" -- so cells get a
  SHAPE SCORE instead. DESIGN.md §39.90 measures the candidate (the usable
  fraction: largest frame-aligned rectangle inside the cell over its area), and
  the owner ruled its parameters the same day: full credit from 0.85, fail
  below 0.70, applied to rooms, circulation and terraces, ground-level gardens
  exempt. That is the objective, not the format; it is recorded here only so
  the format's legal shapes and their cost are read together.

### Reserved for later stages (not in stage 1)

- `blocks:` -- pre-placed rectangles fixed on every storey (the stair shaft as
  a fixed block, §39.88 experiment 4), each `{rect: [u0, u1, v0, v1], type: C}`.
  Reserved so a stage-1 reader can refuse a file that uses it rather than
  mis-reading it.

## Stage 1b: a v2 file scored as itself (2026-10-06, DESIGN.md §39.103)

`dom.load(path, native=True)` -- which is what `homemaker-fitness` does --
builds a NATIVE tree: every divided node keeps the `cut` and `at` the file
gives it, and `geometry` draws the building by splitting the frame rectangle
and cropping each leaf to the plot. Nothing below under *Stage 1a* is refused
on this path: a plot of any number of vertices, L-shaped or not; collinear
status vertices; the file's own `frame.u`; cells that crop to a wedge, a
pentagon or nothing. The orthogonal-division switch is not consulted.

- A cell outside the plot is **void**: it stays in the tree and in the file,
  and is passed over by everything else.
- A plot side is identified as `#k`, the index of the plot edge, so `perimeter`
  in memory is `{"#0": ..., "#1": ...}`.
- **Shape** is scored: a room, corridor or upper-storey terrace whose largest
  fitted rectangle covers under 85% of it loses credit, and under 70% fails
  (`N/path shape`). Ground-level outdoor space is exempt.
- A stair is fitted only to a four-cornered core.
- Every one of the 192 orthogonal designs scores the same as a native tree as
  it does as a quad tree.

A native tree can be scored and written, **not yet searched**: the operators
still edit `rotation` and ratios, so `homemaker-evolve` and every other tool
use the default, `native=False`, described next.

## Stage 1a: what the reader and writer do today

`dom.load` reads either version; `dom.dumps(root, version=2)` writes v2 and
`version=1` stays the default, so `homemaker-evolve` still writes v1. A v2 file
is read into the SAME `Node` tree a v1 file makes -- the reader fits the
`rotation` and ratio under which `geometry` draws each line -- so geometry,
scorer and search are untouched. Over the 192 tracked orthogonal designs: 3,879
of 3,879 cells identical, and a second dump byte-identical.

- **`at` is written to 10 decimal places.** It is recomputed from geometry on
  every write and comes back a few ulps away; rounding is what makes
  load -> dump reproduce the file. 1e-10 of a plot is nanometres.
- **Orthogonal division must be on**, for reading and for writing, and the
  reader says so rather than switching it on: that would change what every v1
  file loaded afterwards means. This goes away with native geometry (`8b2u.4`).
- **Refused until native geometry**, each with a message naming the node: a
  plot that is not a quad; a `frame.u` other than the one derived from the
  longest edge; a cut that misses its cropped cell (an empty cell); and an
  upper-storey cut across a cell whose orientation a storey below has fixed the
  other way. The last is the v1 tree's limit, not the format's: `geometry`
  reads a node's rotation from the lowest storey that has it.
- **Leaf names are not preserved.** The reader puts `low` on the left wherever
  it has the choice, so a design's `l`/`r` paths can differ after a round trip.
  Nothing scored depends on them.

### A leaf's corner numbering is not written, and nothing reads it

v1's `rotation` on a LEAF says only which corner is called 0. The first cut of
this reader carried it for circulation cells as a provisional `origin` key,
because the stair-fit rule was reading it (236 of 576 turns of a `C` leaf moved
a score, §39.94). The owner ruled the same day that a stair is fitted
"whichever way is best, so the flight can start at any corner and may run
clockwise or counter clockwise"; the scorer was changed to do that (§39.95),
turning a leaf now moves no score, and the key was removed before it was ever
merged. Decision 3 stands as written.

### What v2 does not carry, and the scorer reads anyway

An upper-storey node whose cut is inherited still stores a ratio of its own in
v1 ("dead fields"). v2 does not write it. It is not quite dead:
`dom.merge_divided` can undivide the node below, and the upper node then cuts
at its own stale ratio. 180 of the 192 designs carry such ratios and 3 are
scored through one (§39.94, `homemaker-py-3tzk`). After a round trip the
upper cut stays where the lower one was.

## Migration

| tracked `.dom` files | count | v2 |
|---|---|---|
| `+orth` coldstart corpora and the e4r A/B artefacts | 120 | convert EXACTLY (§39.88 experiment 1) |
| non-orthogonal corpora, Perl-era examples, test oracle | 98 | **stay v1** -- they have skew cuts a rectangle frame cannot express |

- **Committed artefacts are records and are NOT rewritten.** Each row of a
  results table names the file and the objective that scored it; rewriting
  the file would change what the row points at. The v1 reader stays, and new
  output is written as v2.
- A v1 file's convention is not in the file. The converter takes it from an
  explicit argument (`--orthogonal`), defaulting from the `+orth` stamp in the
  filename where there is one, and refuses otherwise.
- *(implemented 2026-10-06, `dom_upgrade_cmd.py`; output is `<name>.v2.dom`
  beside the input, never the input itself)*
- `homemaker-dom-upgrade FILE...` converts v1 (orthogonal) to v2 and VERIFIES
  every converted file by rebuilding its cells and comparing them with the v1
  geometry, as experiment 1 does; it writes nothing for a file that does not
  verify.
- A v2 -> v1 export exists only for designs v1 can express (no empty or
  non-quad cells), so Urb's Perl tools stay usable on converted designs.

## Downstream tooling

- **`urb-dom2molior.pl`** (1,285 lines of Perl: plot, walls, floors, stairs,
  doors as Molior YAML) reads v1 only. Two options -- see Decisions.
- **homemaker-addon** builds IFC from a TAGGED CELL COMPLEX:
  `Molior.from_faces_and_widgets()` takes Topologic faces carrying a `style`
  and widget vertices carrying a `usage`. `dxf2ifc.py` and `brep2ifc.py` carry
  geometry only, but its **web editor's rooms document** (`rooms.json`: a
  convex plan polygon, elevation, height, per-face styles and a usage per
  room) carries exactly what a slicing-tree cell needs -- so that is what this
  repo writes (`docs/rooms-format.md`). *(Corrected 2026-10-05: an earlier
  draft said no file format carried a tagged cell complex; the web document
  does.)*

## Decisions (owner, 2026-10-05)

All six as recommended, and on (5)/(6): "don't port dom2molior.pl, let's
target homemaker-addon directly ... best to create a dedicated file format,
this will make debugging easier." That format is `docs/rooms-format.md`.
The list below is kept as the record of what was decided.


1. **Header** -- `format: homemaker-dom` / `version: 2` as the first keys, and
   "no `format` key" meaning v1. *Recommended.*
2. **Frame stored in the file** (`frame.u`) rather than derived from the
   longest edge. *Recommended*: orientation becomes a design property, and an
   edited plot cannot silently rotate the building.
3. **Drop `rotation` and the two-valued `division`** in favour of
   `cut`/`at`/`low`/`high`. *Recommended*: they carry no information in a
   rectangle.
4. **Leave committed artefacts as v1** and write v2 going forward.
   *Recommended*: they are records.
5. **`dom2molior.pl`**: (a) port it to Python now, reading v2; or (b) skip the
   port and go straight to a cell-complex export for homemaker-addon, keeping
   the Perl tool for v1 files (and v2 via the v1 export) in the meantime.
   *Leaning (b)* if nothing else consumes Molior output soon -- the owner
   knows.
6. **The interchange to homemaker-addon** for (5b): a small JSON/YAML
   "tagged cell complex" (faces as vertex loops with a `style`; widgets as
   points with a `usage`) plus a reader beside `dxf2ifc.py`, rather than
   making Topologic a dependency of the optimiser. *Recommended*: the two
   repos stay decoupled and the file is inspectable.

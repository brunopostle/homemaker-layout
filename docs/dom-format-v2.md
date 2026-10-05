# `.dom` format version 2: the rectangle frame — DRAFT

Status: **draft for the owner's review** (2026-10-05). Nothing here is
implemented. Epic: `homemaker-py-8b2u`. Evidence: DESIGN.md §39.88.

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
plot:                        # the site polygon, OUTER boundary, any number of vertices, CCW
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
- Triangles, pentagons and larger polygons are legal and are **scored down so
  the optimiser avoids them** (owner's ruling, 2026-10-04). The size of that
  penalty is an objective decision for when the scorer accepts v2 natively,
  not part of the format.

### Reserved for later stages (not in stage 1)

- `blocks:` -- pre-placed rectangles fixed on every storey (the stair shaft as
  a fixed block, §39.88 experiment 4), each `{rect: [u0, u1, v0, v1], type: C}`.
  Reserved so a stage-1 reader can refuse a file that uses it rather than
  mis-reading it.

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
  and widget vertices carrying a `usage`. Its file entry points (`dxf2ifc.py`,
  `brep2ifc.py`) carry geometry only, no styles or usages; the Blender add-on
  gets those from material names and widget objects. So **no file format
  carries a tagged cell complex into homemaker-addon today.** A v2 slicing tree
  maps onto one directly: every cell on every storey is a prism; its walls,
  floor and ceiling are faces (styled by what is on either side); its centroid
  is a widget carrying the cell's `usage` from `patterns.config`.

## Decisions for the owner

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

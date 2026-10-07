# The rooms document: this repo's interchange with homemaker-addon — DRAFT

Status: **implemented** -- `homemaker-rooms` (`src/homemaker_layout/rooms_export.py`),
verified end to end through homemaker-addon on 2026-10-05. Bead: `homemaker-py-8b2u.5`.

How this repo hands an evolved layout to **homemaker-addon** to build an IFC
building, replacing Urb's `urb-dom2molior.pl` (owner's decision, 2026-10-05:
do not port it; target homemaker-addon directly through a dedicated file
format, because that makes debugging easier).

## Not a new format: the web editor's rooms document

homemaker-addon's web interface already defines a cell encoding -- the
"cuboid editor format" its editor saves as `rooms.json`, loads with its
**Load** button, autosaves, and POSTs to `/api/generate`
(`web/README.md`; `web/geometry_adapter.py`). It is exactly the shape of a
slicing-tree cell: a convex plan polygon, an elevation and height, a style per
face, and a usage. So this repo writes **that document**, with a header and a
few extra keys for tracing. Owner's prompt, 2026-10-05: "See also the
cellcomplex encoding used by the homemaker addon web interface, there should
be some shared concepts."

What that buys:

- **The same file opens in the web editor.** An evolved layout can be loaded,
  inspected, edited and regenerated in the browser -- the debugging the owner
  asked for, without writing a viewer.
- **The addon-side reader already exists.**
  `geometry_adapter.rooms_to_faces_and_widgets()` turns rooms into the faces
  (with `stylename`) and widgets (with `usage`) that
  `Molior.from_faces_and_widgets()` takes. A CLI beside `dxf2ifc.py` is a few
  lines.
- One cell encoding in the ecosystem, not two.

## The file

JSON (what the web editor reads and writes), named `<design>.rooms.json`:

```json
{
  "format": "homemaker-rooms",
  "version": 1,
  "name": "programme-house coldstart-59d8aa1+orth-500000-s0",
  "meta": {
    "source": "examples/programme-house/coldstart-59d8aa1+orth-500000-s0.dom",
    "programme": "programme-house",
    "objective": "59d8aa1+orth"
  },
  "rooms": [
    {
      "vertices": [[3.10, 15.20], [5.20, 15.70], [4.90, 17.40], [2.90, 16.90]],
      "elevation": 0.0,
      "height": 3.0,
      "stylename": "default",
      "face_styles": ["default", "default", "blank", "default", "default", "default"],
      "usage": "bedroom",
      "dom_id": "0/lrl",
      "code": "b1"
    }
  ]
}
```

Field by field, with the web document's own meaning:

| key | meaning |
|---|---|
| `vertices` | plan polygon, CCW, metres. The web document calls these `[x, z]` in Three.js's y-up plane; they map to IFC/world `[x, y]` unchanged, so this repo writes its own plan coordinates as they are. 3-64 vertices, **convex** (the web server rejects non-convex rooms) |
| `elevation`, `height` | the cell's floor level and height on its storey |
| `face_styles` | index 0 floor, 1 ceiling, 2.. walls in vertex order (wall `i` runs vertex `i` -> `i+1`); a missing or null entry falls back to `stylename` |
| `usage` | homemaker-addon room type, after the mapping below |
| `dom_id` | **extra:** storey and `.dom` id path of the cell that made this room |
| `code` | **extra:** the programme room code, or `C` / `O` / `S` |
| `roofed` | **extra:** true for a room of the top storey, which a pitched roof goes over |
| `format`, `version`, `meta` | **extra:** header and provenance |

The extra keys are ignored by both consumers -- the server's request models
take only the fields they declare, and the editor's loader builds each room
from the documented fields -- so the file stays loadable. (An editor re-save
drops them; the editor is for looking and tweaking, the `.dom` stays the
record.)

## Coordinates: the frame, not the world

Rooms are written in the layout's **frame** -- `u` along x, `v` along y, the
orthogonal axes every cut follows -- not in world coordinates, and
`meta.frame` records the rotation back:

```json
"frame": {"u": [0.2525, -0.9676], "angle_degrees": -75.38}
```

(world = the frame rotated by `angle_degrees` about the origin.)

This is not cosmetic. homemaker-addon snaps every vertex to 1 mm
(`geometry_adapter._snap`). A slicing tree is full of T-junctions -- a corner
of one room lying part-way along another's wall -- and on a plot skew to the
world axes, snapping knocks that corner a hair off the wall. Topologic then
makes a sliver cell of the gap and `ApplyDictionary` stalls on it: programme-house
s0 at 75 deg gave 12 cells from 11 rooms and a build that had not finished after
15 minutes. In the frame, every wall that is not on the plot boundary is
exactly axial, so snapping cannot move a point off one: 11 cells, built in 7 s.
It also shows the rooms square to the screen in the web editor.

Placing the building back at its true orientation is a site-placement step
(the IFC site's rotation), not a change to the rooms.

## How a layout becomes rooms

- **One room per cell that has a volume**, on every storey, with as many
  corners as the cell has: four in a v1 design, three or more where a v2
  design's plot crops a cell (a v2 file is read as the native tree it
  describes). Every cell is a rectangle cropped by the plot, so on a convex
  plot the convexity rule always holds; a cell wrapped round the inner corner
  of an L-shaped plot is refused. A cell wholly off the plot is not written.
- **Party walls** get style `blank`: a plot-boundary edge whose `perimeter`
  entry is `private`, which is Urb's `IsParty` (`lib/Urb/Dom.pm`) as used by
  `urb-dom2obj.pl`. (`blank` is a real style directory in `share/`; the web
  README's example uses `party`, which is not -- worth correcting there.)
  Everything else is `default`.
- **A wall that is partly street and partly party wall** -- possible once a
  plot side can change status part-way (`docs/dom-format-v2.md`, Perimeter) --
  is split by a **collinear vertex** inserted in the room polygon at the
  change point, so each part gets its own `face_styles` entry. The web server
  accepts this: its convexity check skips collinear vertices
  (`_is_convex_2d`). **Verified 2026-10-05** (`experiments/check_rooms_split_wall.py`): the
  cell complex keeps the two coplanar parts as separate faces with their own
  styles, and the IFC follows -- a south wall that is party for 2 m and street
  for 2 m gets a window on the street part only (all-street: two windows,
  all-party: none).
- **Uncovered outdoor cells are omitted**, as `urb-dom2obj.pl` omitted them: a
  terrace is the roof of the cell below, not a room. Covered outdoor cells are
  written with usage `outside`.
- **Outdoor siblings are fused, rooms never are** -- exactly
  `dom.merge_divided`, which the scorer applies first and which fuses only
  adjacent `O`/`S` pairs. The scorer counts room instances per leaf, so two
  adjacent leaves of one room code are two rooms to it, and two rooms here.
- Faces two rooms share are written by both; `CellComplex.ByFaces` merges
  them, and the web README documents which style wins.
- Prior art: `urb-dom2obj.pl` (2022, homemaker-addon issue #39) did the same
  through OBJ -- materials as styles, object names as usages, y-up. This
  replaces it.

## Pitched roofs: `faces` and `widgets`

A room is a prism, so it cannot say that a roof slopes. homemaker-addon reads
two more lists from the same document (`molior.rooms.document_to_faces_and_widgets`,
its `web/README.md`): `faces`, each `{"vertices": [[x, y, z], ...], "stylename":
...}` with three or more corners, and `widgets`, each `{"position": [x, y, z],
"usage": ...}`. A roof is then a CELL: closed below by the ceilings of the
rooms under it, which are already in the document, and above by sloping
faces. `homemaker-rooms` writes those faces (`src/homemaker_layout/roofs.py`,
DESIGN.md §39.119; bead `homemaker-py-6e5u`), replacing the pitched roofs
Urb's `urb-dom2molior.pl` made as solids.

- **What is roofed**: the rooms of the top storey, marked `"roofed": true`
  (an extra key, like `dom_id`). Rooms that share a wall are under one roof;
  separate groups get separate roofs. A room lower down with open air over it
  carries a terrace, which stays flat.
- **The shape**: the straight-skeleton roof of each group's outline -- every
  outline edge is an eave at the top storey's ceiling, every slope at one
  pitch (`--roof-pitch`, default 35 degrees), meeting in hips, valleys and
  ridges. A courtyard in the top storey is a hole in the outline and gets
  eaves of its own.
- **Gables**: where a roof ENDS at a party wall (`blank`) -- its face there
  would be a triangular hip end -- the ridge is carried on to the wall and
  the end is closed by a vertical face, as Urb gabled party boundaries. A
  party wall running ALONG a roof keeps its slope; `meta.roof.notes` says how
  many did. `--no-gables` hips everything.
- **A `void` widget** inside each roof, so the roof space is not allocated as
  a room (`AllocateCells` would default it to `living`).
- `--flat-roofs` writes none of this, and the addon roofs every top cell flat
  as it did before.

Three things the addon requires of this geometry, each found by building a
real design and each now held by `tests/test_roofs.py`:

- **A face must be flat to about a micron** (measured: 1e-6 builds, 1e-5 is
  "the wire was not planar"). Each corner's height is therefore taken from
  its own face's plane, not shared between the faces that meet there.
- **Nothing may be smaller than the 0.1 mm it merges at.** Room corners are
  written to 1e-7 m for this: at 1e-4, three rooms' corners along one skew
  plot side are no longer in a line, the roof gets a plane per kink a
  hundredth of a degree apart, and `CellComplex.ByFaces` fails.
- **Neighbours must list the same corners along a shared edge**, so a corner
  of one face that falls part-way along another's edge is inserted there.

Verified through `rooms2ifc.py` (2026-10-07), flat against pitched:

| design | rooms | spaces | IfcRoof | IfcWall | windows / doors |
|---|---|---|---|---|---|
| programme-house `1a24b6a+orth` s0, flat | 11 | 11 | 7 | 51 | 18 / 13 |
| ...pitched | 11 | 12 (one `void`: the roof) | 10 | 39 | 18 / 13 |
| harbor-house `1a24b6a+orth` s0, flat | 48 | 48 | 28 | 202 | 93 / 59 |
| ...pitched | 48 | 49 | 23 | 165 | 93 / 59 |

The walls that go are presumably the parapets of the flat roofs; that was
counted, not inspected.

## Usage mapping

homemaker-addon room types (`ROOM_TYPES` in `__init__.py`, `_VALID_USAGES`
in `web/server.py`, the usage characters in `web/static/src/fragment.js`):
`bedroom circulation circulation_stair stair kitchen living outside retail
sahn toilet void`.

| this repo | usage | note |
|---|---|---|
| `bedroom`, `kitchen`, `living`, `toilet` | the same | identical names |
| `none` (6 rooms) | `void` | owner, 2026-10-05: the addon's `void` is its usage for useless spaces |
| `utility` (18 rooms) | `utility` | **new in homemaker-addon** (owner, 2026-10-05) |
| `C` forming an intact stair shaft (§39.72) | `stair` | the column the scorer counts as a staircase. **Not** `circulation_stair`: every stair behaviour in the addon tests `usage == "stair"`, and `circulation_stair` only appears in its widget-name list (it made a `void` space) |
| `C` otherwise | `circulation` | |
| `O`, covered | `outside` | uncovered `O` is omitted |
| `S` | `sahn` | |

The writer refuses a usage the mapping does not cover, rather than letting
`AllocateCells` default it to `living` unnoticed.

## Reader (homemaker-addon)

`rooms2ifc.py` beside `dxf2ifc.py`: load the document, call
`rooms_to_faces_and_widgets()`, then `Molior.from_faces_and_widgets()`.
`rooms_to_faces_and_widgets` lives in `web/geometry_adapter.py` today; moving
it into the library (beside `molior`) would let the web server and the CLI
share one copy.

## Verified end to end (2026-10-05)

programme-house `coldstart-1a24b6a+orth-500000-s0`: 11 rooms -> 11 IfcSpaces
with the right usages (2 stair, 2 circulation, 2 bedroom, 1 living, 3 toilet,
1 outside), 51 walls, 18 windows, 13 doors, 7 roofs, 3 storeys, in 6 s.

**No IfcStair is produced -- by any input.** homemaker-addon's `Stair` class
is a stub (`molior/stair.py`: `execute()` is `pass`, "entire stair drawing
module still needs porting from Perl Molior library"; `share/traces.yml`:
"FIXME stairs are not implemented yet"). The shaft arrives correctly as
`stair` cells and `molior/floor.py` already leaves the stairwell open between
them; the flights appear when the addon's stair module is ported. Urb's
`urb-dom2molior.pl` route DID draw stairs, so this is the one thing the
decision not to port it gives up for now.

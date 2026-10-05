# The rooms document: this repo's interchange with homemaker-addon — DRAFT

Status: **draft** (2026-10-05). Bead: `homemaker-py-8b2u.5`.

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
| `format`, `version`, `meta` | **extra:** header and provenance |

The extra keys are ignored by both consumers -- the server's request models
take only the fields they declare, and the editor's loader builds each room
from the documented fields -- so the file stays loadable. (An editor re-save
drops them; the editor is for looking and tweaking, the `.dom` stays the
record.)

## How a layout becomes rooms

- **One room per cell that has a volume**, on every storey. Every cell the
  slicing tree produces is convex -- a rectangle cropped by a convex plot, in
  v1 and v2 alike -- so the convexity rule always holds.
- **Party walls** get style `blank`: a plot-boundary edge whose `perimeter`
  entry is `private`, which is Urb's `IsParty` (`lib/Urb/Dom.pm`) as used by
  `urb-dom2obj.pl`. (`blank` is a real style directory in `share/`; the web
  README's example uses `party`, which is not -- worth correcting there.)
  Everything else is `default`.
- **Uncovered outdoor cells are omitted**, as `urb-dom2obj.pl` omitted them: a
  terrace is the roof of the cell below, not a room. Covered outdoor cells are
  written with usage `outside`.
- Faces two rooms share are written by both; `CellComplex.ByFaces` merges
  them, and the web README documents which style wins.
- Prior art: `urb-dom2obj.pl` (2022, homemaker-addon issue #39) did the same
  through OBJ -- materials as styles, object names as usages, y-up. This
  replaces it.

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
| `C` forming an intact stair shaft (§39.72) | `circulation_stair` | the column the scorer counts as a staircase |
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

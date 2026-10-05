# `.cellcomplex` interchange format, version 1 — DRAFT

Status: **draft** (2026-10-05). Bead: `homemaker-py-8b2u.5`.

The file this repo writes so that **homemaker-addon** can build an IFC building
from an evolved layout, replacing Urb's `urb-dom2molior.pl` (owner's decision,
2026-10-05: do not port it; target homemaker-addon directly, through a
dedicated file format, because that makes debugging easier).

## What homemaker-addon needs

`molior.Molior.from_faces_and_widgets(faces, widgets)` builds the cell
complex, circulation graph and IFC from:

- **faces** -- Topologic faces, each with a `stylename` (in Blender this comes
  from the face's material name; `default` when there is none);
- **widgets** -- points carrying a `usage`. `topologist.cellcomplex.
  AllocateCells` gives each cell the usage of the widget inside it, and
  `living` when there is none (`void` when the cell has no closed perimeter).

Nothing on disk carries both today: `dxf2ifc.py` and `brep2ifc.py` read
geometry only, and Urb's `urb-dom2obj.pl` (2022, homemaker-addon issue #39)
encodes styles as OBJ material names and usages as OBJ object names, which
only the Blender add-on interprets. This format carries them explicitly.

## The file

```yaml
format: homemaker-cellcomplex
version: 1
meta:
  source: examples/programme-house/coldstart-59d8aa1+orth-500000-s0.dom
  programme: programme-house
  objective: 59d8aa1+orth
units: m                       # z up, world coordinates, as the .dom plot
cells:
  - id: 0/lrl                  # storey / .dom id path: traces back to the cell that made it
    code: b1                   # the programme room code (or C / O / S)
    usage: bedroom             # the homemaker-addon usage, after the mapping below
    widget: [4.12, 16.30, 1.50]          # inside the cell: centroid at mid-height
    floor: 0.0
    ceiling: 3.0
    outline: [[3.1, 15.2], [5.2, 15.7], [4.9, 17.4], [2.9, 16.9]]   # plan polygon, CCW
    walls: [default, blank, default, default]                        # one style per outline edge
  - ...
```

- **One entry per cell** that has a volume, on every storey, keyed by its
  `.dom` id path. A face in the IFC can be traced to the cell, storey and
  `.dom` node that produced it -- the point of a dedicated format.
- **Geometry is a prism** per cell: the plan `outline` extruded from `floor`
  to `ceiling`. The reader makes the floor, ceiling and one vertical face per
  outline edge. Faces two cells share are written by both;
  `CellComplex.ByFaces` merges coincident faces, exactly as it does for the
  OBJ path today.
- `outline` is a polygon, not a quad, so v2's cropped cells (triangles,
  pentagons) need nothing new here.
- **`walls`** gives each vertical face a style, in outline-edge order:
  `blank` for a party wall -- a plot-boundary edge whose `perimeter` entry is
  `private`, exactly Urb's `IsParty` (`lib/Urb/Dom.pm`), which `urb-dom2obj.pl`
  uses -- and `default` otherwise. Floor and ceiling
  faces are `default`. Further styles are additive and do not bump the version.
- **Uncovered outdoor cells are omitted**, as `urb-dom2obj.pl` omits them: a
  terrace is the roof of the cell below, not a cell. Covered outdoor cells are
  written, with usage `outside`.
- Coordinates are **z-up world metres**. `urb-dom2obj.pl` wrote y-up for OBJ
  (`x, elevation, -y`); this file does not, because the reader builds Topologic
  geometry directly with no Blender import in between.

## Usage mapping (needs the owner)

homemaker-addon's room types: `bedroom circulation circulation_stair stair
kitchen living outside retail sahn toilet void`. This repo's `usage:` classes
(`patterns.config`): `bedroom kitchen living toilet utility none`, plus the
generic cells `C`, `O`, `S`.

| this repo | proposed usage | note |
|---|---|---|
| `bedroom`, `kitchen`, `living`, `toilet` | the same | identical names |
| `utility` (18 rooms) | **?** | no counterpart; unmapped it silently becomes `living` |
| `none` (6 rooms) | **?** | no counterpart; unmapped it silently becomes `living` |
| `C`, an intact stair shaft (§39.72) | `circulation_stair` | the column the scorer counts as a staircase |
| `C`, otherwise | `circulation` | |
| `O`, covered | `outside` | uncovered `O` is omitted (above) |
| `S` | `sahn` | |

The writer refuses a usage the mapping does not cover, rather than letting
`AllocateCells` default it to `living` without anyone noticing.

## Reader

A small script in homemaker-addon beside `dxf2ifc.py` -- proposed name
`cellcomplex2ifc.py` -- that reads this file, makes a Topologic face per
floor, ceiling and wall (with `stylename`), a widget vertex per cell (with
`usage`), and calls `Molior.from_faces_and_widgets`. Being file-based, it keeps
Topologic out of this repo's dependencies, and a failing build can be
reproduced from the file alone.

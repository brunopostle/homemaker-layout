# Harbor House — a brief for a design drawn by hand

Every design in this repository but one was evolved. To know what the scorer
makes of a plan an architect would draw, someone has to draw one. This is the
brief for doing that on Harbor House, and the round trip that scores it.

The twelve evolved designs for this programme carry **24 to 37 fails** each as
scored today. A hand design that composes at all is useful; one with fewer
fails than that says the search is missing something a person finds easily,
and one with more says where the objective disagrees with a designer.

## The round trip

```bash
python experiments/hand_design.py            # compose hand.svg, score it, say why
python experiments/hand_design.py --tune 4000   # then let the walls slide a little
```

Open **`examples/harbor-house/hand.svg`** in Inkscape, draw, save, run the
first command, read the table, draw again. Each run takes a second or two.
`--tune` gives the wall positions a few thousand evaluations of the same
optimiser every evolved design gets, so that a wall 20 cm out is not what the
comparison measures; the layout stays exactly as you drew it.

The starter drawing is already a design that composes: a 2.6 m band up the
middle with a stair core at each end and a corridor between them, on both
floors, and everything either side left as outdoor space. Carve the rooms out
of that, move the band, or delete the lot and start from the plot outline.
`python experiments/hand_design.py --template --force` puts the starter back.

## How to draw

- **Units are metres**, in the plot's own coordinates. The plot is on a locked
  grey layer for reference and is not read.
- **One layer per storey**, named `storey-0` (ground) and `storey-1`. The
  first-floor layer starts hidden; show it in the Layers panel.
- **A wall is a straight line. A room is a text label.** Never draw a room's
  outline: a cell is whatever the walls leave, and it takes the label whose
  anchor point lies inside it. Every cell needs exactly one label.
- **Every wall runs from one side of its region to the other** — a guillotine
  cut. The first wall crosses the whole plot; the next crosses one of the two
  pieces; and so on. A wall that stops in the middle of a space, or four rooms
  meeting pinwheel-fashion round a point, cannot be represented. Ends may fall
  15 cm short or long; they are snapped.
- **Walls run parallel or square to side d**, the long street side: in this
  drawing, horizontal and vertical. Hold Ctrl while drawing.
- **The first floor inherits the ground floor's walls.** Wherever the ground
  floor divides a region, the first floor must divide that region the same
  way, with the wall in the same place — or not divide it at all (one big cell
  over two small ones). Inside a region the ground floor leaves whole, the
  first floor may add walls of its own. What it may not do is cut a region
  the other way from the floor below. Draw the ground floor's main divisions
  first, copy them to `storey-1`, and subdivide each floor from there.
- The drawing is the plan mirrored top to bottom (SVG's y axis points down).
  It changes nothing about the score.

Labels: a room code from the schedule below, **`C`** for circulation
(corridor, hall, landing), **`E`** for a stair, **`O`** for outdoor space (garden, courtyard,
terrace). Rooms that come in numbers — `n`, `t`, `m`, `of`, `r` — are labelled
with the same code each time.

## The site

A plot of about 720 m², 25 m × 31 m, slightly out of square.

| side | in the drawing | what it is | length |
|---|---|---|---|
| a | top edge, sloping | **party wall**: no windows, no door | 25.1 m |
| b | right edge, leaning | **party wall**: no windows, no door | 29.1 m |
| c | bottom edge | street / open | 23.0 m |
| d | left edge | street / open | 31.0 m |

(The table gives the sides as you see them in Inkscape, which is the plan
flipped; the grey labels on the drawing say which is which.)

A wall on a party side gives a room no daylight. A wall on a street side does,
and so does a wall onto an open outdoor cell.

## The schedule of rooms

Two storeys (a third is allowed). 820 m² of rooms in all: 332 m² that must be
on the ground floor, 152 m² that must be on the first, and 336 m² — the five
neighbourhoods and six bathrooms — that may go on either.

"Passes" is the range of areas the scorer accepts; outside it the room fails
on `size`. "Long : short" is the most elongated the room may be.

| code | room | how many | storey | aim m² | passes m² | long : short ≤ | must share a door's width of wall with | needs daylight |
|---|---|---|---|---|---|---|---|---|
| `cr1` | Common room with fireplace | 1 | ground | 80 | 59–101 | 3.1 | circulation, outdoor space | yes |
| `da1` | Dining area | 1 | ground | 60 | 43–77 | 4.2 | circulation, `k1`, outdoor space | yes |
| `k1` | Kitchen | 1 | ground | 30 | 19–41 | 2.6 | `da1`, circulation | yes |
| `ws1` | Workshop | 1 | ground | 40 | 27–53 | 2.9 | circulation, outdoor space | yes |
| `m` | Meeting room | 3 | ground | 10 | 6–14 | 2.6 | circulation | yes |
| `of` | Staff office | 2 | ground | 12.5 | 7–18 | 2.6 | circulation | yes |
| `la1` | Laundry | 1 | ground | 20 | 11–29 | 2.6 | circulation | yes |
| `st1` | Ground-floor store | 1 | ground | 22 | 13–31 | 2.6 | circulation | no |
| `me1` | Plant room | 1 | ground | 25 | 16–34 | 2.6 | circulation | no |
| `n` | Neighbourhood (a cluster of sleeping space) | 5 | either | 60 | 43–77 | 3.3 | circulation | yes |
| `t` | Bathroom | 6 | either | 6 | 3–9 | 2.6 | circulation, and a neighbourhood `n` | yes |
| `li1` | Library corner | 1 | first | 20 | 11–29 | 2.6 | circulation | yes |
| `r` | Individual room | 10 | first | 10 | 6–14 | 2.6 | circulation | yes |
| `st2` | First-floor store | 1 | first | 18 | 10–26 | 2.6 | circulation | no |
| `ut1` | Utilities closet | 1 | first | 14 | 8–20 | 2.6 | circulation | no |

A door's width is 1.2 m: two cells that share less wall than that are not
neighbours. Rooms have no minimum width of their own, only the proportion.

## The rules that cost the most

Each fail halves the score, so a handful of these outweigh every nicety.

1. **Two staircases, exactly.** A stair is a cell labelled **`E`** that is
   *the same cell on each floor it climbs* -- same walls, same place -- from
   the ground up. It may stop below the top floor. It needs a real run: about
   2.6 m x 3.5 m or more; a 2.7 m square is too small. An `E` cell is
   circulation too: rooms may open off it and corridors join it, and two wings
   upstairs that each have their own stair count as one connected building.
   A corridor (`C`) may sit in the same place on every floor; that does not
   make it a stair.
2. **Every room opens off circulation**, and each floor's circulation is one
   connected piece. Circulation narrower than about
   2.0 m fails; 2.4 m is the aim. A bedroom-type room (`n`, `r`, `of`) is a
   dead end: nothing is reached through it.
3. **Every room that needs daylight needs an outside wall** — onto a street
   side, or onto an outdoor cell with nothing built over it. This is the rule
   the evolved designs fail most (half their fails): a deep plan buries rooms.
   Courtyards are how a 720 m² plate gets light to its middle.
4. **Every storey needs usable outdoor space.** On the ground, a garden or
   courtyard. On the first floor, a terrace — and a terrace is only a terrace
   if it sits **over indoor space** and has nothing indoors above it. An `O`
   upstairs that is over a ground-floor `O` is air (a void over a courtyard):
   it lets light down, and counts as nothing else. Outdoor cells narrower than
   about 2.2 m fail; 2.3 m is the aim.
5. **The way in.** There is no entrance-foyer room in the schedule: the
   foyer is circulation with a door to the street. So the ground floor needs
   a `C` cell on side c or d (label your lobby `C`) -- or an outdoor cell on
   a street side with circulation, a living room or the kitchen opening onto
   it. A stair (`E`) on the street is not by itself the way in.
6. **Don't overbuild.** Indoor area, corridors included, starts to lose score
   above 1.2 × the schedule (about 985 m²) and fails well beyond it. It is
   the one rule that says generous circulation is waste. With two floors of
   720 m² there is 440 m² or more to give to courtyards, terraces and voids —
   and rule 3 wants it.

## What the checker tells you

A line per cell: what it is, its area against what was wanted, its width and
proportion, and what it fails on. Then what is still to place, the indoor
total against the cap, the score and the fails that belong to the building
and not to a cell. If the drawing does not compose it says which region is
at fault and why, and stops there.

`hand.dom` is the composed design; `homemaker-fitness`, `homemaker-rooms` and
the IFC route all read it like any other.

When you have one you are content with, say so: the comparison worth making
is the hand design and the evolved ones under the same tuning, and what each
fails that the other does not (`experiments/build_hand_3storey.py --baseline`
is how that was done for the house).

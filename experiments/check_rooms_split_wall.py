"""Does a wall that is partly party wall and partly street survive into the IFC?

docs/rooms-format.md splits such a wall with a collinear vertex and gives each
part its own face style. This builds that room through homemaker-addon and
checks the windows: the street part gets one, the party (`blank`) part none.
Verified 2026-10-05 (DESIGN.md §39.91):

    south wall all street               windows at x = 0.54, 2.54
    south wall all party                none
    party 0-2 m, street 2-4 m           x = 2.54 only

Needs a homemaker-addon checkout (HOMEMAKER_ADDON, default ~/src/homemaker-addon).

    python experiments/check_rooms_split_wall.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ADDON = Path(os.environ.get("HOMEMAKER_ADDON", Path.home() / "src" / "homemaker-addon"))


def south_windows(face_styles) -> list:
    from geometry_adapter import rooms_to_faces_and_widgets
    from molior import Molior
    import ifcopenshell.util.placement as placement

    room = {"vertices": [[0, 0], [2, 0], [4, 0], [4, 3], [0, 3]], "elevation": 0.0,
            "height": 3.0, "stylename": "default", "face_styles": face_styles,
            "usage": "living"}
    faces, widgets = rooms_to_faces_and_widgets([room])
    m = Molior.from_faces_and_widgets(faces=faces, widgets=widgets, name="split",
                                      share_dir=str(ADDON / "share"))
    m.execute()
    xy = [placement.get_local_placement(w.ObjectPlacement)[:2, 3]
          for w in m.file.by_type("IfcWindow")]
    return sorted(round(float(x), 2) for x, y in xy if abs(y) < 0.5)   # on the y=0 wall


def main() -> int:
    if not (ADDON / "molior").is_dir():
        print(f"homemaker-addon not found at {ADDON}; set HOMEMAKER_ADDON. Skipped.")
        return 0
    sys.path[:0] = [str(ADDON), str(ADDON / "web")]
    d = ["default", "default"]
    cases = {
        "all street": (d + ["default"] * 5, lambda w: len(w) == 2),
        "all party": (d + ["blank", "blank"] + ["default"] * 3, lambda w: w == []),
        "party 0-2 m, street 2-4 m": (d + ["blank"] + ["default"] * 4,
                                      lambda w: w and all(x > 2.0 for x in w)),
    }
    ok = True
    for name, (styles, good) in cases.items():
        w = south_windows(styles)
        ok &= bool(good(w))
        print(f"  {name:28} south windows at {w}  {'ok' if good(w) else 'WRONG'}")
    print("split wall: " + ("each part keeps its own style" if ok else "STYLES LOST"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/bin/bash
# General-arrangement PDF drawings of the best design per programme
# (homemaker-py-m1mv): .dom -> homemaker-rooms -> homemaker-addon rooms2ifc.py
# -> ifcpatch GenerateGeneralArrangementDrawings -> headless Bonsai
# (render_drawings.py, render_sheets.py) -> one PDF per design.
#
#   experiments/drawings_bestof.sh [name ...]      # default: every pick
#
# Writes experiments/results/drawings-bestof/<name>/, and <name>.pdf beside
# it. Runs one design at a time: the desktop has 5 GB.
#
# Needs: the IfcOpenShell rpms with the ifcpatch recipe (0.9.1 20261028 or
# later -- earlier Bonsai builds fail in create_drawing), Blender with Bonsai,
# rsvg-convert, pdfunite; homemaker-addon at $ADDON and the two Blender
# drivers at $RENDER (from etruria-house-ifc/scripts).
set -euo pipefail

ADDON=${ADDON:-$HOME/src/homemaker-addon}
RENDER=${RENDER:-$HOME/src/etruria-house-ifc/scripts}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/experiments/results/drawings-bestof
# every pick is a +orth artefact
export HOMEMAKER_ORTHOGONAL_DIVISION=1

# name | .dom | programme directory | scale | sheet | homemaker-rooms options
# The recipe does not fit the views to the sheet: at 1:100 everything bigger
# than programme-house overflows A2, and at 1:200 so do the buildings with
# eight or more views.
PICKS="
programme-house|experiments/results/seedsolve-ab/seedsolve-ab-programme-house-built-s3.dom|examples/programme-house|100|A2|
harbor-house-handseed|examples/harbor-house/handseed-4428262+orth-500000-s2.dom|examples/harbor-house|200|A1|
harbor-house-evolved|experiments/results/halving-harbor-heights/best-heights-nospine-1-a.dom|examples/harbor-house|200|A2|
maple-court|experiments/results/halving-maple-connect/guard/winner.dom|examples/maple-court|200|A1|
health-centre|experiments/results/pivot-ab/pivot-ab-health-centre-pivot-s4.dom|examples/health-centre|200|A2|
"

draw() {
    local name=$1 dom=$2 programme=$3 scale=$4 sheet=$5 options=$6
    local dir=$OUT/$name
    rm -rf "$dir"
    mkdir -p "$dir"
    cp -f "$ROOT/$dom" "$dir/$name.dom"
    cd "$dir"
    # shellcheck disable=SC2086
    homemaker-rooms $options --programme "$ROOT/$programme" "$name.dom"
    python3 "$ADDON/rooms2ifc.py" "$name.dom.rooms.json" "$name.ifc"
    python3 -m ifcpatch -i "$name.ifc" -o "$name-ga.ifc" \
        -r GenerateGeneralArrangementDrawings -a "$scale" "$sheet" > ifcpatch.log 2>&1
    blender -b --python "$RENDER/render_drawings.py" -- "$dir/$name-ga.ifc" \
        > drawings.log 2>&1
    blender -b --python "$RENDER/render_sheets.py" -- "$dir/$name-ga.ifc" \
        > sheets.log 2>&1
    mapfile -t pdfs < <(grep '^-- sheet-pdf: ' sheets.log | sed 's/^-- sheet-pdf: //')
    if [ ${#pdfs[@]} -eq 0 ]; then
        echo "$name: no sheets; see $dir/*.log" >&2
        return 1
    fi
    pdfunite "${pdfs[@]}" "$OUT/$name.pdf"
    echo "$name: ${#pdfs[@]} sheet(s) -> $OUT/$name.pdf"
}

status=0
while IFS='|' read -r name dom programme scale sheet options; do
    [ -n "$name" ] || continue
    if [ $# -gt 0 ] && [[ ! " $* " == *" $name "* ]]; then
        continue
    fi
    SECONDS=0
    # a separate shell, so that set -e holds inside draw (bash ignores it in
    # a function called from an || list)
    bash -c "$(declare -p ROOT OUT ADDON RENDER); $(declare -f draw); set -euo pipefail; draw \"\$@\"" \
        draw "$name" "$dom" "$programme" "$scale" "$sheet" "$options" || status=1
    echo "$name: ${SECONDS} s"
done <<< "$PICKS"
exit $status

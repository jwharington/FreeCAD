"""Capture the bulkhead drape case as a nextdrape reproducer kit.

No bulkhead may be draped through the FreeCAD stack while the draper
needs minutes for this geometry (owner decision 2026-07-29).  This script
writes the exact geometry and setup that produced the failure — the
plate/band shells and the sewn doubly-curved skin they drape against —
as BREP files plus a setup.json, so nextdrape can load them directly
(``BRepTools::Read``) and fix the draper against the real case.

Usage:
    run-script.sh compositestests/inspect_bulkhead_drape_case.py \
        --out-dir ../../../3rdParty/nextdrape/data/bulkhead-plate-drape
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import Part


def capture(out_dir: Path) -> None:
    from Composites.compositeexamples.fixture_bulkhead import (
        AFT_SECTIONS, FORWARD_SECTIONS, lofted_bands, station_plane)
    from Composites.tools.bulkhead_section import (
        drape_cuts_of, make_bulkhead, section_chains)

    out_dir.mkdir(parents=True, exist_ok=True)
    cut = station_plane(210.0)

    # The sewn doubly-curved skin exactly as the panel drapes on it (the
    # panel solve at pitch 5.0 exceeded 100 s and was killed), the member
    # exactly as the wiring built it, and the footprint the band butts
    # against — every file a nextdrape case needs, nothing derived.
    sewn = lofted_bands([FORWARD_SECTIONS, AFT_SECTIONS], sewn=True)
    plates, bands = make_bulkhead(sewn, cut, 34.0, False)
    plate = Part.makeCompound(plates)
    band = Part.makeCompound(bands)
    cuts = drape_cuts_of(sewn, cut, 34.0, False)
    remainder = Part.makeCompound(cuts)

    for name, shape in (
            ("skin_sewn.brep", sewn), ("plate.brep", plate),
            ("band.brep", band), ("remainder.brep", remainder)):
        target = out_dir / name
        if target.exists():
            target.unlink()
        shape.exportBrep(str(target))

    chains = section_chains(sewn, cut)
    setup = {
        "case": "bulkhead-plate-drape",
        "symptom": ("plate drape took 14.7 s (expected: sub-second); "
                    "full-skin panel drape exceeded 100 s and was killed"),
        "setup": {
            "panel": {"shape": "skin_sewn.brep", "drape_pitch": 5.0,
                      "rosette_angle_deg": 0.0,
                      "rosette_support_sub": "Face1 of skin_sewn"},
            "plate_shell": {"shape": "plate.brep", "drape_pitch": 8.5,
                            "rosette_angle_deg": 0.0,
                            "note": "own drape solve; 14.7 s observed"},
            "band_shell": {"shape": "band.brep", "drape_pitch": 8.5,
                           "note": ("borrows the panel's solved drape "
                                    "(DrapeSource), butt joint against "
                                    "remainder.brep along the chain")},
            "laminate": {"plies": [{"angle_deg": 0.0, "thickness_mm": 0.5},
                                    {"angle_deg": 90.0,
                                     "thickness_mm": 0.5}],
                          "material": "glass, example_materials.make_glass()"},
        },
        "section_chain": {"chains": [[len(c.Edges), round(c.Length, 3)]
                                      for c in chains],
                           "seam_crossing_cut": False,
                           "note": ("x=210 lies mid-forward, clear of the "
                                     "x=300 seam; the chain is one closed "
                                     "chain either way")},
        "rebuild_recipe": ("fixture_bulkhead.lofted_bands([FORWARD_SECTIONS,"
                            " AFT_SECTIONS], sewn=True) + "
                            "fixture_bulkhead.station_plane(210.0); width 34; "
                            "pitch = width/4 (both shells); one-sided prism, "
                            "mirror_x=False"),
        "observed_at": "branch fem-unified, headless FreeCADCmd",
    }
    (out_dir / "setup.json").write_text(json.dumps(setup, indent=2))
    print(f"captured -> {out_dir}")
    for f in sorted(out_dir.iterdir()):
        print(" ", f.name, f.stat().st_size, "bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path,
                        default=Path(__file__).resolve().parents[3]
                        / "3rdParty/nextdrape/data/bulkhead-plate-drape")
    args = parser.parse_args()
    capture(args.out_dir)

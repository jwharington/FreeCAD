# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Does a *full* ring's re-supported panel re-drape within the quality gates?

Decisive probe for the LS8e skin L/R split.  ``test_drape_on_resupported_panel``
proves a *band* stiffener's remainder re-drapes cleanly, but a fuselage frame
ring is annular: its seat spans the full closed section, so the remainder is
the skin split into the bands fore/aft of the ring **plus** the two slivers
between the foot's ends at the crown and the belly — i.e. it is cut along the
centreline.  Whether that gapped remainder still drapes within the coverage
and shear gates decides between two builds:

* within gates  -> the skin can stay one shell and the ring runs on the full
  skin (the owner's preferred shape);
* below gates   -> the skin must be split L/R *first* and the foot assembled
  from the half weaves (the foot weave IS the panel weave, shared surface).

Mirrors ``test_drape_on_resupported_panel`` but with the full fuselage ring.
Run headless:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_full_ring_remainder_drape.py
"""

import json

import FreeCAD
import Part

from Composites.compositestests.test_drape_on_resupported_panel import (
    TestDrapeOnResupportedPanel,
)
from Composites.compositestests.test_stiffener import lofted_skin_face
from Composites.compositestests.test_stiffener_composite_shell import (
    TestQuasiIsotropicStiffener,
)

COVERAGE_GATE = 0.95
SHEAR_GATE_DEG = 25.0


def main() -> int:
    case = TestDrapeOnResupportedPanel(
        "test_redrape_on_remainder_keeps_layup_quality"
    )
    case.setUp()
    from Composites.features.Stiffener import StiffenerFP

    sections = (
        (-10.0, 565.0, 460.0),
        (200.0, 495.0, 400.0),
        (420.0, 415.0, 330.0),
        (630.0, 355.0, 280.0),
    )
    panel = case._make_panel(
        name="SkinPanel",
        isotropic=False,
        rosette_angle=90.0,
        plate=lofted_skin_face(sections),
    )
    ring_laminate = case._make_laminate(
        TestQuasiIsotropicStiffener.QI_ANGLES,
        [0.5] * len(TestQuasiIsotropicStiffener.QI_ANGLES),
        [TestQuasiIsotropicStiffener.CARBON] * len(TestQuasiIsotropicStiffener.QI_ANGLES),
        name="RingLaminate",
        isotropic=True,
    )
    cut_object, face = case._ring_cut_surface("RingCutSurface")
    cut_object.Shape = face
    s = case.FRAME_SECTION
    profile = case._make_sketch(
        "RingProfile",
        [
            (FreeCAD.Vector(s, 0, 0), FreeCAD.Vector(0, 0, 0)),
            (FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, s, 0)),
            (FreeCAD.Vector(0, s, 0), FreeCAD.Vector(s, s, 0)),
        ],
    )
    stiffener = case.doc.addObject("Part::FeaturePython", "FrameRing")
    StiffenerFP(stiffener, support=panel, cut_surface=cut_object, profile=profile)
    stiffener.Laminate = ring_laminate
    case.doc.recompute()

    error = getattr(stiffener.Proxy, "last_error", None)
    print(f"[probe] ring wiring last_error: {error}", flush=True)

    # The remainder the panel re-draped on.
    remainder = case.doc.getObject("FrameRing_RemainderSupport")
    if remainder is not None:
        print(
            f"[probe] remainder: {len(remainder.Shape.Faces)} faces",
            flush=True,
        )
        for index, piece in enumerate(remainder.Shape.Faces, start=1):
            box = piece.BoundBox
            print(
                f"    [{index}] area {piece.Area:9.1f}  "
                f"y[{box.YMin:7.1f},{box.YMax:7.1f}]",
                flush=True,
            )

    raw = panel.DrapeDiagnostics
    if not raw:
        print("[probe] panel produced no drape diagnostics", flush=True)
        return 1
    diag = json.loads(raw)
    print(f"[probe] panel re-drape diagnostics: {json.dumps(diag)[:600]}", flush=True)
    coverage = float(diag.get("coverage_ratio", 0.0) or 0.0)
    shear = float(diag.get("max_shear_deg", 0.0) or 0.0)
    status = diag.get("status")
    verdict = (
        "WITHIN"
        if (status == "valid" and coverage >= COVERAGE_GATE and shear <= SHEAR_GATE_DEG)
        else "BELOW"
    )
    print(
        f"[probe] VERDICT: full-ring remainder re-drape is {verdict} gates "
        f"(status={status}, coverage {coverage:.3f}>={COVERAGE_GATE}, "
        f"shear {shear:.1f}<={SHEAR_GATE_DEG})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

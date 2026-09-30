# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""What each link of a chained stiffener support holds, piece by piece.

Two composite stiffeners on one panel (the
``TestMultipleStiffenersOnOnePanel`` fixture), so the support chains
original -> A's remainder -> B's remainder and the panel weaves on the
deepest link.  For every link this prints each piece's area and bounding
box, and the same for each stiffener's seat and foot, which is what the
remainder selection has to be judged against.

Written because the second link came back holding a single 1200 mm^2 piece
20 mm from the first stiffener's foot.  "The selection dropped pieces" and
"the pieces are not where they are expected" differ only in the extents.

Run headless:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \
        src/Mod/Composites/compositestests/inspect_chain_remainders.py
"""

from Composites.compositestests.test_stiffener_composite_shell import (
    TestMultipleStiffenersOnOnePanel,
)


def report(label: str, shape) -> None:
    """Print a shape's pieces with their areas and extents."""
    print(f"--- {label}: {len(shape.Faces)} face(s), area {shape.Area:.1f}", flush=True)
    for index, face in enumerate(shape.Faces, start=1):
        box = face.BoundBox
        print(
            f"    [{index}] area {face.Area:8.1f}  "
            f"x[{box.XMin:7.1f},{box.XMax:7.1f}]  "
            f"y[{box.YMin:7.1f},{box.YMax:7.1f}]  "
            f"z[{box.ZMin:7.1f},{box.ZMax:7.1f}]",
            flush=True,
        )


def main() -> int:
    case = TestMultipleStiffenersOnOnePanel(
        "test_two_stiffeners_record_their_seats_one_drape"
    )
    case.setUp()
    try:
        try:
            case._make_two_stiffeners()
        except ValueError as error:
            # The joint's wiring raises loudly when a shared edge is
            # missing; the geometry that provoked it is exactly what we
            # came to look at, so report it rather than aborting.
            print(f"(the flow raised: {error})")
        doc = case.doc
        print(
            f"--- document objects: {[obj.Name for obj in doc.Objects]}",
            flush=True,
        )
        for name in ("StiffenerA", "StiffenerB"):
            stiffener = doc.getObject(name)
            if stiffener is None:
                continue
            base = stiffener.SupportBase
            report(
                f"{name} SupportBase ({getattr(base, 'Name', base)})",
                base.Shape,
            )
            remainder = doc.getObject(f"{name}_RemainderSupport")
            if remainder is not None:
                report(f"{name} remainder", remainder.Shape)
            foot = doc.getObject(f"{name}_Foot")
            if foot is not None:
                report(f"{name} foot", foot.Shape)
        panel = doc.getObject("Panel")
        support = getattr(panel, "Support", None)
        if support is not None:
            report(f"panel support ({support.Name})", support.Shape)
    finally:
        case.tearDown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

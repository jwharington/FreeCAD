"""Seam extraction demo — creates a simple seam between two panels."""

import FreeCAD
import Part
from Composites.features.CompositeShell import CompositeShellFP
from Composites.features.Laminate import LaminateFP
from Composites.features.Rosette import RosetteFP
from Composites.features.SeamExtraction import SeamShellFP


def _face(pts):
    """Create a planar face from a list of vertices."""
    wire = Part.makePolygon(pts + [pts[0]])
    return Part.Face(wire)


def main():
    """Create a seam extraction example."""
    doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("SeamDemo")

    # Support geometry
    master_sup = doc.addObject("Part::Feature", "MasterSup")
    master_sup.Shape = _face([
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(50, -25, 0),
        FreeCAD.Vector(50, 25, 0),
        FreeCAD.Vector(0, 25, 0),
    ])

    att_sup = doc.addObject("Part::FeaturePython", "AttSup")
    att_sup.Shape = _face([
        FreeCAD.Vector(-50, -25, 0),
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(0, 25, 0),
        FreeCAD.Vector(-50, 25, 0),
    ])

    # Laminate
    lam = doc.addObject("Part::FeaturePython", "Laminate")
    LaminateFP(lam)

    # Rosettes on master (45°) and attachment (−45°) shells
    ros_master = doc.addObject("Part::FeaturePython", "Rosette_Master")
    RosetteFP(ros_master, support=master_sup)
    ros_master.Angle = 45.0

    ros_att = doc.addObject("Part::FeaturePython", "Rosette_Attachment")
    RosetteFP(ros_att, support=att_sup)
    ros_att.Angle = -45.0

    # Shells
    ms = doc.addObject("Part::FeaturePython", "MasterShell")
    CompositeShellFP(ms, support=master_sup, laminate=lam, rosette=ros_master)

    as_ = doc.addObject("Part::FeaturePython", "AttShell")
    CompositeShellFP(as_, support=att_sup, laminate=lam, rosette=ros_att)

    doc.recompute()

    # Seam extraction
    seam = doc.addObject("Part::FeaturePython", "SeamExtraction")
    SeamShellFP(seam, ms, as_)

    doc.recompute()

    print(f"Created {len(doc.Objects)} objects")
    print(f"Seam: {seam.Seam.Name if seam.Seam else 'None'}")
    print(f"Remainder: {seam.Remainder.Name if seam.Remainder else 'None'}")


if __name__ == "__main__":
    main()
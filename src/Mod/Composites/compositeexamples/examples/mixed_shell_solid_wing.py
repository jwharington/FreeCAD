# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""A composite wing: biaxial carbon skins over a solid foam core.

This is the case the mixed shell-and-solid work exists for. A NACA 2412 wing,
1000 mm span and 200 mm chord, is built as a solid Rohacell 51 WF foam core
with a 160 gsm biaxial carbon-epoxy ``Composite::Shell`` on each of its two
lateral surfaces. The skins are shells carrying a real per-ply laminate and a
fibre orientation, the core is volume elements, and CalculiX solves both in one
deck - no smeared equivalent, no separate models.

``*SHELL SECTION, COMPOSITE`` needs S8R or S6 shells, so the skins are meshed
second order; the core is meshed apart and merged node-disjoint (a skin sharing
the core's nodes is a hinge, and ``getFacesOnly`` then drops it silently), and
two ``*TIE``s bond each skin to the core face it lies on. The load case is a
cantilever - root end fixed, tip pulled down - so the tip deflection is
interpretable.

Assumptions, stated rather than buried.

**Core Poisson's ratio.** The ROHACELL WF datasheet (Evonik, October 2025)
gives the core's tensile modulus as 75 MPa (ISO 527-2) and its shear modulus as
20 MPa (DIN 53294), measured by different methods, and gives no Poisson's
ratio. E = 75 MPa with G = 20 MPa implies nu = E/(2G) - 1 = 0.875, which no
isotropic solid can have, so the two cannot both be used in an isotropic
idealisation. The tensile modulus is used and **nu = 0.3 is an assumption, not
from the datasheet**. The datasheet strengths (1.6 MPa tensile, 0.6 MPa
compressive, 0.8 MPa shear) are not used by a linear static solve.

**Ply thickness.** 160 g/m^2 of fibre at a fibre volume fraction of 0.55 with a
fibre density of 1750 kg/m^3 gives
t = 0.160 / (1750 * 0.55) = 0.166 mm per ply, derived rather than guessed.

**Ply count.** One fabric layer each side of the mid-plane, each layer being a
+45 and a -45 ply: a balanced symmetric ``[+/-45]s`` stack of four plies,
0.664 mm of skin on each surface.

**Skin reference surface.** Each skin's shell reference surface is the core
face it is bonded to (CalculiX ``OFFSET`` = 0), the same idealisation the mixed
shell-and-solid plate example uses, so the skin's mid-surface sits on the
interface rather than the whole skin lying outside the core. The eccentricity
is half a skin thickness - 0.33 mm against a 24 mm core, under 1.5%.

**Fibre frame.** The laminate's plies are at +/-45 deg in their rosette frame;
the rosette is anchored on the skin support face and its 0 deg direction is the
world X (chord) direction of that face, so the bias runs at 45 deg to the chord
and span.
"""

import math
import os

import ObjectsFem
import FreeCAD
import Part

from femexamples.meshes.merged_mesh import mesh_parts_separately

from ...features.CompositeShell import CompositeShellFP
from ...features.Rosette import RosetteFP
from ...features.TexturePlan import TexturePlanFP
from ._shell_example_common import (
    _add_analysis_member,
    _add_shell_section_and_material,
    _create_fem_base,
    _run_ccx,
    _set_constraint_refs,
    ensure_document,
    make_biaxial_laminate,
)

DOCUMENT_NAME = "Composites_Mixed_Shell_Solid_Wing"

SPAN_MM = 1000.0
CHORD_MM = 200.0
# MPXX: 2% camber at 40% chord, 12% thickness - a NACA 2412.
NACA_CAMBER = 0.02
NACA_CAMBER_POSITION = 0.40
NACA_THICKNESS = 0.12

# Cosine-spaced intervals per surface of the profile. The two surfaces are
# interpolated as single B-splines so the extrusion has exactly two lateral
# faces: many short edges would explode them into one face per segment and make
# the ties unwritable.
SURFACE_INTERVALS = 40

MESH_SIZE_MM = 12.0
DRAPE_PITCH_MM = 5.0

FORCE_N = 100.0
# The tip deflection has to look like a sandwich, not like bare foam. An
# Euler-Bernoulli estimate of the skin-stiffened cantilever,
# F L^3 / (3 E_skin I_skin) with I_skin = 2 c t (d/2)^2 ~ 3.8e4 mm^4 and
# E_skin = 135 GPa, gives ~6 mm; the foam core alone (E = 75 MPa,
# I ~ 1.5e5 mm^4) gives ~3000 mm. A bound of 50 mm is proof the skins are
# bonded and carrying the bending, with a wide margin on both sides.
TIP_DEFLECTION_BOUND_MM = 50.0

# 160 gsm biaxial carbon-epoxy skin, from the areal weight.
FABRIC_AREAL_WEIGHT_KG_M2 = 0.160
FIBRE_DENSITY_KG_M3 = 1750.0
FIBRE_VOLUME_FRACTION = 0.55
PLY_THICKNESS_MM = (
    FABRIC_AREAL_WEIGHT_KG_M2 / (FIBRE_DENSITY_KG_M3 * FIBRE_VOLUME_FRACTION)
) * 1000.0
BIAXIAL_ANGLE_DEG = 45.0
FABRIC_LAYERS = 1  # one layer each side -> [+/-45]s, four plies

ROHACELL_51_WF = {
    "Density": "52 kg/m^3",
    "YoungsModulus": "75 MPa",
    "PoissonRatio": "0.30",
}


def naca4_ordinates(camber, camber_position, thickness, chord, intervals):
    """Cosine-spaced NACA 4-digit outline as ``(upper, lower)`` point lists.

    Each list runs from the leading edge to the trailing edge and the two meet
    at both ends: the trailing-edge coefficient is the closed form (-0.1036),
    not the open one (-0.1015), so the thickness goes to zero there and the
    profile closes exactly. The points are offset normal to the camber line,
    which is the defining construction of the series.
    """
    upper = []
    lower = []
    for index in range(intervals + 1):
        theta = math.pi * index / intervals
        x = 0.5 * (1.0 - math.cos(theta))
        yt = 5.0 * thickness * (
            0.2969 * math.sqrt(x)
            - 0.1260 * x
            - 0.3516 * x * x
            + 0.2843 * x**3
            - 0.1036 * x**4
        )
        if x < camber_position:
            yc = camber / camber_position**2 * (2.0 * camber_position * x - x * x)
            slope = 2.0 * camber / camber_position**2 * (camber_position - x)
        else:
            yc = camber / (1.0 - camber_position) ** 2 * (
                (1.0 - 2.0 * camber_position)
                + 2.0 * camber_position * x
                - x * x
            )
            slope = 2.0 * camber / (1.0 - camber_position) ** 2 * (
                camber_position - x
            )
        normal = math.atan(slope)
        upper.append(
            (
                (x - yt * math.sin(normal)) * chord,
                (yc + yt * math.cos(normal)) * chord,
            )
        )
        lower.append(
            (
                (x + yt * math.sin(normal)) * chord,
                (yc - yt * math.cos(normal)) * chord,
            )
        )
    return upper, lower


def _spline_edge(points):
    """The B-spline edge through ``points`` (an XZ list, placed at y=0)."""
    curve = Part.BSplineCurve()
    curve.interpolate([FreeCAD.Vector(x, 0.0, z) for x, z in points])
    return curve.toShape()


def _make_core(doc):
    """The profile extruded along the span, as a Part::Feature solid."""
    upper, lower = naca4_ordinates(
        NACA_CAMBER,
        NACA_CAMBER_POSITION,
        NACA_THICKNESS,
        CHORD_MM,
        SURFACE_INTERVALS,
    )
    profile = Part.Face(
        Part.Wire([_spline_edge(upper), _spline_edge(list(reversed(lower)))])
    )
    core = doc.addObject("Part::Feature", "WingCore")
    core.Shape = profile.extrude(FreeCAD.Vector(0.0, SPAN_MM, 0.0))
    return core


def _make_skin_support(doc, name, points):
    """One profile surface swept along the span, as its own Part::Feature.

    The skins are separate objects from the core by construction: a reference
    to the core's own face would make the shell and the solid share a shape,
    and the mesher never sees them together anyway.
    """
    leading_edge = _spline_edge(points)
    trailing_edge = _spline_edge(points)
    trailing_edge.translate(FreeCAD.Vector(0.0, SPAN_MM, 0.0))
    support = doc.addObject("Part::Feature", name)
    support.Shape = Part.makeRuledSurface(leading_edge, trailing_edge)
    return support


def _make_skin(doc, support, name):
    """A composite shell on ``support`` with its own rosette and laminate."""
    rosette = doc.addObject("Part::FeaturePython", f"{name}Rosette")
    RosetteFP(rosette, support=(support, ["Face1"]))
    rosette.Angle = 0.0

    laminate = make_biaxial_laminate(
        doc,
        f"{name}Laminate",
        PLY_THICKNESS_MM,
        angle=BIAXIAL_ANGLE_DEG,
        fabric_layers=FABRIC_LAYERS,
    )

    shell = doc.addObject("Part::FeaturePython", f"{name}Shell")
    CompositeShellFP(shell, support=support, laminate=laminate, rosette=rosette)
    shell.DrapePitch = DRAPE_PITCH_MM
    doc.recompute()
    return shell, laminate


def _add_texture_plans(doc, tag, shells):
    """One flat pattern per draped woven shell (the D7 gate)."""
    plans = []
    for index, shell in enumerate(shells, start=1):
        plan = doc.addObject("Part::FeaturePython", f"{tag}_TexturePlan{index}")
        TexturePlanFP(plan, shells=[shell])
        plans.append(plan)
    doc.recompute()
    return plans


def _planar_face_name(obj, axis, value, tolerance=1e-6):
    """Name of the planar face whose centre lies on ``axis`` = ``value``."""
    for index, face in enumerate(obj.Shape.Faces, start=1):
        if face.Surface.TypeId != "Part::GeomPlane":
            continue
        if abs(getattr(face.CenterOfMass, axis) - value) < tolerance:
            return f"Face{index}"
    raise ValueError(f"{obj.Name} has no planar face on {axis}={value}")


def _lateral_face_names(obj):
    """``(lower, upper)`` names of the extrusion's two lateral walls.

    The walls are the faces that are not the two planar end caps: the profile
    is extruded as two B-spline edges, so each wall is one surface of linear
    extrusion. The count is asserted, not assumed: a profile built from many
    segments would come back as many walls, and the model would silently stop
    having one tieable face per skin.
    """
    walls = [
        (index, face)
        for index, face in enumerate(obj.Shape.Faces, start=1)
        if face.Surface.TypeId != "Part::GeomPlane"
    ]
    if len(walls) != 2:
        raise ValueError(
            f"{obj.Name} has {len(walls)} lateral walls, expected 2: the "
            f"profile must be two edges, not a polyline"
        )
    walls.sort(key=lambda item: item[1].CenterOfMass.z)
    return f"Face{walls[0][0]}", f"Face{walls[1][0]}"


def _add_core_material(doc, analysis, core, tag):
    material = ObjectsFem.makeMaterialSolid(doc, f"{tag}_CoreMaterial")
    data = material.Material
    data["Name"] = "ROHACELL 51 WF"
    data.update(ROHACELL_51_WF)
    material.Material = data
    # An empty sub-element names the solid itself: this material reaches
    # volumes only, the skins belong to their own materials.
    _set_constraint_refs(material, [(core, "")])
    _add_analysis_member(analysis, material)
    return material


def _add_load_case(doc, analysis, core, tag):
    fixed = ObjectsFem.makeConstraintFixed(doc, f"{tag}_Fixed")
    _set_constraint_refs(fixed, [(core, _planar_face_name(core, "y", 0.0))])
    _add_analysis_member(analysis, fixed)

    force = ObjectsFem.makeConstraintForce(doc, f"{tag}_Force")
    _set_constraint_refs(force, [(core, _planar_face_name(core, "y", SPAN_MM))])
    force.Force = f"{FORCE_N} N"
    force.DirectionVector = FreeCAD.Vector(0.0, 0.0, -1.0)
    _add_analysis_member(analysis, force)


def _add_tie(doc, analysis, support, core, core_face, tag):
    tie = ObjectsFem.makeConstraintTie(doc, f"{tag}_Tie")
    _set_constraint_refs(tie, [(support, "Face1"), (core, core_face)])
    # The position tolerance also has to reach the shell's expanded face,
    # which sits half a skin thickness (0.33 mm) off the reference surface.
    tie.Tolerance = 1.0
    _add_analysis_member(analysis, tie)
    return tie


def _max_displacement(analysis):
    for obj in analysis.Group:
        if obj.isDerivedFrom("Fem::FemResultObject"):
            lengths = getattr(obj, "DisplacementLengths", None)
            if lengths:
                return max(float(value) for value in lengths)
    return None


def build(doc=None, run_solver=False):
    """Build the mixed-skin wing; ``run_solver=True`` meshes, writes and solves."""
    doc = ensure_document(doc, DOCUMENT_NAME)
    tag = "MixedShellSolidWing"

    upper, lower = naca4_ordinates(
        NACA_CAMBER,
        NACA_CAMBER_POSITION,
        NACA_THICKNESS,
        CHORD_MM,
        SURFACE_INTERVALS,
    )
    core = _make_core(doc)
    upper_support = _make_skin_support(doc, "WingUpperSkinSupport", upper)
    lower_support = _make_skin_support(doc, "WingLowerSkinSupport", lower)
    upper_skin, upper_laminate = _make_skin(doc, upper_support, "WingUpperSkin")
    lower_skin, lower_laminate = _make_skin(doc, lower_support, "WingLowerSkin")
    plans = _add_texture_plans(doc, tag, [upper_skin, lower_skin])

    result = {
        "doc": doc,
        "core": core,
        "upper_support": upper_support,
        "lower_support": lower_support,
        "upper_skin": upper_skin,
        "lower_skin": lower_skin,
        "upper_laminate": upper_laminate,
        "lower_laminate": lower_laminate,
        "texture_plans": plans,
    }
    if not run_solver:
        return result

    lower_face, upper_face = _lateral_face_names(core)
    analysis, solver, mesh_obj = _create_fem_base(doc, tag)
    _add_shell_section_and_material(
        doc, analysis, upper_support, f"{tag}_UpperSkin", shell_obj=upper_skin
    )
    _add_shell_section_and_material(
        doc, analysis, lower_support, f"{tag}_LowerSkin", shell_obj=lower_skin
    )
    _add_core_material(doc, analysis, core, tag)
    _add_load_case(doc, analysis, core, tag)
    _add_tie(doc, analysis, upper_support, core, upper_face, f"{tag}_Upper")
    _add_tie(doc, analysis, lower_support, core, lower_face, f"{tag}_Lower")

    # The mesher never sees the parts together: a skin sharing the core's
    # nodes would be a hinge, and would stop being detected as a shell.
    mesh_obj.FemMesh = mesh_parts_separately(
        doc,
        [core, upper_support, lower_support],
        max_size=MESH_SIZE_MM,
        element_order="2nd",
    )
    geometry = doc.addObject("Part::Compound", f"{tag}_Geometry")
    geometry.Links = [core, upper_support, lower_support]
    mesh_obj.Shape = geometry
    doc.recompute()

    solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    if not solve_result:
        raise RuntimeError("CalculiX solve failed for the mixed shell-and-solid wing")

    with open(fem.inp_file_name, encoding="utf-8", errors="ignore") as fh:
        solver_input = fh.read()

    result.update(
        {
            "analysis": analysis,
            "solver": solver,
            "mesh": mesh_obj,
            "max_displacement": _max_displacement(analysis),
            "inp_file": os.path.abspath(fem.inp_file_name),
            "solver_input": solver_input,
        }
    )
    return result


def main():
    case = build(run_solver=True)
    mesh = case["mesh"].FemMesh
    print(
        f"mixed_shell_solid_wing: max_displacement={case['max_displacement']} "
        f"volumes={len(mesh.Volumes)} shells={len(mesh.FacesOnly)} "
        f"nodes={mesh.NodeCount}"
    )


if __name__ == "__main__":
    main()
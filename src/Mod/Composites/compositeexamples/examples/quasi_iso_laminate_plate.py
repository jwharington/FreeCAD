# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Quasi-isotropic laminate plate example."""

from ...objects import (
    CompositeLaminate,
    FibreCompositeLamina,
    SimpleFabric,
    StackModelType,
    SymmetryType,
    WeaveType,
)


def _carbon_material():
    return {
        "Name": "Carbon",
        "Density": "1750.0 kg/m^3",
        "PoissonRatioXY": "0.27",
        "PoissonRatioXZ": "0.27",
        "PoissonRatioYZ": "0.45",
        "ShearModulusXY": "5000 MPa",
        "ShearModulusXZ": "5000 MPa",
        "ShearModulusYZ": "3500 MPa",
        "YoungsModulusX": "135 GPa",
        "YoungsModulusY": "9.5 GPa",
        "YoungsModulusZ": "9.5 GPa",
    }


def _resin_material():
    return {
        "Name": "Epoxy",
        "Density": "1180.0 kg/m^3",
        "YoungsModulus": "3.300 GPa",
        "PoissonRatio": "0.35",
    }


def _make_ply(orientation):
    ply = SimpleFabric(
        material_fibre=_carbon_material(),
        orientation=orientation,
        weave=WeaveType.UD,
    )
    ply.thickness = 0.2
    return FibreCompositeLamina(fibre=ply)


def _ensure_document(doc):
    if doc is not None:
        return doc

    try:
        import FreeCAD
    except ImportError:
        return None

    return FreeCAD.newDocument("Composites_QuasiIso_Laminate")


def _maybe_run_solver(doc):
    if doc is not None and hasattr(doc, "recompute"):
        doc.recompute()


def build(doc=None, run_solver=False, isotropic_equivalent=True):
    doc = _ensure_document(doc)

    # A QI stack must be symmetric (Even) for isotropic presentation: the
    # balance validation requires B = 0, so the half-stack [0/45/-45/90]
    # becomes the full [0/45/-45/90]s layup.
    laminate = CompositeLaminate(
        symmetry=SymmetryType.Even,
        layers=[
            _make_ply(0),
            _make_ply(45),
            _make_ply(-45),
            _make_ply(90),
        ],
        volume_fraction_fibre=0.55,
        material_matrix=_resin_material(),
        isotropic_equivalent=isotropic_equivalent,
    )

    if run_solver:
        _maybe_run_solver(doc)

    result = {
        "doc": doc,
        "laminate": laminate,
    }
    if isotropic_equivalent:
        # Isotropic presentation: collapse to one equivalent material so
        # downstream consumers can inspect E / nu / G / density.
        merged = laminate.get_layers(StackModelType.Smeared)
        result["equivalent"] = merged[0]
    return result

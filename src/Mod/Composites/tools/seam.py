# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com


import Part

from . import splitAPI


def generate_seam_tube(wire: Part.Wire, overlap: float):
    o = wire.Edges[0].firstVertex().Point
    # wire.valueAt(wire.FirstParameter)

    def make_section():
        c = Part.Circle()
        c.Center = o
        c.Axis = (0, 1, 0)
        c.Radius = overlap
        return Part.Wire([c.toShape()])

    makeSolid = True
    isFrenet = True
    return wire.makePipeShell([make_section()], makeSolid, isFrenet)


def make_edge_seam(
    shape: Part.Shape,
    edges: list[Part.Edge],
    overlap: float = 10,
):
    if not edges:
        raise ValueError("No edges provided for seam generation")
    if shape.IsNull():
        raise ValueError("Input shape is null")

    # Validate edges
    for i, e in enumerate(edges):
        if e.isNull():
            raise ValueError(f"Edge at index {i} is null")
        if e.Length < 1e-9:
            raise ValueError(f"Edge at index {i} has zero length")

    try:
        sedges = Part.__sortEdges__(edges)
    except Exception as e:
        raise ValueError(f"Failed to sort edges: {str(e)}")

    tools = []
    for i, e in enumerate(sedges):
        try:
            tube = generate_seam_tube(Part.Wire(e), overlap)
            if tube.IsNull():
                raise ValueError(f"Failed to generate pipe shell for edge {i}")
            tools.append(tube)
        except Exception as e:
            raise ValueError(f"Error generating pipe shell for edge {i}: {str(e)}")

    try:
        return splitAPI.slice(shape, tools, "Split", 1e-6)
    except Exception as e:
        raise ValueError(f"Slice operation failed: {str(e)}")


def get_partner_edges(
    face1: Part.Face,
    face2: Part.Face,
):
    return [e2 for e2 in face2.Edges for e1 in face1.Edges if e2.isPartner(e1)]


def _fallback_join_edges(face1: Part.Face, face2: Part.Face):
    for candidate in (
        face1.common(face2),
        face1.section(face2),
        face2.section(face1),
    ):
        edges = getattr(candidate, "Edges", None)
        if edges:
            return edges
    return []


def make_join_seam(
    face1: Part.Face,
    face2: Part.Face,
    overlap: float = 10,
):
    # Validate inputs
    if face1.isNull() or face2.isNull():
        raise ValueError("One or both faces are null")
    if not face1.isValid() or not face2.isValid():
        raise ValueError("One or both faces are invalid")

    edges = get_partner_edges(face1, face2)

    if not edges:
        # Try fallback with diagnostics
        edges = _fallback_join_edges(face1, face2)
        if not edges:
            # Try intersection as last resort
            try:
                intersection = face1.intersect(face2)
                if intersection and hasattr(intersection, "Edges") and intersection.Edges:
                    edges = intersection.Edges
            except Exception as e:
                pass
            if not edges:
                raise ValueError(
                    f"Faces do not share a seam. "
                    f"Common edges: {len(edges)}. "
                    f"Try ensuring faces properly overlap or touch."
                )

    return make_edge_seam(face1, edges, overlap=overlap)

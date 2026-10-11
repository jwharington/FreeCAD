# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for the geometry helpers moved into Composites.util.geometry_util:
shape_area, edge_names_by_x and extreme_y_point."""

import Part
import pytest

from Composites.util.geometry_util import (
    edge_names_by_x,
    extreme_y_point,
    shape_area,
)


def test_shape_area_sums_the_faces():
    assert shape_area(Part.makeBox(2.0, 3.0, 4.0)) == pytest.approx(52.0)


def test_shape_area_of_no_faces_is_zero():
    assert shape_area(Part.makeCompound([])) == 0.0


def test_edge_names_by_x_orders_by_average_x():
    shape = Part.makeBox(1.0, 1.0, 1.0)
    names = edge_names_by_x(shape)
    assert len(names) == len(shape.Edges)
    by_name = {"Edge%d" % index: edge
               for index, edge in enumerate(shape.Edges, start=1)}
    averages = []
    for name in names:
        points = [v.Point for v in by_name[name].Vertexes]
        averages.append(sum(p.x for p in points) / len(points))
    assert averages == sorted(averages)


def test_edge_names_by_x_finds_the_nose_first():
    """Model +x points aft, so the forward-most edge is the first name."""
    shape = Part.makeBox(1.0, 1.0, 1.0)
    first = edge_names_by_x(shape)[0]
    edge = {name: e for name, e in zip(edge_names_by_x(shape), shape.Edges)}[first]
    assert all(v.Point.x == pytest.approx(0.0) for v in edge.Vertexes)


def _lateral_face(cylinder):
    for face in cylinder.Faces:
        if isinstance(face.Surface, Part.Cylinder):
            return face
    raise AssertionError("no lateral face on the cylinder")


def test_extreme_y_point_lands_on_the_widest_line():
    face = _lateral_face(Part.makeCylinder(10.0, 20.0))
    point = extreme_y_point(face)
    assert abs(point.y) == pytest.approx(10.0, abs=1e-6)
    box = face.BoundBox
    assert box.YMin - 1e-6 <= point.y <= box.YMax + 1e-6

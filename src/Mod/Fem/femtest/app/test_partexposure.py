# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Per-part accounting: a node on a bondline is in both members; a node off the
structure is counted, not dropped.  The tie and reach windows are arguments, so
the tests move them rather than relying on the defaults.
"""

import numpy as np
import pytest

import FreeCAD

from femtools import partexposure


def test_a_bondline_node_is_claimed_by_both_members():
    clouds = {"A": np.array([[0.0, 0.0, 0.0]]),
              "B": np.array([[0.2, 0.0, 0.0]])}
    assignment, unclaimed = partexposure.assign(
        np.array([[0.1, 0.0, 0.0]]), clouds, tie=0.5)
    assert set(assignment) == {"A", "B"}
    assert unclaimed == 0


def test_a_node_no_member_reaches_is_counted_not_dropped():
    clouds = {"A": np.array([[0.0, 0.0, 0.0]])}
    assignment, unclaimed = partexposure.assign(
        np.array([[1000.0, 0.0, 0.0]]), clouds)
    assert assignment == {}
    assert unclaimed == 1


def test_no_clouds_leaves_every_node_unclaimed():
    assignment, unclaimed = partexposure.assign(np.array([[0.0, 0.0, 0.0]]), {})
    assert assignment == {} and unclaimed == 1


def test_maxima_are_the_worst_per_member():
    utilization = np.array([0.1, 0.9, 0.3, 0.7])
    assignment = {"A": np.array([0, 1]), "B": np.array([2, 3])}
    assert partexposure.maxima(utilization, assignment) == {"A": 0.9, "B": 0.7}


def test_clouds_split_one_section_between_mirrored_members():
    zones = {1: "Skin_Section", 2: "Skin_Section"}
    coords = {1: (0.0, 0.0, 0.0), 2: (5.0, 0.0, 0.0)}
    claimed = {"Skin_Section": ["Left", "Right"]}
    boxes = {"Left": FreeCAD.BoundBox(-1.0, -1.0, -1.0, 1.0, 1.0, 1.0),
             "Right": FreeCAD.BoundBox(4.0, -1.0, -1.0, 6.0, 1.0, 1.0)}
    found, note = partexposure.clouds(zones, coords, claimed, boxes)
    assert found["Left"].tolist() == [[0.0, 0.0, 0.0]]
    assert found["Right"].tolist() == [[5.0, 0.0, 0.0]]
    assert note == ""


def test_a_deck_node_outside_every_box_is_reported():
    zones = {1: "Skin_Section", 2: "Skin_Section"}
    coords = {1: (0.0, 0.0, 0.0), 2: (50.0, 0.0, 0.0)}
    claimed = {"Skin_Section": ["Left"]}
    boxes = {"Left": FreeCAD.BoundBox(-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)}
    found, note = partexposure.clouds(zones, coords, claimed, boxes)
    assert found["Left"].tolist() == [[0.0, 0.0, 0.0]]
    assert note == "1 of 2 deck nodes name no member"


def test_section_members_keeps_only_meshed_members():
    assert partexposure.section_members(
        {"Skin_Section": ["Skin", "Unmeshed"]}, {"Skin"}) == {
            "Skin_Section": ["Skin"]}

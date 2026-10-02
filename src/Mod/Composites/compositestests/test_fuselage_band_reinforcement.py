"""What the engine-bay band adds to the skin is a specification.

The band is the skin within a fixed width of the cutout rim, and its job
is to replace the material the opening removed.  What it adds to the
field stack - two glass 0/90 pairs and one +-45 pair at the mid-plane - is
therefore a spec, not a detail: get it wrong and the one region on the
opening's load path has the wrong stiffness, while the build, the mesh
and the deck all stay quietly green.
"""
import importlib.util
import os
import sys

import pytest

_SCRIPT = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "Projects", "RTOA", "LS8e", "Design", "ls8e-design-tools",
    "propeller", "cad", "FuselageV2.py",
)


@pytest.fixture(scope="module")
def vv():
    spec = importlib.util.spec_from_file_location("fuselage_v2", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fuselage_v2"] = module
    spec.loader.exec_module(module)
    return module


def _thickness(stack):
    return round(sum(ply[3] for ply in stack), 6)


def test_reinforcement_is_a_45_pair_with_two_0_deg_plies_either_side(vv):
    """A +-45 pair with two 0 deg glass plies either side of it - the 0 deg
    plies are the fore-aft load path the opening cut, so they are the bulk
    of the reinforcement.  No 90 deg plies anywhere in it."""
    extra = vv.BAY_BAND_SCHEDULES[vv.BAY_BAND_SCHEDULE]
    assert [ply[1] for ply in extra] == [0.0, 0.0, 45.0, -45.0, 0.0, 0.0]
    assert all(ply[2] == "UD" and ply[0] == "Glass220UD" for ply in extra), \
        "reinforcement plies are glass UD: %s" % [ply[:3] for ply in extra]


def test_reinforcement_adds_the_published_thickness(vv):
    """Six 0.17 plies: 1.02 mm on every band, whichever zone it is in."""
    extra = vv.BAY_BAND_SCHEDULES[vv.BAY_BAND_SCHEDULE]
    assert _thickness(extra) == pytest.approx(1.02)
    for base in (vv.SKIN_PLY_STACK, vv.SKIN_PLY_STACK_FWD):
        assert _thickness(vv.band_ply_stack(base)) - _thickness(base) == \
            pytest.approx(1.02)


def test_reinforcement_is_glass(vv):
    """The band replaces structure the opening removed, so it is the same
    fibre as the skin around it; the field stack's polyester veil is not
    reinforcement and half the band would be doing nothing."""
    extra = vv.BAY_BAND_SCHEDULES[vv.BAY_BAND_SCHEDULE]
    assert all("Glass" in ply[0] for ply in extra), \
        "band plies must be glass: %s" % [ply[0] for ply in extra]


def test_field_plies_survive_in_order(vv):
    """The reinforcement is inserted, not substituted - the field stack is
    still there, in order, on either side of it."""
    base = vv.SKIN_PLY_STACK
    mid = len(base) // 2
    extra = vv.BAY_BAND_SCHEDULES[vv.BAY_BAND_SCHEDULE]
    band = vv.band_ply_stack(base)
    assert band[:mid] == base[:mid]
    assert band[mid + len(extra):] == base[mid:]


def test_insertion_is_balanced(vv):
    """Mirrored about its own mid-plane, so the extra plies add no
    bending-twist coupling of their own: every off-axis ply has its
    opposite at the mirror position, and only the coupling-free 0 deg
    plies may sit opposite anything."""
    extra = [ply[1] for ply in vv.BAY_BAND_SCHEDULES[vv.BAY_BAND_SCHEDULE]]
    for index, angle in enumerate(extra):
        mirror = extra[-1 - index]
        if angle in (0.0, 90.0):
            assert mirror in (0.0, 90.0), "position %d" % index
        else:
            assert mirror == -angle, "position %d" % index


def test_none_schedule_leaves_the_stack_alone(vv, monkeypatch):
    """A band schedule is the band: 'none' has to give back the field
    stack, not a stack with a hole where the mid-plane was."""
    monkeypatch.setattr(vv, "BAY_BAND_SCHEDULE", "none")
    assert vv.band_ply_stack(vv.SKIN_PLY_STACK) == vv.SKIN_PLY_STACK


@pytest.mark.parametrize("schedule",
                         ["none", "reinforcement", "qi_pair", "axial_pair",
                          "doubled"])
def test_every_schedule_gives_a_complete_stack(vv, monkeypatch, schedule):
    assert schedule in vv.BAY_BAND_SCHEDULES, "the schedule menu changed"
    base = vv.SKIN_PLY_STACK
    monkeypatch.setattr(vv, "BAY_BAND_SCHEDULE", schedule)
    band = vv.band_ply_stack(base)
    expected = base + base if schedule == "doubled" \
        else base + vv.BAY_BAND_SCHEDULES[schedule]
    assert _thickness(band) == pytest.approx(_thickness(expected))


def test_ships_with_the_specified_reinforcement(vv):
    if "FUSELAGE_BAY_BAND_PLIES" in os.environ:
        pytest.skip("schedule chosen by the environment")
    assert vv.BAY_BAND_SCHEDULE == "reinforcement"

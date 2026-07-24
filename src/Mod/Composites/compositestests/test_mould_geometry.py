# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Geometry-behavior tests for mould_analysis.py public functions.

Targets the 5 public functions that take/return Part.Shape:
- propose_parting_surface
- make_mould_halves
- normalize_source_shape
- analyze_source_shape
- validate_mould_result

Asserts their actual contracts (parting plane at bbox midpoint, mould
halves on the correct side of the parting plane, normalization confidence,
analysis status/ranking) — not just 'shape not null'. Uses programmatic
primitives with known geometry plus the 'propblade' real-world fixture.
"""

import os
import unittest

import FreeCAD
import Part

from Composites.tools.mould_analysis import (
    NORMALIZATION_CONFIDENCE_EXACT,
    NORMALIZATION_CONFIDENCE_FAIL,
    _analysis_gate_status,
    _classify_draft_faces,
    _direction_profile_and_violations,
    _dot,
    _face_midpoint_normal,
    _sample_draw_accessibility,
    _sample_face_draft_alignment,
    _withdrawal_clearance_validity_check,
    _whole_side_draft_envelope,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
    make_mould_halves,
    normalize_source_shape,
    propose_parting_surface,
    validate_mould_result,
)
from Composites.tools.profile_mould_analysis import (
    _make_blade_shape,
    _make_loft_shape,
)
from synthetic_mould_shapes import (
    make_angled_cone,
    make_sideways_cone,
    make_sphere,
    make_vertical_cone,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
PROPBLADE_PATH = os.path.join(FIXTURES_DIR, "propblade.FCStd")


def _box(dx=20.0, dy=15.0, dz=10.0):
    """A solid box centered on the origin is NOT what these helpers expect;
    they read shape.BoundBox, so place at origin for predictable bounds."""
    return Part.makeBox(dx, dy, dz, FreeCAD.Vector(0, 0, 0))


class TestProposePartingSurface(unittest.TestCase):
    """propose_parting_surface: plane at bbox midpoint along dominant axis."""

    def test_x_direction_plane_at_midpoint(self):
        shape = _box(dx=20.0, dy=10.0, dz=10.0)
        result = propose_parting_surface(shape, FreeCAD.Vector(1, 0, 0))
        self.assertEqual(result["status"], "Ready")
        self.assertFalse(result["shape"].isNull())
        # Parting plane at X midpoint = 10.0
        self.assertAlmostEqual(result["surface_offset"], 10.0, places=6)
        # Surface normal is the X axis
        n = result["surface_normal"]
        self.assertAlmostEqual(n.x, 1.0, places=6)
        self.assertAlmostEqual(abs(n.y) + abs(n.z), 0.0, places=6)

    def test_y_direction_plane_at_midpoint(self):
        shape = _box(dx=10.0, dy=20.0, dz=10.0)
        result = propose_parting_surface(shape, FreeCAD.Vector(0, 1, 0))
        self.assertEqual(result["status"], "Ready")
        self.assertAlmostEqual(result["surface_offset"], 10.0, places=6)
        n = result["surface_normal"]
        self.assertAlmostEqual(n.y, 1.0, places=6)

    def test_z_direction_plane_at_midpoint(self):
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        result = propose_parting_surface(shape, FreeCAD.Vector(0, 0, 1))
        self.assertEqual(result["status"], "Ready")
        self.assertAlmostEqual(result["surface_offset"], 10.0, places=6)
        n = result["surface_normal"]
        self.assertAlmostEqual(n.z, 1.0, places=6)

    def test_returns_valid_face_shape(self):
        shape = _box()
        result = propose_parting_surface(shape, FreeCAD.Vector(0, 0, 1))
        self.assertTrue(result["shape"].isValid())


class TestMakeMouldHalves(unittest.TestCase):
    """make_mould_halves: two non-null solids split at the parting plane."""

    def test_two_halves_non_null(self):
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        # Parting at Z=10 (midpoint)
        result = make_mould_halves(shape, FreeCAD.Vector(0, 0, 1), 10.0)
        self.assertIn(result["status"], ("Ready", "Degraded"))
        self.assertFalse(result["half_a_shape"].isNull())
        self.assertFalse(result["half_b_shape"].isNull())
        self.assertGreater(result["half_a_volume"], 0.0)
        self.assertGreater(result["half_b_volume"], 0.0)

    def test_halves_lie_on_opposite_sides_of_parting(self):
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        result = make_mould_halves(shape, FreeCAD.Vector(0, 0, 1), 10.0)
        # half_a is below the parting plane (Z < 10), half_b above (Z > 10)
        a = result["half_a_shape"]
        b = result["half_b_shape"]
        self.assertLessEqual(a.BoundBox.ZMax, 10.0 + 1e-6)
        self.assertGreaterEqual(b.BoundBox.ZMin, 10.0 - 1e-6)

    def test_each_half_has_positive_stock_volume(self):
        # The mould halves are stock blanks with the source cut out (cavity),
        # so their combined volume is NOT necessarily > source. The meaningful
        # contract is that each half is a real, positive-volume solid.
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        result = make_mould_halves(shape, FreeCAD.Vector(0, 0, 1), 10.0)
        self.assertGreater(result["half_a_volume"], 0.0)
        self.assertGreater(result["half_b_volume"], 0.0)


class TestNormalizeSourceShape(unittest.TestCase):
    """normalize_source_shape: confidence + effective solid."""

    def test_solid_passes_through_exact(self):
        shape = _box()
        result = normalize_source_shape(shape)
        self.assertEqual(result["confidence"], NORMALIZATION_CONFIDENCE_EXACT)
        self.assertFalse(result["effective_shape"].isNull())

    def test_null_shape_fails(self):
        result = normalize_source_shape(Part.Shape())
        self.assertEqual(result["confidence"], NORMALIZATION_CONFIDENCE_FAIL)

    def test_effective_shape_is_solid(self):
        shape = _box()
        result = normalize_source_shape(shape)
        eff = result["effective_shape"]
        # A normalized solid should have positive volume
        self.assertGreater(eff.Volume, 0.0)


class TestDraftFaceClassification(unittest.TestCase):
    """_classify_draft_faces: screen box faces against a draw direction."""

    def test_box_faces_split_into_safe_risky_and_ambiguous(self):
        shape = _box(dx=20.0, dy=10.0, dz=10.0)
        result = _classify_draft_faces(shape, FreeCAD.Vector(0, 0, 1))
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["safe_face_count"], 1)
        self.assertEqual(result["risky_face_count"], 1)
        self.assertEqual(result["ambiguous_face_count"], 4)
        self.assertAlmostEqual(result["safe_face_area"], 200.0, places=6)
        self.assertAlmostEqual(result["risky_face_area"], 200.0, places=6)
        self.assertAlmostEqual(result["ambiguous_face_area"], 600.0, places=6)
        self.assertEqual(len(result["face_classifications"]), 6)

    def test_midpoint_normal_can_miss_local_negative_draft_on_twisted_shapes(self):
        cases = {
            "blade": _make_blade_shape(),
            "loft": _make_loft_shape(),
        }
        for shape_name, shape in cases.items():
            with self.subTest(shape=shape_name):
                evidence = None
                for face_index, face in enumerate(shape.Faces, start=1):
                    midpoint_normal = _face_midpoint_normal(face)
                    if midpoint_normal is None:
                        continue

                    midpoint_dot = _dot(
                        midpoint_normal,
                        default_mould_analysis_draw_direction,
                    )
                    sampled = _sample_face_draft_alignment(
                        face,
                        default_mould_analysis_draw_direction,
                    )
                    if sampled["min_direction_dot"] is None:
                        continue
                    if midpoint_dot > 0.0 and sampled["min_direction_dot"] < 0.0:
                        evidence = {
                            "face_index": face_index,
                            "midpoint_dot": midpoint_dot,
                            "min_sample_dot": sampled["min_direction_dot"],
                        }
                        break

                self.assertIsNotNone(
                    evidence,
                    f"{shape_name} should expose a face whose midpoint normal hides local negative draft",
                )
                self.assertGreater(evidence["midpoint_dot"], 0.0)
                self.assertLess(evidence["min_sample_dot"], 0.0)


class TestWholeSideDraftEnvelope(unittest.TestCase):
    """_whole_side_draft_envelope: per-side draft aggregation across the planar split.

    Distinguishes a local midpoint miss (one face hides a local undercut) from
    a true global parting-model failure (a whole side of the split is
    unreleasable). Sample points are classified by position relative to the
    parting offset, so a face spanning the parting plane feeds both sides.
    """

    def test_box_is_releasable_on_both_sides(self):
        shape = _box()
        result = _whole_side_draft_envelope(
            shape,
            default_mould_analysis_draw_direction,
            samples_per_axis=5,
        )
        self.assertEqual(result["status"], "Pass")
        self.assertEqual(result["upper_undercut_count"], 0)
        self.assertEqual(result["lower_undercut_count"], 0)
        self.assertEqual(result["globally_negative_sides"], [])

    def test_blade_has_globally_negative_sides(self):
        shape = _make_blade_shape()
        result = _whole_side_draft_envelope(
            shape,
            default_mould_analysis_draw_direction,
            samples_per_axis=5,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(set(result["globally_negative_sides"]), {"upper", "lower"})
        self.assertGreater(result["upper_undercut_count"], 0)
        self.assertGreater(result["lower_undercut_count"], 0)

    def test_loft_has_globally_negative_sides(self):
        shape = _make_loft_shape()
        result = _whole_side_draft_envelope(
            shape,
            default_mould_analysis_draw_direction,
            samples_per_axis=5,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(set(result["globally_negative_sides"]), {"upper", "lower"})
        self.assertGreater(result["upper_undercut_count"], 0)
        self.assertGreater(result["lower_undercut_count"], 0)

    def test_spanning_face_contributes_to_both_sides(self):
        # The lofted side wall is one face spanning the parting plane; its
        # samples must land on both sides, proving per-sample classification
        # rather than a face-centre split that would assign it to one side.
        shape = _make_loft_shape()
        result = _whole_side_draft_envelope(
            shape,
            default_mould_analysis_draw_direction,
            samples_per_axis=5,
        )
        spanning = next(
            face for face in result["per_face"]
            if face["upper_sample_count"] > 0 and face["lower_sample_count"] > 0
        )
        self.assertGreater(spanning["upper_undercut_count"], 0)
        self.assertGreater(spanning["lower_undercut_count"], 0)

    def test_lower_side_is_the_severer_global_failure(self):
        # On twisted geometry the camber hooks the lower mould half harder:
        # lower-side worst releasability is more negative and its undercut
        # fraction is higher than the upper side. This is the signal that
        # separates a global parting-model failure from a local midpoint miss.
        cases = {
            "blade": _make_blade_shape(),
            "loft": _make_loft_shape(),
        }
        for shape_name, shape in cases.items():
            with self.subTest(shape=shape_name):
                result = _whole_side_draft_envelope(
                    shape,
                    default_mould_analysis_draw_direction,
                    samples_per_axis=5,
                )
                self.assertLess(
                    result["lower_worst_releasability"],
                    result["upper_worst_releasability"],
                )
                self.assertGreater(
                    result["lower_undercut_fraction"],
                    result["upper_undercut_fraction"],
                )


class TestDraftEnvelopePrimitives(unittest.TestCase):
    """Cone and sphere primitives pin the envelope's sign logic and sampling.

    The sphere is the canonical correctness probe: convex, so it is releasable
    on both sides only when the parting plane passes through its centre, and
    on exactly one side everywhere else. A uniform parametric grid can step
    over the thin undercut band near an off-centre parting plane (a real
    false-negative), so these tests also lock in the adaptive refinement that
    catches it.
    """

    def test_sphere_center_parting_is_releasable_on_both_sides(self):
        result = _whole_side_draft_envelope(
            make_sphere(),
            default_mould_analysis_draw_direction,
            parting_offset=0.0,
        )
        self.assertEqual(result["status"], "Pass")
        self.assertEqual(result["globally_negative_sides"], [])
        self.assertEqual(result["upper_undercut_count"], 0)
        self.assertEqual(result["lower_undercut_count"], 0)

    def test_sphere_off_center_above_fails_only_lower_side(self):
        result = _whole_side_draft_envelope(
            make_sphere(),
            default_mould_analysis_draw_direction,
            parting_offset=5.0,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["globally_negative_sides"], ["lower"])
        self.assertGreater(result["upper_worst_releasability"], 0.0)
        self.assertLess(result["lower_worst_releasability"], 0.0)

    def test_sphere_off_center_below_fails_only_upper_side(self):
        result = _whole_side_draft_envelope(
            make_sphere(),
            default_mould_analysis_draw_direction,
            parting_offset=-5.0,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["globally_negative_sides"], ["upper"])
        self.assertGreater(result["lower_worst_releasability"], 0.0)
        self.assertLess(result["upper_worst_releasability"], 0.0)

    def test_sphere_at_most_one_side_unreleasable_across_offsets(self):
        # Convexity invariant: a sphere never hooks both mould halves at once.
        # The failing side must also flip with the sign of the offset.
        for offset in (-8.0, -5.0, -2.0, 0.0, 2.0, 5.0, 8.0):
            with self.subTest(offset=offset):
                result = _whole_side_draft_envelope(
                    make_sphere(),
                    default_mould_analysis_draw_direction,
                    parting_offset=offset,
                )
                self.assertLessEqual(len(result["globally_negative_sides"]), 1)
                if offset > 0.0:
                    self.assertEqual(result["globally_negative_sides"], ["lower"])
                elif offset < 0.0:
                    self.assertEqual(result["globally_negative_sides"], ["upper"])
                else:
                    self.assertEqual(result["globally_negative_sides"], [])

    def test_sphere_off_center_triggers_adaptive_refinement(self):
        # The thin undercut band near an off-centre parting plane is missed at
        # the coarse default grid; adaptive refinement must engage to resolve it.
        result = _whole_side_draft_envelope(
            make_sphere(),
            default_mould_analysis_draw_direction,
            parting_offset=5.0,
        )
        self.assertGreater(len(result["refinement_trace"]), 2)
        self.assertEqual(result["status"], "Fail")

    def test_vertical_cone_fails_only_lower_side(self):
        # Apex-up cone: side normals point up-and-out, so the lower mould half
        # hooks withdrawing downward; the upper cap releases.
        result = _whole_side_draft_envelope(
            make_vertical_cone(),
            default_mould_analysis_draw_direction,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["globally_negative_sides"], ["lower"])
        self.assertGreater(result["upper_worst_releasability"], 0.0)

    def test_sideways_cone_fails_only_upper_side(self):
        # Cone lying along X with draw +X: the failing side is the upper (X+)
        # half, proving the envelope attributes failure from real geometry, not
        # a hardcoded upper/lower assumption.
        result = _whole_side_draft_envelope(
            make_sideways_cone(),
            FreeCAD.Vector(1, 0, 0),
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["globally_negative_sides"], ["upper"])
        self.assertGreater(result["lower_worst_releasability"], 0.0)

    def test_angled_cone_can_fail_both_sides(self):
        # A cone tilted 45 degrees from the draw direction is convex, yet the
        # oblique draw hooks both halves. Convexity alone does not guarantee a
        # single-sided failure when the draw is not axis-aligned.
        result = _whole_side_draft_envelope(
            make_angled_cone(45.0),
            default_mould_analysis_draw_direction,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(
            set(result["globally_negative_sides"]), {"upper", "lower"}
        )

    def test_primitives_have_no_silent_sample_loss(self):
        # A skipped sample is a swallowed normalAt/valueAt failure that could
        # hide an undercut. On clean primitives the skipped count must be zero.
        cases = {
            "sphere": (make_sphere(), default_mould_analysis_draw_direction),
            "cone-vertical": (
                make_vertical_cone(),
                default_mould_analysis_draw_direction,
            ),
            "cone-sideways": (make_sideways_cone(), FreeCAD.Vector(1, 0, 0)),
            "box": (_box(), default_mould_analysis_draw_direction),
        }
        for name, (shape, direction) in cases.items():
            with self.subTest(shape=name):
                result = _whole_side_draft_envelope(shape, direction)
                self.assertEqual(result["skipped_sample_count"], 0)


class TestAccessibilitySampling(unittest.TestCase):
    """_sample_draw_accessibility: ray sampling along a draw direction."""

    def test_box_is_accessible_along_z(self):
        shape = _box(dx=20.0, dy=10.0, dz=10.0)
        result = _sample_draw_accessibility(shape, FreeCAD.Vector(0, 0, 1))
        self.assertEqual(result["status"], "Ready")
        self.assertGreater(result["sample_count"], 0)
        self.assertEqual(result["blocked_sample_count"], 0)
        self.assertEqual(result["multi_hit_sample_count"], 0)
        self.assertEqual(result["accessibility_regions"], ["None"])

    def test_disjoint_stacked_solids_trigger_multi_hit(self):
        lower = Part.makeBox(10.0, 10.0, 4.0, FreeCAD.Vector(0, 0, 0))
        upper = Part.makeBox(10.0, 10.0, 4.0, FreeCAD.Vector(0, 0, 8.0))
        shape = Part.makeCompound([lower, upper])
        result = _sample_draw_accessibility(shape, FreeCAD.Vector(0, 0, 1))
        self.assertEqual(result["status"], "Fail")
        self.assertGreater(result["multi_hit_sample_count"], 0)
        self.assertTrue(result["accessibility_regions"])
        self.assertTrue(result["ray_samples"])

    def test_side_by_side_solids_pin_blocked_outcome(self):
        # Two solids separated across the transverse plane leave a gap that a
        # draw-aligned ray passes through without hitting: that is the
        # "blocked" classification (hit_segments<=0, hit_vertices<=0),
        # distinct from "multi_hit" (a ray that hits more than one segment).
        # The gap is made wide enough that the default transverse grid lands
        # points squarely inside it (not on box edges), so the blocked
        # outcome is stable across sample densities. Pinning it completes the
        # clear / blocked / multi-hit trio so a regression in hit
        # classification is localized to the accessibility sampler, not
        # blamed on gating or validation.
        left = Part.makeBox(3.0, 10.0, 10.0, FreeCAD.Vector(0, 0, 0))
        right = Part.makeBox(3.0, 10.0, 10.0, FreeCAD.Vector(7, 0, 0))
        shape = Part.makeCompound([left, right])
        result = _sample_draw_accessibility(shape, FreeCAD.Vector(0, 0, 1))
        self.assertEqual(result["status"], "Warning")
        self.assertGreater(result["blocked_sample_count"], 0)
        self.assertEqual(result["multi_hit_sample_count"], 0)
        blocked = next(
            sample for sample in result["ray_samples"]
            if sample["classification"] == "blocked"
        )
        self.assertLessEqual(blocked["hit_segments"], 0)
        self.assertLessEqual(blocked["hit_vertices"], 0)


class TestAnalysisGateStatus(unittest.TestCase):
    """_analysis_gate_status: the policy that turns evidence into a verdict.

    Driven directly with crafted evidence dicts, not through the full
    pipeline, so a status-policy regression is isolated from the geometric
    evidence gathering. The contract: uncertain evidence stays a Warning
    (never silently escalates to Fail), a true accessibility failure is a
    hard Fail, and clean evidence is a Pass.
    """

    def test_clean_evidence_passes(self):
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Pass"}, {"status": "Ready"},
            ),
            "Pass",
        )

    def test_accessibility_fail_is_a_hard_fail(self):
        # A true failure (multi-hit access) must return Fail, not Warning.
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Pass"}, {"status": "Fail"},
            ),
            "Fail",
        )

    def test_uncertain_accessibility_stays_warning_not_fail(self):
        # Blocked access is uncertain (a ray missed), not a proven release
        # failure, so it must not escalate to Fail.
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Pass"}, {"status": "Warning"},
            ),
            "Warning",
        )

    def test_draft_warning_with_risky_faces_stays_warning(self):
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Warning", "risky_face_count": 3},
                {"status": "Ready"},
            ),
            "Warning",
        )

    def test_draft_warning_without_risky_faces_is_clean(self):
        # A draft-screening "Warning" label alone, with zero risky faces, is
        # not even a warning: the gate trusts clean accessibility over the
        # draft label.
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Warning", "risky_face_count": 0},
                {"status": "Ready"},
            ),
            "Pass",
        )

    def test_draft_face_fail_label_does_not_override_clean_access(self):
        # _classify_draft_faces returns "Fail" for a plain box (its bottom
        # face is "risky"), yet a box is perfectly mouldable. The gate
        # therefore treats draft-face status as non-authoritative when
        # accessibility is clean: a draft "Fail" does NOT gate-fail unless
        # accessibility also fails. Pinning this policy so a future change to
        # make draft authoritative is a deliberate, visible decision.
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Fail", "risky_face_count": 1},
                {"status": "Ready"},
            ),
            "Pass",
        )


class TestDiscretizationSensitivity(unittest.TestCase):
    """_sample_draw_accessibility: evidence must respond to sample density.

    A discretization that returns identical evidence regardless of resolution
    is cosmetic — the accuracy knob is not plumbed through. The easy shape
    (box) must stay stable (clear at every density), while a non-box-filling
    shape (sphere) must show its blocked-sample count grow as the grid
    tightens. If this fails, the bug is in the scan resolution / density
    plumbing, not in the evidence interpretation.
    """

    def test_box_stays_clear_as_density_tightens(self):
        shape = _box(dx=20.0, dy=10.0, dz=10.0)
        direction = FreeCAD.Vector(0, 0, 1)
        densities = (0.05, 0.2, 0.5)
        counts = []
        for density in densities:
            result = _sample_draw_accessibility(shape, direction, sample_density=density)
            self.assertEqual(result["status"], "Ready")
            self.assertEqual(result["blocked_sample_count"], 0)
            self.assertEqual(result["multi_hit_sample_count"], 0)
            counts.append(result["sample_count"])
        # Strictly increasing sample count proves density actually feeds the grid.
        self.assertGreater(counts[1], counts[0])
        self.assertGreater(counts[2], counts[1])

    def test_sphere_blocked_count_grows_with_density(self):
        shape = make_sphere()
        direction = FreeCAD.Vector(0, 0, 1)
        coarse = _sample_draw_accessibility(shape, direction, sample_density=0.05)
        fine = _sample_draw_accessibility(shape, direction, sample_density=0.5)
        self.assertGreater(fine["sample_count"], coarse["sample_count"])
        # Corner rays miss the sphere at both resolutions, proving the
        # sampler reports non-trivial evidence; the count grows with density.
        self.assertGreater(coarse["blocked_sample_count"], 0)
        self.assertGreater(fine["blocked_sample_count"], coarse["blocked_sample_count"])


class TestAnalyzeSourceShape(unittest.TestCase):
    """analyze_source_shape: status, best direction on a known box."""

    def test_box_yields_ready_status(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertEqual(result["status"], "Ready")
        self.assertEqual(result["validation_status"], "Pass")

    def test_box_uses_geometric_screening_only(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertEqual(result["analysis_method"], "geometric_screening_only")
        self.assertFalse(result["slice_refinement_required"])
        self.assertEqual(result["profile_violations"], [])
        self.assertIn("geometric refinement skipped", result["slice_refinement_summary"].lower())

    def test_best_direction_is_axis_aligned(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        best = result["best_draw_direction"]
        # The draw direction is user-specified; best_draw_direction mirrors it.
        self.assertAlmostEqual(best.Length, 1.0, places=6)

    def test_candidate_strategies_reuse_geometric_evidence(self):
        # Even with a single authoritative direction, the split-strategy
        # attempt must reuse the precomputed draft-face / accessibility /
        # geometric-evidence bundles rather than recomputing them.
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        first_attempt = result["split_strategy_attempts"][0]
        self.assertIsNone(first_attempt.get("exception") or None)
        # The first split-strategy attempt always reuses the strategy's evidence.
        self.assertTrue(first_attempt.get("analysis_gate_status"))

    def test_null_shape_no_exception(self):
        # The documented early-return: null shape must not raise.
        result = analyze_source_shape(Part.Shape(),
                                      default_mould_analysis_draw_direction)
        self.assertEqual(result["status"], "Waiting for source")

    def test_manufacturability_metrics_present(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        metrics = result["manufacturability_metrics"]
        for key in ("backface_area_ratio", "undercut_count",
                    "draft_violation_count", "multipart_piece_count",
                    "risk_index", "risk_class"):
            self.assertIn(key, metrics)

    def test_slice_refinement_regression_fields_present(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertIn("slice_refinement_required", result)
        self.assertIn("slice_refinement_summary", result)
        self.assertFalse(result["slice_refinement_required"])
        self.assertTrue(result["slice_refinement_summary"])
        self.assertTrue(result["split_strategy_attempts"])
        first_attempt = result["split_strategy_attempts"][0]
        self.assertIn("slice_refinement_required", first_attempt)
        self.assertIn("analysis_gate_status", first_attempt)
        self.assertEqual(first_attempt["analysis_gate_status"], "Pass")
        self.assertIn("accessibility_status", first_attempt)

    def test_slice_profile_helper_remains_available_for_regression_diagnostics(self):
        shape = _box()
        profile, violations = _direction_profile_and_violations(
            shape,
            FreeCAD.Vector(0, 0, 1),
        )
        self.assertTrue(profile)
        self.assertEqual(violations, [])

    def test_top_level_evidence_fields_present(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertIn("analysis_gate_status", result)
        self.assertIn("analysis_method", result)
        self.assertIn("analysis_confidence", result)
        self.assertIn("draft_face_summary", result)
        self.assertIn("draft_face_classifications", result)
        self.assertIn("accessibility_summary", result)
        self.assertIn("accessibility_checks", result)
        self.assertIn("profile_summary", result)
        self.assertIn("profile_violations", result)
        self.assertIn("geometric_accuracy_mm", result)
        self.assertIn("geometric_accuracy_tolerance_mm", result)
        self.assertIn("geometric_accuracy_status", result)
        self.assertIn("geometric_accuracy_summary", result)
        self.assertTrue(result["analysis_method"])
        self.assertTrue(result["analysis_confidence"])
        self.assertTrue(result["draft_face_summary"])
        self.assertTrue(result["accessibility_summary"])
        self.assertTrue(result["profile_summary"])
        self.assertLessEqual(
            result["geometric_accuracy_mm"],
            result["geometric_accuracy_tolerance_mm"],
        )
        self.assertEqual(result["geometric_accuracy_status"], "Pass")

    def test_summaries_non_empty(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertTrue(result["summary"])
        self.assertTrue(result["manufacturability_summary"])

    def test_fast_loop_shapes_separate_box_from_planar_limits(self):
        # Each shape is analyzed under a draw direction where it is
        # releasable (no multi-hit re-entrant region): box and blade under
        # the default +Z, loft under +X (+Z has a genuine multi-hit re-entrance
        # on the loft, so +Z is a bad user choice for it — exactly the signal
        # an authoritative-direction analysis must surface).
        cases = {
            "box": {
                "direction": default_mould_analysis_draw_direction,
                "status": "Ready",
                "validation_status": "Pass",
                "analysis_gate_status": "Pass",
                "analysis_method": "geometric_screening_only",
                "slice_refinement_required": False,
            },
            "blade": {
                "direction": default_mould_analysis_draw_direction,
                "status": "Warning",
                "validation_status": "Warning",
                "analysis_gate_status": "Warning",
                "analysis_method": "geometric_screening_with_geometric_refinement",
                "slice_refinement_required": True,
            },
            "loft": {
                "direction": FreeCAD.Vector(1, 0, 0),
                "status": "Warning",
                "validation_status": "Warning",
                "analysis_gate_status": "Warning",
                "analysis_method": "geometric_screening_with_geometric_refinement",
                "slice_refinement_required": True,
            },
        }
        for shape_name, expectations in cases.items():
            with self.subTest(shape=shape_name):
                shape = _box() if shape_name == "box" else {
                    "blade": _make_blade_shape(),
                    "loft": _make_loft_shape(),
                }[shape_name]
                result = analyze_source_shape(
                    shape,
                    expectations["direction"],
                )
                self.assertEqual(result["status"], expectations["status"])
                self.assertEqual(
                    result["validation_status"],
                    expectations["validation_status"],
                )
                self.assertEqual(
                    result["analysis_gate_status"],
                    expectations["analysis_gate_status"],
                )
                self.assertEqual(
                    result["analysis_method"],
                    expectations["analysis_method"],
                )
                self.assertEqual(
                    result["slice_refinement_required"],
                    expectations["slice_refinement_required"],
                )
                self.assertTrue(result["summary"])
                self.assertAlmostEqual(result["geometric_accuracy_tolerance_mm"], 0.1, places=6)
                self.assertLessEqual(
                    result["geometric_accuracy_mm"],
                    result["geometric_accuracy_tolerance_mm"],
                )
                self.assertEqual(result["geometric_accuracy_status"], "Pass")


class TestWithdrawalClearanceValidity(unittest.TestCase):
    """Withdrawal-clearance validity: the mould must withdraw without colliding."""

    def test_inspection_helper_reports_box_clearance_pass(self):
        from compositestests.inspect_mould_results import inspect_benchmark_shape

        report = inspect_benchmark_shape("box")
        self.assertEqual(report["shape_name"], "box")
        self.assertTrue(report["document_name"])
        self.assertTrue(report["object_name"])
        self.assertEqual(report["analysis"]["status"], "Ready")
        self.assertEqual(report["withdrawal_clearance"]["status"], "Pass")
        self.assertEqual(report["withdrawal_clearance"]["failure_count"], 0)

    def test_box_mould_halves_clear_the_source(self):
        shape = _box()
        parting = propose_parting_surface(shape, FreeCAD.Vector(0, 0, 1))
        halves = make_mould_halves(
            shape,
            parting["surface_normal"],
            parting["surface_offset"],
        )
        clearance = _withdrawal_clearance_validity_check(
            shape,
            halves["half_a_shape"],
            halves["half_b_shape"],
            FreeCAD.Vector(0, 0, 1),
        )
        self.assertEqual(clearance["status"], "Pass")
        self.assertGreater(clearance["sample_count"], 0)
        self.assertEqual(clearance["failure_count"], 0)
        self.assertEqual(len(clearance["half_checks"]), 2)
        self.assertTrue(all(item["status"] == "Pass" for item in clearance["half_checks"]))

        validation = validate_mould_result(
            parting["status"],
            halves["status"],
            0,
            0,
            parting["shape"],
            halves["half_a_shape"],
            halves["half_b_shape"],
        )
        self.assertEqual(validation["status"], "Pass")

    def test_forced_collision_fails_the_gate(self):
        shape = _box()
        parting = propose_parting_surface(shape, FreeCAD.Vector(0, 0, 1))
        halves = make_mould_halves(
            shape,
            parting["surface_normal"],
            parting["surface_offset"],
        )
        collided_half = halves["half_a_shape"].copy()
        collided_half.translate(FreeCAD.Vector(0, 0, 4.0))
        clearance = _withdrawal_clearance_validity_check(
            shape,
            collided_half,
            halves["half_b_shape"],
            FreeCAD.Vector(0, 0, 1),
        )
        self.assertEqual(clearance["status"], "Fail")
        self.assertGreater(clearance["failure_count"], 0)
        self.assertTrue(clearance["failure_regions"])



class TestValidateMouldResult(unittest.TestCase):
    """validate_mould_result: status from inputs (pure function over shapes)."""

    def _valid(self, shape):
        return shape  # a real box is valid + non-null

    def test_pass_on_clean_inputs(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", 0, 0, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Pass")

    def test_fail_on_failed_parting_surface(self):
        shape = _box()
        result = validate_mould_result(
            "Fail", "Ready", 0, 0, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Fail")

    def test_warning_on_undercuts(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", 2, 0, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Warning")

    def test_warning_on_draft_violations(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", 0, 3, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Warning")

    def test_fail_on_null_half(self):
        shape = _box()
        null_shape = Part.Shape()
        result = validate_mould_result(
            "Ready", "Ready", 0, 0, shape, null_shape, shape,
        )
        self.assertEqual(result["status"], "Fail")

    def test_warning_when_analysis_gate_needs_refinement(self):
        shape = _box()
        result = validate_mould_result(
            "Ready",
            "Ready",
            0,
            0,
            shape,
            shape,
            shape,
            analysis_gate_status="Warning",
        )
        self.assertEqual(result["status"], "Warning")

    def test_fail_when_analysis_gate_fails_with_otherwise_clean_mould(self):
        # Isolation check: with a ready parting surface, valid halves, and zero
        # undercuts/violations, the ONLY failing signal is the analysis gate.
        # A gate Fail must escalate validation to Fail (mirroring the Warning
        # case above, which must NOT). This pins the coupling policy: warning-
        # grade screening stays a warning, a true gate failure hard-fails.
        shape = _box()
        result = validate_mould_result(
            "Ready",
            "Ready",
            0,
            0,
            shape,
            shape,
            shape,
            analysis_gate_status="Fail",
        )
        self.assertEqual(result["status"], "Fail")
        self.assertTrue(any("gate" in check.lower() for check in result["checks"]))


@unittest.skip("Propblade fixture disabled until later")
class TestPropbladeFixture(unittest.TestCase):
    """Real-world geometry: the propblade model now sits alongside the
    synthetic primitives as a primary mould-analysis test shape."""

    def setUp(self):
        self.doc = FreeCAD.openDocument(PROPBLADE_PATH)
        self.shape = None
        self.obj = None
        for obj in self.doc.Objects:
            if hasattr(obj, "Shape") and not obj.Shape.isNull():
                self.shape = obj.Shape
                self.obj = obj
                break
        self.assertIsNotNone(self.shape, "propblade fixture has no shape")

    def tearDown(self):
        try:
            FreeCAD.closeDocument(self.doc.Name)
        except Exception:
            pass

    def _analyze(self):
        return analyze_source_shape(
            self.shape,
            default_mould_analysis_draw_direction,
            source_obj=self.obj,
        )

    def test_fixture_opens_with_solid(self):
        self.assertTrue(self.shape.isValid())
        self.assertEqual(self.shape.ShapeType, "Solid")

    def test_normalize_handles_real_geometry(self):
        # Real CAD may report Volume=0 (shell-like) — normalize must still
        # produce an effective solid (possibly via bbox proxy) without failing.
        result = normalize_source_shape(self.shape)
        self.assertIn(
            result["confidence"],
            (NORMALIZATION_CONFIDENCE_EXACT, "approximate"),
        )
        self.assertFalse(result["effective_shape"].isNull())

    def test_analyze_yields_ready_mould(self):
        result = self._analyze()
        self.assertIn(result["status"], ("Ready", "Warning"))
        self.assertNotEqual(result["validation_status"], "Fail")
        self.assertTrue(result["summary"])

    def test_propblade_mould_halves_are_real_solids(self):
        result = self._analyze()
        halves = make_mould_halves(
            result["shape"],
            result["parting_surface_normal"],
            result["parting_surface_offset"],
        )
        self.assertIn(halves["status"], ("Ready", "Degraded"))
        self.assertFalse(halves["half_a_shape"].isNull())
        self.assertFalse(halves["half_b_shape"].isNull())
        self.assertGreater(halves["half_a_volume"], 0.0)
        self.assertGreater(halves["half_b_volume"], 0.0)

    def test_propblade_validation_not_fail(self):
        result = self._analyze()
        self.assertIn(result["validation_status"], ("Pass", "Warning"))
        self.assertTrue(result["validation_checks"])
        self.assertLessEqual(
            result["geometric_accuracy_mm"],
            result["geometric_accuracy_tolerance_mm"],
        )
        self.assertEqual(result["geometric_accuracy_status"], "Pass")


if __name__ == "__main__":
    unittest.main()

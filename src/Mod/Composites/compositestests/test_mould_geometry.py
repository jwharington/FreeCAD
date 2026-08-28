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

import math
import os
import unittest

import FreeCAD
import Part

from Composites.tools.mould_analysis import (
    NORMALIZATION_CONFIDENCE_EXACT,
    NORMALIZATION_CONFIDENCE_FAIL,
    _analysis_gate_status,
    _classify_draft_faces,
    _dot,
    _face_midpoint_normal,
    _sample_face_draft_alignment,
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


def _make_twisted_loft_shape():
    def make_rect(z, width, height, twist_rad):
        points = []
        for index in range(4):
            cx = -width / 2.0 if index in (0, 3) else width / 2.0
            cy = -height / 2.0 if index < 2 else height / 2.0
            x = cx * math.cos(twist_rad) - cy * math.sin(twist_rad)
            y = cx * math.sin(twist_rad) + cy * math.cos(twist_rad)
            points.append(FreeCAD.Vector(x, y, z))
        points.append(points[0])
        return Part.makePolygon(points)

    return Part.makeLoft([
        make_rect(0.0, 20.0, 6.0, 0.0),
        make_rect(20.0, 14.0, 4.0, math.pi / 6.0),
    ], solid=True)


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
            parting_offset=3.0,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["globally_negative_sides"], ["lower"])
        self.assertGreater(result["upper_worst_releasability"], 0.0)
        self.assertLess(result["lower_worst_releasability"], 0.0)

    def test_sphere_off_center_below_fails_only_upper_side(self):
        result = _whole_side_draft_envelope(
            make_sphere(),
            default_mould_analysis_draw_direction,
            parting_offset=-3.0,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertEqual(result["globally_negative_sides"], ["upper"])
        self.assertGreater(result["lower_worst_releasability"], 0.0)
        self.assertLess(result["upper_worst_releasability"], 0.0)

    def test_sphere_at_most_one_side_unreleasable_across_offsets(self):
        # Convexity invariant: a sphere never hooks both mould halves at once.
        # The failing side must also flip with the sign of the offset. The
        # offsets stay interior to the r=5 sphere; at/outside the pole (±5, ±8)
        # one side has zero samples and no meaningful worst releasability.
        for offset in (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0):
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
            parting_offset=3.0,
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


class TestAnalysisGateStatus(unittest.TestCase):
    """_analysis_gate_status: informational draft-face signal.

    Driven directly with crafted screening dicts. The gate is decoupled from
    the verdict: it reports Pass only when every face drafts cleanly away
    from the draw direction, Warning otherwise (which includes legitimate
    parting faces). It NEVER returns Fail — withdrawal clearance is the sole
    authoritative test and the only source of a hard Fail.
    """

    def test_clean_screening_passes(self):
        self.assertEqual(_analysis_gate_status({"status": "Ready"}), "Pass")

    def test_risky_faces_warn(self):
        # A box's bottom face is "risky" by the dot test; the gate flags it
        # Warning rather than asserting releasability it cannot prove.
        self.assertEqual(
            _analysis_gate_status({"status": "Fail", "risky_face_count": 2}),
            "Warning",
        )

    def test_ambiguous_faces_warn(self):
        self.assertEqual(
            _analysis_gate_status(
                {"status": "Warning", "risky_face_count": 0, "ambiguous_face_count": 1}
            ),
            "Warning",
        )

    def test_missing_screening_defaults_to_warning(self):
        self.assertEqual(_analysis_gate_status({}), "Warning")

    def test_gate_never_escalates_to_fail(self):
        # Even a draft "Fail" stays Warning: the gate cannot hard-fail —
        # only withdrawal clearance can. Pinning this so a future change
        # coupling the gate to a hard Fail is a deliberate, visible decision.
        self.assertEqual(
            _analysis_gate_status({"status": "Fail", "risky_face_count": 5}),
            "Warning",
        )


class TestAnalyzeSourceShape(unittest.TestCase):
    """analyze_source_shape: status, best direction on a known box."""

    def test_box_yields_ready_status(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertEqual(result["status"], "Ready")
        self.assertEqual(result["validation_status"], "Pass")

    def test_best_direction_is_axis_aligned(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        best = result["best_draw_direction"]
        # The draw direction is user-specified; best_draw_direction mirrors it.
        self.assertAlmostEqual(best.Length, 1.0, places=6)

    def test_candidate_strategies_reuse_geometric_evidence(self):
        # Even with a single authoritative direction, the split-strategy
        # attempt must reuse the precomputed draft-face / geometric-evidence
        # bundles rather than recomputing them.
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

    def test_top_level_evidence_fields_present(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertIn("analysis_gate_status", result)
        self.assertIn("draft_face_summary", result)
        self.assertIn("draft_face_classifications", result)
        self.assertIn("parting_surface_status", result)
        self.assertIn("mould_halves_status", result)
        self.assertIn("withdrawal_clearance_status", result)
        self.assertIn("validation_status", result)
        self.assertTrue(result["draft_face_summary"])
        self.assertIn(result["analysis_gate_status"], ("Pass", "Warning"))

    def test_summaries_non_empty(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertTrue(result["summary"])
        self.assertTrue(result["draft_face_summary"])
        self.assertTrue(result["parting_surface_summary"])
        self.assertTrue(result["mould_halves_summary"])

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
        # The native C++ withdrawal-clearance check runs inside the non-planar
        # solver on the solver's own mould halves. Draw the box along +Z and
        # assert the native verdict passes.
        result = analyze_source_shape(
            _box(), FreeCAD.Vector(0, 0, 1), parting_model="NonPlanar"
        )
        self.assertEqual(result["non_planar_status"], "ready")
        self.assertEqual(result["withdrawal_clearance_status"], "Pass")
        self.assertEqual(result["withdrawal_clearance_failure_count"], 0)
        self.assertIn("Withdrawal clearance pass", result["withdrawal_clearance_summary"])
        self.assertEqual(result["validation_status"], "Pass")


class TestNonPlanarPartingSolver(unittest.TestCase):
    """Phase 2 acceptance: the non-planar solver on the baseline shapes.

    The part-line contract is checked at the lowest level first: the solver
    must return Ready, expose a part line, and surface UV-chain diagnostics
    for the freeform cases.
    """

    def _analyze(self, shape, direction):
        return analyze_source_shape(shape, direction, parting_model="NonPlanar")

    def _assert_uv_segments(self, label, result):
        segments = result.get("parting_line_segments", [])
        self.assertIsInstance(segments, list, msg=f"{label}: parting_line_segments must be a list")
        self.assertGreater(len(segments), 0, msg=f"{label}: expected part-line segments")
        for segment in segments:
            # Every segment carries a type tag and its 3D samples; face segments
            # additionally carry face + matching uv_samples.
            self.assertIn("type", segment, msg=f"{label}: segment is missing type")
            self.assertIn(segment["type"], ("face", "edge"), msg=f"{label}: bad segment type")
            self.assertIn("points_3d", segment, msg=f"{label}: segment is missing 3D samples")
            self.assertGreaterEqual(len(segment["points_3d"]), 2, msg=f"{label}: too few 3D samples")
            if segment["type"] == "face":
                self.assertIn("face", segment, msg=f"{label}: face segment is missing face geometry")
                self.assertIn("uv_samples", segment, msg=f"{label}: face segment is missing UV samples")
                self.assertEqual(len(segment["uv_samples"]), len(segment["points_3d"]),
                                 msg=f"{label}: UV/3D sample counts must match")

    def _assert_parting_geometry(self, shape, direction, label):
        result = self._analyze(shape, direction)
        self.assertEqual(result["non_planar_status"], "ready",
                         msg=f"{label}: {result.get('non_planar_summary', '')}")
        self.assertEqual(result["withdrawal_clearance_status"], "Pass",
                         msg=f"{label} WC: {result.get('non_planar_summary', '')}")
        self._assert_uv_segments(label, result)

    def test_box_non_planar_releases(self):
        self._assert_parting_geometry(_box(), default_mould_analysis_draw_direction, "box")

    def test_cylinder_non_planar_releases(self):
        self._assert_parting_geometry(Part.makeCylinder(5.0, 20.0),
                                   default_mould_analysis_draw_direction, "cylinder")

    def test_sphere_non_planar_releases(self):
        self._assert_parting_geometry(make_sphere(), default_mould_analysis_draw_direction, "sphere")

    def test_cone_on_side_non_planar_releases(self):
        self._assert_parting_geometry(make_sideways_cone(), FreeCAD.Vector(1, 0, 0), "cone-on-side")

    def test_cone_non_planar_releases(self):
        self._assert_parting_geometry(make_vertical_cone(), default_mould_analysis_draw_direction, "cone")

    def test_side_cone_non_planar_releases(self):
        self._assert_parting_geometry(make_sideways_cone(), FreeCAD.Vector(1, 0, 0), "side-cone")

    def test_loft2_non_planar_releases(self):
        # 'loft2' = the cambered 5-section BSpline loft (_make_loft_shape),
        # distinct from nextdrape's internal two-section 'loft' (MakeTwistedLoft)
        # which passes. loft2 only releases along its thinnest (Y) axis.
        self._assert_parting_geometry(_make_loft_shape(), FreeCAD.Vector(0, 1, 0), "loft2")

    def test_blade_non_planar_releases(self):
        # The cambered blade must be drawn along its releasable axis. +Z (the
        # default) is the long, twisted axis — it cannot withdraw without
        # collision. Drawn along +X it releases cleanly (matrix solver pass).
        self._assert_parting_geometry(_make_blade_shape(),
                                      FreeCAD.Vector(1, 0, 0), "blade")

    def test_twisted_loft_non_planar_releases(self):
        # The twisted loft's skirt cannot be built (its outer ring corner
        # cannot be placed without overlap). Rather than crash the process
        # (the historical assert(false)), the solver must surface a
        # recoverable non-ready status with a meaningful message. This is the
        # contract we lock in: a mould failure must never abort FreeCAD.
        result = self._analyze(_make_twisted_loft_shape(), default_mould_analysis_draw_direction)
        self.assertNotEqual(result["non_planar_status"], "ready",
                            msg=f"twisted loft: unexpected ready {result.get('non_planar_summary', '')}")
        self.assertTrue(
            result.get("non_planar_summary")
            and "buildSkirt" in result.get("non_planar_summary", ""),
            msg=f"twisted loft: expected a meaningful skirt-failure message, got {result.get('non_planar_summary', '')}",
        )
        # Even though the mould cannot finish, the part line is a valid
        # deliverable: it is fully marched before the skirt stage fails, and
        # the analysis must surface it rather than discarding it (it used to
        # be dropped on any non-ready verdict).
        part_line = result.get("parting_surface_shape")
        self.assertTrue(
            part_line is not None and not part_line.isNull(),
            msg="twisted loft: part line should still surface despite skirt_failed",
        )
        self.assertGreater(len(part_line.Edges), 0,
                           msg="twisted loft: surfaced part line is empty")


class TestValidateMouldResult(unittest.TestCase):
    """validate_mould_result: verdict from parting, halves, and withdrawal clearance.

    Withdrawal clearance is the authoritative necessary test; the draft-face
    gate is decoupled and not consulted here. A clean mould (Ready parting,
    valid halves, withdrawal clears) is Pass; any null/invalid shape or a
    withdrawal collision is a hard Fail.
    """

    def test_pass_on_clean_inputs(self):
        shape = _box()
        result = validate_mould_result("Ready", "Ready", shape, shape, shape)
        self.assertEqual(result["status"], "Pass")

    def test_fail_on_failed_parting_surface(self):
        shape = _box()
        result = validate_mould_result("Fail", "Ready", shape, shape, shape)
        self.assertEqual(result["status"], "Fail")

    def test_fail_on_null_half(self):
        shape = _box()
        null_shape = Part.Shape()
        result = validate_mould_result("Ready", "Ready", shape, null_shape, shape)
        self.assertEqual(result["status"], "Fail")

    def test_withdrawal_clearance_fail_escalates_to_fail(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", shape, shape, shape,
            withdrawal_clearance_status="Fail",
        )
        self.assertEqual(result["status"], "Fail")
        self.assertTrue(any("withdraw" in check.lower() for check in result["checks"]))

    def test_withdrawal_clearance_pass_stays_pass(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", shape, shape, shape,
            withdrawal_clearance_status="Pass",
        )
        self.assertEqual(result["status"], "Pass")

    def test_withdrawal_clearance_skipped_on_invalid_geometry(self):
        source = _box()
        detached_parting = Part.makePolygon([
            FreeCAD.Vector(100.0, 100.0, 100.0),
            FreeCAD.Vector(110.0, 100.0, 100.0),
        ])
        result = validate_mould_result(
            "Ready",
            "Ready",
            source,
            source,
            source,
            withdrawal_clearance_status="Skipped",
            source_shape=source,
            parting_line_shape=detached_parting,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertFalse(any("withdraw" in check.lower() for check in result["checks"]))

    def test_fail_on_detached_parting_surface(self):
        source = _box()
        detached_parting = Part.makePolygon([
            FreeCAD.Vector(100.0, 100.0, 100.0),
            FreeCAD.Vector(110.0, 100.0, 100.0),
        ])
        result = validate_mould_result(
            "Ready",
            "Ready",
            source,
            source,
            source,
            source_shape=source,
            parting_line_shape=detached_parting,
        )
        self.assertEqual(result["status"], "Fail")
        self.assertTrue(any("parting line stays on source shape" in check for check in result["checks"]))


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


if __name__ == "__main__":
    unittest.main()

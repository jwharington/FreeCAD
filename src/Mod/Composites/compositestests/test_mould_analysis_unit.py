# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Pure-Python unit tests for mould_analysis.py helper functions.

These target the deterministic logic in tools/mould_analysis.py (score
breakdown, overlay grouping, decomposition planning, split-offset derivation,
normalization hints) without constructing any Part geometry. They run
headless under FreeCADCmd (the module imports FreeCAD/Part at load time,
but the helpers under test take plain dicts/scalars).
"""

import unittest

from Composites.tools.mould_analysis import (
    DECOMPOSITION_PLAN_STATUS_CONSIDER_MULTIPART,
    DECOMPOSITION_PLAN_STATUS_MULTIPART_REQUIRED,
    DECOMPOSITION_PLAN_STATUS_NOT_APPLICABLE,
    DECOMPOSITION_PLAN_STATUS_NOT_REQUIRED,
    MANUFACTURABILITY_BACKFACE_SATURATION_RATIO,
    MANUFACTURABILITY_CALIBRATION_WEIGHTS,
    MANUFACTURABILITY_DRAFT_SATURATION_COUNT,
    MANUFACTURABILITY_GROUP_DENSITY_SATURATION_COUNT,
    MANUFACTURABILITY_MULTIPART_SATURATION_COUNT,
    MANUFACTURABILITY_UNDERCUT_SATURATION_COUNT,
    MAX_MULTIPART_EXTRA_SPLITS,
    NORMALIZATION_CONFIDENCE_EXACT,
    NORMALIZATION_CONFIDENCE_FAIL,
    _decomposition_plan_candidates,
    _decomposition_plan_status,
    _extract_normalization_hints,
    _manufacturability_calibration_weights,
    _manufacturability_overlay_bands,
    _manufacturability_overlay_groups,
    _manufacturability_risk_class,
    _manufacturability_score_breakdown,
    _multipart_offset_sets,
    _quantity_to_mm,
    _region_interval,
    _select_best_multipart_attempt,
    _split_offsets_from_violations,
)


def _attempt(status="Pass", baseline_violations=10, piece_violations=2,
             volume=100.0, depth=1, offset=5.0, baseline_offset=0.0):
    """Build a multipart attempt dict in the shape _select_best expects."""
    return {
        "status": status,
        "baseline_violation_count": baseline_violations,
        "piece_violation_count": piece_violations,
        "total_piece_volume": volume,
        "split_depth": depth,
        "split_offset": offset,
        "baseline_offset": baseline_offset,
    }


class TestManufacturabilityScoreBreakdown(unittest.TestCase):
    """_manufacturability_score_breakdown: components, saturation, weights."""

    def test_zero_inputs_yield_zero_total(self):
        b = _manufacturability_score_breakdown(0.0, 0, 0, 0, 0)
        self.assertEqual(b["total"], 0.0)
        for component in ("draft_component", "undercut_component",
                          "backface_component", "multipart_component",
                          "group_density_component"):
            self.assertEqual(b[component], 0.0)

    def test_total_in_unit_interval(self):
        for draft in (0, 1, 5, 100):
            for undercut in (0, 3, 50):
                b = _manufacturability_score_breakdown(0.5, undercut, draft, 4, 3)
                self.assertGreaterEqual(b["total"], 0.0)
                self.assertLessEqual(b["total"], 1.0)

    def test_each_component_saturates_at_one(self):
        # draft saturates at MANUFACTURABILITY_DRAFT_SATURATION_COUNT
        b = _manufacturability_score_breakdown(
            0.0, 0, int(MANUFACTURABILITY_DRAFT_SATURATION_COUNT) + 10, 0, 0,
        )
        self.assertEqual(b["draft_component"], 1.0)
        # undercut saturates
        b = _manufacturability_score_breakdown(
            0.0, int(MANUFACTURABILITY_UNDERCUT_SATURATION_COUNT) + 10, 0, 0, 0,
        )
        self.assertEqual(b["undercut_component"], 1.0)
        # backface saturates (ratio > saturation_ratio)
        b = _manufacturability_score_breakdown(1.0, 0, 0, 0, 0)
        self.assertEqual(b["backface_component"], 1.0)
        # multipart saturates (excess pieces beyond 2)
        b = _manufacturability_score_breakdown(
            0.0, 0, 0,
            2 + int(MANUFACTURABILITY_MULTIPART_SATURATION_COUNT) + 10, 0,
        )
        self.assertEqual(b["multipart_component"], 1.0)
        # group density saturates
        b = _manufacturability_score_breakdown(
            0.0, 0, 0, 0,
            int(MANUFACTURABILITY_GROUP_DENSITY_SATURATION_COUNT) + 10,
        )
        self.assertEqual(b["group_density_component"], 1.0)

    def test_monotonic_in_each_component(self):
        base = _manufacturability_score_breakdown(0.0, 0, 0, 0, 0)
        more_draft = _manufacturability_score_breakdown(0.0, 0, 3, 0, 0)
        self.assertGreater(more_draft["draft_component"], base["draft_component"])
        self.assertGreaterEqual(more_draft["total"], base["total"])

    def test_calibration_weights_normalize_to_one(self):
        weights = _manufacturability_calibration_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)

    def test_custom_weights_used(self):
        # All weight on draft -> total == draft_component
        weights = {k: 0.0 for k in MANUFACTURABILITY_CALIBRATION_WEIGHTS}
        weights["draft_weight"] = 1.0
        b = _manufacturability_score_breakdown(0.0, 0, 3, 0, 0,
                                               calibration_weights=weights)
        self.assertAlmostEqual(b["total"], b["draft_component"], places=6)

    def test_zero_weights_yield_zero_total(self):
        weights = {k: 0.0 for k in MANUFACTURABILITY_CALIBRATION_WEIGHTS}
        b = _manufacturability_score_breakdown(1.0, 10, 10, 10, 10,
                                               calibration_weights=weights)
        self.assertEqual(b["total"], 0.0)


class TestManufacturabilityRiskClass(unittest.TestCase):
    """_manufacturability_risk_class: boundary thresholds."""

    def test_low_below_medium_threshold(self):
        self.assertEqual(_manufacturability_risk_class(0.0), "low")
        self.assertEqual(_manufacturability_risk_class(0.33), "low")

    def test_medium_at_and_above_threshold(self):
        self.assertEqual(_manufacturability_risk_class(0.34), "medium")
        self.assertEqual(_manufacturability_risk_class(0.66), "medium")

    def test_high_at_and_above_threshold(self):
        self.assertEqual(_manufacturability_risk_class(0.67), "high")
        self.assertEqual(_manufacturability_risk_class(1.0), "high")

    def test_negative_clamps_to_low(self):
        self.assertEqual(_manufacturability_risk_class(-0.5), "low")


class TestRegionInterval(unittest.TestCase):
    """_region_interval: parses '[n] a->b' text."""

    def test_parses_valid_interval(self):
        self.assertEqual(_region_interval("[0] 1.5→3.5"), (1.5, 3.5))

    def test_swaps_reversed_interval(self):
        start, end = _region_interval("[1] 3.0→1.0")
        self.assertEqual(start, 1.0)
        self.assertEqual(end, 3.0)

    def test_negative_values(self):
        self.assertEqual(_region_interval("[2] -1.0→2.0"), (-1.0, 2.0))

    def test_unparseable_returns_none(self):
        self.assertIsNone(_region_interval("no interval here"))
        self.assertIsNone(_region_interval(""))
        self.assertIsNone(_region_interval(None))

    def test_parses_real_region_text_with_area_suffix(self):
        # Real regions from _format_violation_regions look like:
        #   "[1] 1.500→2.000 area 0.000→0.500"
        self.assertEqual(
            _region_interval("[1] 1.500→2.000 area 0.000→0.500"),
            (1.5, 2.0),
        )


class TestManufacturabilityOverlayBands(unittest.TestCase):
    """_manufacturability_overlay_bands: region text -> band dicts."""

    def test_empty_inputs(self):
        self.assertEqual(_manufacturability_overlay_bands([], []), [])

    def test_parses_undercut_and_draft(self):
        bands = _manufacturability_overlay_bands(
            ["[0] 1.0→2.0"],
            ["[1] 5.0→6.0"],
        )
        self.assertEqual(len(bands), 2)
        kinds = sorted(b["kind"] for b in bands)
        self.assertEqual(kinds, ["draft_violation", "undercut"])
        for band in bands:
            self.assertIn("start", band)
            self.assertIn("end", band)
            self.assertIn("label", band)

    def test_ignores_unparseable_regions(self):
        bands = _manufacturability_overlay_bands(["garbage", "[0] 1.0→2.0"], [])
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0]["kind"], "undercut")


class TestManufacturabilityOverlayGroups(unittest.TestCase):
    """_manufacturability_overlay_groups: clustering by kind + proximity."""

    def test_empty_bands(self):
        self.assertEqual(_manufacturability_overlay_groups([]), [])

    def test_adjacent_same_kind_bands_cluster(self):
        bands = [
            {"kind": "undercut", "start": 1.0, "end": 2.0, "label": "[0] 1.0->2.0"},
            {"kind": "undercut", "start": 2.0, "end": 3.0, "label": "[1] 2.0->3.0"},
        ]
        groups = _manufacturability_overlay_groups(bands)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["band_count"], 2)
        self.assertEqual(groups[0]["start"], 1.0)
        self.assertEqual(groups[0]["end"], 3.0)

    def test_different_kinds_do_not_cluster(self):
        bands = [
            {"kind": "undercut", "start": 1.0, "end": 2.0, "label": "u"},
            {"kind": "draft_violation", "start": 1.0, "end": 2.0, "label": "d"},
        ]
        groups = _manufacturability_overlay_groups(bands)
        self.assertEqual(len(groups), 2)

    def test_group_has_severity_tier(self):
        bands = [{"kind": "undercut", "start": 0.0, "end": 20.0,
                  "label": "big"}]
        groups = _manufacturability_overlay_groups(bands)
        self.assertIn(groups[0]["severity_tier"], ("low", "medium", "high"))

    def test_labels_deduped(self):
        bands = [
            {"kind": "undercut", "start": 1.0, "end": 2.0, "label": "a"},
            {"kind": "undercut", "start": 2.0, "end": 3.0, "label": "a"},
        ]
        groups = _manufacturability_overlay_groups(bands)
        self.assertEqual(groups[0]["labels"], ["a"])


class TestDecompositionPlanStatus(unittest.TestCase):
    """_decomposition_plan_status: the full status matrix."""

    def test_waiting_for_source_is_not_applicable(self):
        self.assertEqual(
            _decomposition_plan_status("Waiting for source", "Pass"),
            DECOMPOSITION_PLAN_STATUS_NOT_APPLICABLE,
        )
        self.assertEqual(
            _decomposition_plan_status("Ready", "Waiting for source"),
            DECOMPOSITION_PLAN_STATUS_NOT_APPLICABLE,
        )

    def test_fail_is_multipart_required(self):
        self.assertEqual(
            _decomposition_plan_status("Fail", "Pass"),
            DECOMPOSITION_PLAN_STATUS_MULTIPART_REQUIRED,
        )
        self.assertEqual(
            _decomposition_plan_status("Ready", "Fail"),
            DECOMPOSITION_PLAN_STATUS_MULTIPART_REQUIRED,
        )

    def test_warning_is_consider_multipart(self):
        self.assertEqual(
            _decomposition_plan_status("Warning", "Pass"),
            DECOMPOSITION_PLAN_STATUS_CONSIDER_MULTIPART,
        )

    def test_ready_pass_is_not_required(self):
        self.assertEqual(
            _decomposition_plan_status("Ready", "Pass"),
            DECOMPOSITION_PLAN_STATUS_NOT_REQUIRED,
        )

    def test_other_combos_default_to_consider(self):
        self.assertEqual(
            _decomposition_plan_status("Ready", "Warning"),
            DECOMPOSITION_PLAN_STATUS_CONSIDER_MULTIPART,
        )


class TestDecompositionPlanCandidates(unittest.TestCase):
    """_decomposition_plan_candidates: candidate set per status + counts."""

    def test_not_applicable_yields_empty(self):
        self.assertEqual(
            _decomposition_plan_candidates(
                DECOMPOSITION_PLAN_STATUS_NOT_APPLICABLE, 5, 5,
            ),
            [],
        )

    def test_not_required_yields_empty(self):
        self.assertEqual(
            _decomposition_plan_candidates(
                DECOMPOSITION_PLAN_STATUS_NOT_REQUIRED, 0, 0,
            ),
            [],
        )

    def test_required_emits_baseline_required(self):
        c = _decomposition_plan_candidates(
            DECOMPOSITION_PLAN_STATUS_MULTIPART_REQUIRED, 0, 0,
        )
        self.assertIn("multipart_baseline_required", c)
        self.assertIn("split_for_validation_recovery", c)

    def test_consider_emits_baseline_optional(self):
        c = _decomposition_plan_candidates(
            DECOMPOSITION_PLAN_STATUS_CONSIDER_MULTIPART, 0, 0,
        )
        self.assertIn("multipart_baseline_optional", c)

    def test_undercut_adds_relief_candidate(self):
        c = _decomposition_plan_candidates(
            DECOMPOSITION_PLAN_STATUS_CONSIDER_MULTIPART, 1, 0,
        )
        self.assertIn("split_for_undercut_relief", c)
        self.assertNotIn("split_for_validation_recovery", c)

    def test_draft_adds_relief_candidate(self):
        c = _decomposition_plan_candidates(
            DECOMPOSITION_PLAN_STATUS_CONSIDER_MULTIPART, 0, 1,
        )
        self.assertIn("split_for_draft_relief", c)


class TestSplitOffsetsFromViolations(unittest.TestCase):
    """_split_offsets_from_violations: midpoint derivation + clamping."""

    def _viol(self, start, end):
        return [{"start_position": start, "end_position": end}]

    def test_midpoint_within_bounds(self):
        offsets = _split_offsets_from_violations(
            self._viol(2.0, 4.0), 0.0, 10.0, 0.0,
        )
        self.assertEqual(len(offsets), 1)
        self.assertAlmostEqual(offsets[0], 3.0, places=6)

    def test_skips_baseline_offset(self):
        # midpoint == baseline -> skipped
        offsets = _split_offsets_from_violations(
            self._viol(0.0, 0.0), 0.0, 10.0, 0.0,
        )
        self.assertEqual(offsets, [])

    def test_clamps_to_axis_bounds(self):
        # midpoint above axis_max -> clamped to axis_max - eps
        offsets = _split_offsets_from_violations(
            self._viol(0.0, 100.0), 0.0, 10.0, 0.0,
        )
        self.assertEqual(len(offsets), 1)
        self.assertLess(offsets[0], 10.0)
        self.assertGreater(offsets[0], 9.0)

    def test_dedupes_near_equal_midpoints(self):
        offsets = _split_offsets_from_violations(
            self._viol(2.0, 4.0) + self._viol(2.0, 4.0), 0.0, 10.0, 0.0,
        )
        self.assertEqual(len(offsets), 1)

    def test_respects_max_extra_splits(self):
        violations = [
            {"start_position": float(i), "end_position": float(i) + 1.0}
            for i in range(0, 20, 2)
        ]
        offsets = _split_offsets_from_violations(
            violations, 0.0, 100.0, 50.0,
        )
        self.assertLessEqual(len(offsets), MAX_MULTIPART_EXTRA_SPLITS)

    def test_empty_violations(self):
        self.assertEqual(
            _split_offsets_from_violations([], 0.0, 10.0, 0.0),
            [],
        )


class TestMultipartOffsetSets(unittest.TestCase):
    """_multipart_offset_sets: depth-1 and depth-2 sets."""

    def test_empty_yields_empty(self):
        self.assertEqual(_multipart_offset_sets([]), [])

    def test_single_offset_yields_depth_one(self):
        sets = _multipart_offset_sets([5.0])
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0], [5.0])

    def test_two_offsets_yields_depth_one_and_two(self):
        sets = _multipart_offset_sets([5.0, 15.0])
        self.assertEqual(len(sets), 2)
        self.assertEqual(sets[0], [5.0])
        self.assertEqual(sets[1], [5.0, 15.0])

    def test_max_depth_one_suppresses_depth_two(self):
        sets = _multipart_offset_sets([5.0, 15.0], max_depth=1)
        self.assertEqual(len(sets), 1)


class TestSelectBestMultipartAttempt(unittest.TestCase):
    """_select_best_multipart_attempt: ranking tuple."""

    def test_empty_returns_none(self):
        self.assertIsNone(_select_best_multipart_attempt([]))

    def test_pass_beats_warning_beats_fail(self):
        fail = _attempt(status="Fail")
        warn = _attempt(status="Warning")
        ok = _attempt(status="Pass")
        best = _select_best_multipart_attempt([fail, warn, ok])
        self.assertEqual(best["status"], "Pass")

    def test_greater_violation_reduction_wins_on_tie(self):
        # same status, but attempt_b reduces more violations
        attempt_a = _attempt(status="Pass", baseline_violations=10,
                             piece_violations=8)  # reduction 2
        attempt_b = _attempt(status="Pass", baseline_violations=10,
                             piece_violations=3)  # reduction 7
        best = _select_best_multipart_attempt([attempt_a, attempt_b])
        self.assertEqual(best["piece_violation_count"], 3)

    def test_higher_volume_wins_on_further_tie(self):
        a = _attempt(status="Pass", baseline_violations=10,
                     piece_violations=5, volume=50.0)
        b = _attempt(status="Pass", baseline_violations=10,
                     piece_violations=5, volume=120.0)
        best = _select_best_multipart_attempt([a, b])
        self.assertEqual(best["total_piece_volume"], 120.0)


class TestQuantityToMm(unittest.TestCase):
    """_quantity_to_mm: FreeCAD Quantity / raw value extraction."""

    def test_none_returns_none(self):
        self.assertIsNone(_quantity_to_mm(None))

    def test_raw_float(self):
        self.assertEqual(_quantity_to_mm(12.5), 12.5)

    def test_raw_int(self):
        self.assertEqual(_quantity_to_mm(7), 7.0)

    def test_object_with_value_attribute(self):
        class Q:
            Value = 42.0
        self.assertEqual(_quantity_to_mm(Q()), 42.0)

    def test_unparseable_returns_none(self):
        self.assertIsNone(_quantity_to_mm("not a number"))


class TestExtractNormalizationHints(unittest.TestCase):
    """_extract_normalization_hints: thickness + laminate detection."""

    def test_none_source(self):
        hints = _extract_normalization_hints(None)
        self.assertEqual(hints["thickness_hint_state"], "missing")
        self.assertFalse(hints["has_laminate"])

    def test_valid_thickness(self):
        class Q:
            Value = 2.5
        class Source:
            Name = "src"
            Thickness = Q()
        hints = _extract_normalization_hints(Source())
        self.assertEqual(hints["thickness_hint_state"], "valid")
        self.assertAlmostEqual(hints["thickness_mm"], 2.5)
        self.assertEqual(hints["thickness_hint_source"], "Thickness")

    def test_non_positive_thickness_is_invalid(self):
        class Q:
            Value = 0.0
        class Source:
            Name = "src"
            Thickness = Q()
        hints = _extract_normalization_hints(Source())
        self.assertEqual(hints["thickness_hint_state"], "invalid_non_positive")

    def test_laminate_detected_via_attribute(self):
        class Lam:
            Proxy = type("P", (), {"Type": "Composite::Laminate"})()
        class Source:
            Name = "src"
            Laminate = Lam()
        hints = _extract_normalization_hints(Source())
        self.assertTrue(hints["has_laminate"])

    def test_falls_back_through_candidate_props(self):
        class Q:
            Value = 1.8
        class Source:
            Name = "src"
            ShellThickness = Q()  # later in the candidate list
        hints = _extract_normalization_hints(Source())
        self.assertEqual(hints["thickness_hint_state"], "valid")
        self.assertEqual(hints["thickness_hint_source"], "ShellThickness")


if __name__ == "__main__":
    unittest.main()

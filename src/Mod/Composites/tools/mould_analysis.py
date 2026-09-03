# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import math
import re

from FreeCAD import Vector
import Part


default_mould_analysis_draw_direction = Vector(0, 0, 1)

NORMALIZATION_CONFIDENCE_EXACT = "exact"
NORMALIZATION_CONFIDENCE_APPROXIMATE = "approximate"
NORMALIZATION_CONFIDENCE_FAIL = "fail"

GEOMETRY_BACKFACE_WEIGHT = 0.25
DRAFT_FACE_ALIGNMENT_MARGIN = 0.25
MAX_SPLIT_STRATEGIES = 2
WITHDRAWAL_CLEARANCE_STEP_MM = 0.1
PARTING_LINE_ATTACHMENT_TOLERANCE_MM = 1.0e-2
PARTING_LINE_ATTACHMENT_SAMPLES = 8


def _safe_copy_shape(shape):
    try:
        return shape.copy()
    except Exception:
        return shape


def _bbox_proxy_solid(shape, padding_hint_mm=None):
    bbox = shape.BoundBox
    min_size = 1.0e-3
    dx = max(float(getattr(bbox, "XLength", 0.0)), min_size)
    dy = max(float(getattr(bbox, "YLength", 0.0)), min_size)
    dz = max(float(getattr(bbox, "ZLength", 0.0)), min_size)
    px = max(dx * 0.05, min_size)
    py = max(dy * 0.05, min_size)
    pz = max(dz * 0.05, min_size)

    if padding_hint_mm is not None:
        pad_hint = max(float(padding_hint_mm), min_size)
        px = max(px, pad_hint)
        py = max(py, pad_hint)
        pz = max(pz, pad_hint)

    return Part.makeBox(
        dx + (2.0 * px),
        dy + (2.0 * py),
        dz + (2.0 * pz),
        Vector(bbox.XMin - px, bbox.YMin - py, bbox.ZMin - pz),
    )


def _quantity_to_mm(value):
    if value is None:
        return None

    if hasattr(value, "getValueAs"):
        try:
            converted = value.getValueAs("mm")
            if hasattr(converted, "Value"):
                return float(converted.Value)
            return float(converted)
        except Exception:
            pass

    if hasattr(value, "Value"):
        try:
            return float(value.Value)
        except Exception:
            pass

    try:
        return float(value)
    except Exception:
        return None


def _extract_normalization_hints(source_obj):
    hints = {
        "source_name": "",
        "thickness_mm": None,
        "thickness_hint_state": "missing",
        "thickness_hint_source": "",
        "thickness_invalid_detail": "",
        "has_laminate": False,
        "laminate_type": "",
    }
    if source_obj is None:
        return hints

    hints["source_name"] = str(getattr(source_obj, "Name", "") or "")

    invalid_state = None
    invalid_detail = ""
    for prop_name in (
        "Thickness",
        "thickness",
        "ShellThickness",
        "LaminateThickness",
    ):
        if not hasattr(source_obj, prop_name):
            continue
        thickness_value = getattr(source_obj, prop_name, None)
        thickness_mm = _quantity_to_mm(thickness_value)
        if thickness_mm is None:
            if invalid_state is None:
                invalid_state = "invalid_non_numeric"
                invalid_detail = prop_name
            continue
        if not math.isfinite(thickness_mm):
            if invalid_state is None:
                invalid_state = "invalid_non_numeric"
                invalid_detail = prop_name
            continue
        if thickness_mm <= 0.0:
            if invalid_state is None:
                invalid_state = "invalid_non_positive"
                invalid_detail = prop_name
            continue

        hints["thickness_mm"] = thickness_mm
        hints["thickness_hint_state"] = "valid"
        hints["thickness_hint_source"] = prop_name
        break

    if hints["thickness_hint_state"] != "valid" and invalid_state is not None:
        hints["thickness_hint_state"] = invalid_state
        hints["thickness_invalid_detail"] = invalid_detail

    for prop_name in ("Laminate", "LaminateRef", "Layup", "Stack"):
        if not hasattr(source_obj, prop_name):
            continue
        laminate_obj = getattr(source_obj, prop_name, None)
        if laminate_obj is None:
            continue
        hints["has_laminate"] = True
        hints["laminate_type"] = (
            getattr(getattr(laminate_obj, "Proxy", None), "Type", "")
            or getattr(laminate_obj, "TypeId", "")
            or type(laminate_obj).__name__
        )
        break

    if not hints["has_laminate"]:
        proxy_type = str(getattr(getattr(source_obj, "Proxy", None), "Type", "") or "")
        if "Laminate" in proxy_type:
            hints["has_laminate"] = True
            hints["laminate_type"] = proxy_type

    return hints


def _normalization_hint_reason_flags(hints):
    flags = []
    thickness_state = hints.get("thickness_hint_state", "missing")
    if thickness_state == "valid":
        flags.append("hint_thickness_present")
    elif thickness_state == "invalid_non_positive":
        flags.append("hint_thickness_invalid_non_positive")
    elif thickness_state == "invalid_non_numeric":
        flags.append("hint_thickness_invalid_non_numeric")

    if hints.get("has_laminate"):
        flags.append("hint_laminate_present")
    return flags


def _normalization_hint_summary(hints):
    thickness_state = hints.get("thickness_hint_state", "missing")
    thickness_mm = hints.get("thickness_mm")

    if thickness_state == "valid" and thickness_mm is not None:
        thickness_source = hints.get("thickness_hint_source") or "unknown"
        thickness_summary = (
            f"thickness_hint=valid({thickness_mm:.3f} mm via {thickness_source})"
        )
    elif thickness_state == "invalid_non_positive":
        detail = hints.get("thickness_invalid_detail") or "unknown"
        thickness_summary = f"thickness_hint=invalid_non_positive(via {detail})"
    elif thickness_state == "invalid_non_numeric":
        detail = hints.get("thickness_invalid_detail") or "unknown"
        thickness_summary = f"thickness_hint=invalid_non_numeric(via {detail})"
    else:
        thickness_summary = "thickness_hint=missing"

    if hints.get("has_laminate"):
        laminate_type = hints.get("laminate_type") or "unknown"
        laminate_summary = f"laminate_hint={laminate_type}"
    else:
        laminate_summary = "laminate_hint=none"

    return f"{thickness_summary}, {laminate_summary}"


def _dedupe_preserve_order(items):
    deduped = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        deduped.append(item)
        seen.add(item)
    return deduped


def _normalization_reason_flags(reason_flags, hint_flags):
    return _dedupe_preserve_order(list(reason_flags) + list(hint_flags))


def _format_vector(vec):
    return f"({vec.x:.3f}, {vec.y:.3f}, {vec.z:.3f})"


def _normalized(direction):
    length = getattr(direction, "Length", 0.0)
    if not length:
        return default_mould_analysis_draw_direction
    return Vector(direction.x / length, direction.y / length, direction.z / length)


def _extent_along_direction(bbox, direction):
    unit = _normalized(direction)
    return (
        abs(unit.x) * bbox.XLength
        + abs(unit.y) * bbox.YLength
        + abs(unit.z) * bbox.ZLength
    )


def _face_midpoint_normal(face):
    try:
        umin, umax, vmin, vmax = face.ParameterRange
        u = 0.5 * (umin + umax)
        v = 0.5 * (vmin + vmax)
        normal = face.normalAt(u, v)
    except Exception:
        return None

    length = getattr(normal, "Length", 0.0)
    if not length:
        return None
    return Vector(normal.x / length, normal.y / length, normal.z / length)


def _face_parameter_grid(umin, umax, vmin, vmax, samples_per_axis):
    """Uniform (u,v) sample grid over a face's parameter range."""
    count = max(1, int(samples_per_axis or 0))
    if count == 1:
        return [0.5 * (umin + umax)], [0.5 * (vmin + vmax)]
    u_values = [
        umin + ((umax - umin) * index / (count - 1))
        for index in range(count)
    ]
    v_values = [
        vmin + ((vmax - vmin) * index / (count - 1))
        for index in range(count)
    ]
    return u_values, v_values


def _sample_face_draft_alignment(face, direction, samples_per_axis=5):
    unit = _normalized(direction)
    midpoint_normal = _face_midpoint_normal(face)
    midpoint_direction_dot = None
    if midpoint_normal is not None:
        midpoint_direction_dot = _dot(midpoint_normal, unit)

    try:
        umin, umax, vmin, vmax = face.ParameterRange
    except Exception:
        return {
            "sample_count": 0,
            "midpoint_direction_dot": midpoint_direction_dot,
            "min_direction_dot": None,
            "max_direction_dot": None,
            "negative_sample_count": 0,
            "positive_sample_count": 0,
        }

    u_values, v_values = _face_parameter_grid(umin, umax, vmin, vmax, samples_per_axis)

    sample_count = 0
    negative_sample_count = 0
    positive_sample_count = 0
    min_direction_dot = None
    max_direction_dot = None

    for u in u_values:
        for v in v_values:
            try:
                normal = face.normalAt(u, v)
            except Exception:
                continue

            length = getattr(normal, "Length", 0.0)
            if not length:
                continue

            direction_vector = Vector(
                normal.x / length,
                normal.y / length,
                normal.z / length,
            )
            direction_dot = _dot(direction_vector, unit)
            sample_count += 1
            if direction_dot < 0.0:
                negative_sample_count += 1
            elif direction_dot > 0.0:
                positive_sample_count += 1

            if min_direction_dot is None or direction_dot < min_direction_dot:
                min_direction_dot = direction_dot
            if max_direction_dot is None or direction_dot > max_direction_dot:
                max_direction_dot = direction_dot

    return {
        "sample_count": sample_count,
        "midpoint_direction_dot": midpoint_direction_dot,
        "min_direction_dot": min_direction_dot,
        "max_direction_dot": max_direction_dot,
        "negative_sample_count": negative_sample_count,
        "positive_sample_count": positive_sample_count,
    }


def _whole_side_draft_envelope(
    shape,
    direction,
    samples_per_axis=5,
    parting_offset=None,
    max_samples_per_axis=32,
    stability_epsilon=1.0e-3,
):
    """Aggregate worst draft per side of the planar parting split.

    Each sample point is classified by its position relative to the parting
    offset along the draw direction, not by its face centre, so a face that
    spans the parting plane contributes to both sides. A side is releasable
    when its outward normals point with that side's withdrawal direction
    (+unit for the upper side, -unit for the lower side).

    ``parting_offset`` defaults to the bounding-box midpoint along the draw
    direction. Passing an explicit value probes off-centre parting planes, so
    a convex shape (e.g. a sphere) can be shown releasable on both sides only
    at its centre and on exactly one side elsewhere.

    Sampling is adaptive: a uniform parametric grid can step over a thin
    undercut band near the parting plane (a real false-negative, proven on an
    off-centre sphere). The grid is refined, doubling per-axis resolution,
    until each side's worst releasability stabilises within
    ``stability_epsilon`` or ``max_samples_per_axis`` is reached. A box's
    horizontal walls sit at exactly zero at every resolution, so they stabilise
    on the first pass and trigger no extra work.
    """
    unit = _normalized(direction)
    axis_min, axis_max = _projection_bounds(shape, unit)
    if parting_offset is None:
        parting_offset = 0.5 * (axis_min + axis_max)

    def _evaluate(resolution):
        upper_sample_count = 0
        lower_sample_count = 0
        upper_undercut_count = 0
        lower_undercut_count = 0
        skipped_sample_count = 0
        upper_worst_releasability = None
        lower_worst_releasability = None
        per_face = []

        for face_index, face in enumerate(getattr(shape, "Faces", []), start=1):
            try:
                umin, umax, vmin, vmax = face.ParameterRange
            except Exception:
                per_face.append(
                    {
                        "face_index": face_index,
                        "upper_sample_count": 0,
                        "lower_sample_count": 0,
                        "skipped_sample_count": 0,
                        "upper_undercut_count": 0,
                        "lower_undercut_count": 0,
                        "upper_worst_releasability": None,
                        "lower_worst_releasability": None,
                    }
                )
                continue
            u_values, v_values = _face_parameter_grid(
                umin, umax, vmin, vmax, resolution,
            )

            face_upper = 0
            face_lower = 0
            face_skipped = 0
            face_upper_undercut = 0
            face_lower_undercut = 0
            face_upper_worst = None
            face_lower_worst = None

            for u in u_values:
                for v in v_values:
                    try:
                        normal = face.normalAt(u, v)
                        point = face.valueAt(u, v)
                    except Exception:
                        face_skipped += 1
                        continue
                    length = getattr(normal, "Length", 0.0)
                    if not length:
                        face_skipped += 1
                        continue
                    normal_unit = Vector(
                        normal.x / length,
                        normal.y / length,
                        normal.z / length,
                    )
                    dot = _dot(normal_unit, unit)
                    axis_pos = (
                        point.x * unit.x + point.y * unit.y + point.z * unit.z
                    )

                    if axis_pos >= parting_offset:
                        upper_sample_count += 1
                        face_upper += 1
                        if dot < 0.0:
                            upper_undercut_count += 1
                            face_upper_undercut += 1
                        if face_upper_worst is None or dot < face_upper_worst:
                            face_upper_worst = dot
                    else:
                        lower_sample_count += 1
                        face_lower += 1
                        releasability = -dot
                        if dot > 0.0:
                            lower_undercut_count += 1
                            face_lower_undercut += 1
                        if (
                            face_lower_worst is None
                            or releasability < face_lower_worst
                        ):
                            face_lower_worst = releasability

            skipped_sample_count += face_skipped
            per_face.append(
                {
                    "face_index": face_index,
                    "upper_sample_count": face_upper,
                    "lower_sample_count": face_lower,
                    "skipped_sample_count": face_skipped,
                    "upper_undercut_count": face_upper_undercut,
                    "lower_undercut_count": face_lower_undercut,
                    "upper_worst_releasability": face_upper_worst,
                    "lower_worst_releasability": face_lower_worst,
                }
            )
            if face_upper_worst is not None and (
                upper_worst_releasability is None
                or face_upper_worst < upper_worst_releasability
            ):
                upper_worst_releasability = face_upper_worst
            if face_lower_worst is not None and (
                lower_worst_releasability is None
                or face_lower_worst < lower_worst_releasability
            ):
                lower_worst_releasability = face_lower_worst

        return {
            "upper_sample_count": upper_sample_count,
            "lower_sample_count": lower_sample_count,
            "upper_undercut_count": upper_undercut_count,
            "lower_undercut_count": lower_undercut_count,
            "skipped_sample_count": skipped_sample_count,
            "upper_worst_releasability": upper_worst_releasability,
            "lower_worst_releasability": lower_worst_releasability,
            "per_face": per_face,
        }

    def _stable(prev, cur):
        for key in ("upper_worst_releasability", "lower_worst_releasability"):
            before = prev[key]
            after = cur[key]
            if before is None and after is None:
                continue
            if before is None or after is None:
                return False
            if abs(after - before) > stability_epsilon:
                return False
        return True

    resolution = max(2, int(samples_per_axis or 0))
    cap = max(resolution, int(max_samples_per_axis or 0))
    refinement_trace = [resolution]
    current = _evaluate(resolution)
    while resolution < cap:
        next_resolution = min(resolution * 2, cap)
        refined = _evaluate(next_resolution)
        refinement_trace.append(next_resolution)
        if _stable(current, refined):
            current = refined
            break
        current = refined
        resolution = next_resolution

    upper_sample_count = current["upper_sample_count"]
    lower_sample_count = current["lower_sample_count"]
    upper_undercut_count = current["upper_undercut_count"]
    lower_undercut_count = current["lower_undercut_count"]
    skipped_sample_count = current["skipped_sample_count"]
    upper_worst_releasability = current["upper_worst_releasability"]
    lower_worst_releasability = current["lower_worst_releasability"]
    per_face = current["per_face"]

    upper_undercut_fraction = (
        upper_undercut_count / upper_sample_count if upper_sample_count else 0.0
    )
    lower_undercut_fraction = (
        lower_undercut_count / lower_sample_count if lower_sample_count else 0.0
    )

    globally_negative_sides = []
    if (
        upper_sample_count > 0
        and upper_worst_releasability is not None
        and upper_worst_releasability < 0.0
    ):
        globally_negative_sides.append("upper")
    if (
        lower_sample_count > 0
        and lower_worst_releasability is not None
        and lower_worst_releasability < 0.0
    ):
        globally_negative_sides.append("lower")

    if globally_negative_sides:
        status = "Fail"
        summary_prefix = "whole-side draft envelope fail"
    elif upper_undercut_count > 0 or lower_undercut_count > 0:
        status = "Warning"
        summary_prefix = "whole-side draft envelope warning"
    else:
        status = "Pass"
        summary_prefix = "whole-side draft envelope pass"

    summary = (
        f"{summary_prefix}; parting_offset={parting_offset:.3f}, "
        f"upper_samples={upper_sample_count}, upper_undercut={upper_undercut_count}, "
        f"upper_undercut_fraction={upper_undercut_fraction:.3f}, "
        f"lower_samples={lower_sample_count}, lower_undercut={lower_undercut_count}, "
        f"lower_undercut_fraction={lower_undercut_fraction:.3f}, "
        f"skipped_samples={skipped_sample_count}, "
        f"refinement_trace={refinement_trace}, "
        f"globally_negative_sides={globally_negative_sides or ['none']}"
    )

    return {
        "status": status,
        "summary": summary,
        "parting_offset": parting_offset,
        "upper_sample_count": upper_sample_count,
        "lower_sample_count": lower_sample_count,
        "upper_undercut_count": upper_undercut_count,
        "lower_undercut_count": lower_undercut_count,
        "upper_undercut_fraction": upper_undercut_fraction,
        "lower_undercut_fraction": lower_undercut_fraction,
        "skipped_sample_count": skipped_sample_count,
        "refinement_trace": refinement_trace,
        "upper_worst_releasability": upper_worst_releasability,
        "lower_worst_releasability": lower_worst_releasability,
        "globally_negative_sides": globally_negative_sides,
        "per_face": per_face,
    }


def _face_center_point(face):
    center = getattr(face, "CenterOfMass", None)
    if center is not None:
        return center

    bbox = getattr(face, "BoundBox", None)
    if bbox is None:
        return None

    return Vector(
        0.5 * (bbox.XMin + bbox.XMax),
        0.5 * (bbox.YMin + bbox.YMax),
        0.5 * (bbox.ZMin + bbox.ZMax),
    )


def _dot(a, b):
    return a.x * b.x + a.y * b.y + a.z * b.z


def _classify_draft_faces(shape, direction, alignment_margin=DRAFT_FACE_ALIGNMENT_MARGIN):
    unit = _normalized(direction)
    margin = max(0.0, float(alignment_margin or 0.0))

    safe_face_area = 0.0
    risky_face_area = 0.0
    ambiguous_face_area = 0.0
    safe_face_count = 0
    risky_face_count = 0
    ambiguous_face_count = 0
    face_classifications = []

    for index, face in enumerate(getattr(shape, "Faces", []), start=1):
        area = float(getattr(face, "Area", 0.0) or 0.0)
        if area <= 0.0:
            continue

        normal = _face_midpoint_normal(face)
        center = _face_center_point(face)
        axis_position = None if center is None else _dot(center, unit)
        dot = None if normal is None else _dot(normal, unit)

        if dot is None:
            classification = "ambiguous"
            classification_margin = None
            ambiguous_face_area += area
            ambiguous_face_count += 1
        elif dot >= margin:
            classification = "safe"
            classification_margin = dot - margin
            safe_face_area += area
            safe_face_count += 1
        elif dot <= -margin:
            classification = "risky"
            classification_margin = -margin - dot
            risky_face_area += area
            risky_face_count += 1
        else:
            classification = "ambiguous"
            classification_margin = margin - abs(dot)
            ambiguous_face_area += area
            ambiguous_face_count += 1

        face_classifications.append(
            {
                "face_index": index,
                "face_label": f"Face{index}",
                "area": area,
                "normal": normal,
                "axis_position": axis_position,
                "direction_dot": dot,
                "direction_alignment": None if dot is None else abs(dot),
                "classification": classification,
                "classification_margin": classification_margin,
            }
        )

    if risky_face_count > 0:
        status = "Fail"
        summary_prefix = "draft-face screening fail"
    elif ambiguous_face_count > 0:
        status = "Warning"
        summary_prefix = "draft-face screening warning"
    else:
        status = "Ready"
        summary_prefix = "draft-face screening ready"

    summary = (
        f"{summary_prefix}; safe_faces={safe_face_count}, risky_faces={risky_face_count}, "
        f"ambiguous_faces={ambiguous_face_count}, safe_area={safe_face_area:.3f}, "
        f"risky_area={risky_face_area:.3f}, ambiguous_area={ambiguous_face_area:.3f}, "
        f"alignment_margin={margin:.3f}"
    )

    return {
        "status": status,
        "summary": summary,
        "safe_face_area": safe_face_area,
        "risky_face_area": risky_face_area,
        "ambiguous_face_area": ambiguous_face_area,
        "safe_face_count": safe_face_count,
        "risky_face_count": risky_face_count,
        "ambiguous_face_count": ambiguous_face_count,
        "face_classifications": face_classifications,
    }


def _backface_area_ratio(shape, direction, epsilon=1.0e-9):
    unit = _normalized(direction)
    total_area = 0.0
    backface_area = 0.0

    for face in getattr(shape, "Faces", []):
        area = float(getattr(face, "Area", 0.0) or 0.0)
        if area <= 0.0:
            continue
        normal = _face_midpoint_normal(face)
        if normal is None:
            continue

        dot = _dot(normal, unit)
        total_area += area
        if dot < -epsilon:
            backface_area += area

    if total_area <= 0.0:
        return 0.0
    return max(0.0, min(1.0, backface_area / total_area))


def _direction_geometric_evidence_cache_key(
    direction,
    alignment_margin=DRAFT_FACE_ALIGNMENT_MARGIN,
):
    unit = _normalized(direction)
    return (
        round(unit.x, 9),
        round(unit.y, 9),
        round(unit.z, 9),
        round(float(alignment_margin or 0.0), 6),
    )


def _direction_geometric_evidence(
    shape,
    direction,
    alignment_margin=DRAFT_FACE_ALIGNMENT_MARGIN,
    cache=None,
):
    cache_key = _direction_geometric_evidence_cache_key(
        direction,
        alignment_margin=alignment_margin,
    )
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    draft_face_screening = _classify_draft_faces(
        shape,
        direction,
        alignment_margin=alignment_margin,
    )
    evidence = {
        "cache_key": cache_key,
        "direction": _normalized(direction),
        "draft_face_screening": draft_face_screening,
        "backface_ratio": _backface_area_ratio(shape, direction),
        "analysis_gate_status": _analysis_gate_status(draft_face_screening),
    }

    if cache is not None:
        cache[cache_key] = evidence
    return evidence


def _plan_split_strategies(ranked, limit=MAX_SPLIT_STRATEGIES):
    strategies = []
    for rank, item in enumerate(ranked[: max(0, int(limit))], start=1):
        strategies.append(
            {
                "strategy_id": f"axis_plane_r{rank}",
                "rank": rank,
                "direction": item["direction"],
                "direction_label": _format_vector(item["direction"]),
                "direction_score": item["normalized_score"],
                "backface_ratio": item["backface_ratio"],
                "geometry_factor": item["geometry_factor"],
                "geometric_evidence": item.get("geometric_evidence"),
                "draft_face_screening": item.get("draft_face_screening"),
                "analysis_gate_status": item.get("analysis_gate_status"),
                "parting_model": item.get("parting_model", "NonPlanar"),
                "parting_line_tolerance": item.get("parting_line_tolerance", 0.1),
                "parting_stock_margin_x": item.get("parting_stock_margin_x", 5.0),
                "parting_stock_margin_y": item.get("parting_stock_margin_y", 5.0),
                "parting_stock_margin_z": item.get("parting_stock_margin_z", 5.0),
                "parting_stock_footprint": item.get("parting_stock_footprint"),
                "part_line_only": item.get("part_line_only", False),
                "status": "planned",
                "reason": "top-ranked draw-direction strategy",
            }
        )
    return strategies


def _planner_score(strategy, status):
    status_rank = {
        "Pass": 3.0,
        "Warning": 2.0,
        "Fail": 1.0,
    }.get(status, 0.0)
    rank = float(strategy.get("rank", 0) or 0)
    direction_score = float(strategy.get("direction_score", 0.0) or 0.0)
    return (status_rank * 1000.0) + direction_score - (rank * 1.0e-3)


def _evaluate_split_strategy_attempt(shape, strategy):
    evidence = strategy.get("geometric_evidence")
    if evidence is None:
        evidence = _direction_geometric_evidence(shape, strategy["direction"])

    draft_face_screening = evidence["draft_face_screening"]
    analysis_gate_status = evidence.get("analysis_gate_status") or _analysis_gate_status(
        draft_face_screening
    )

    part_line_only = bool(strategy.get("part_line_only", False))
    non_planar_result = _propose_non_planar_parting(
        shape,
        strategy["direction"],
        part_line_tolerance=strategy.get("parting_line_tolerance", 0.1),
        stock_margin_x=strategy.get("parting_stock_margin_x", 5.0),
        stock_margin_y=strategy.get("parting_stock_margin_y", 5.0),
        stock_margin_z=strategy.get("parting_stock_margin_z", 5.0),
        stock_footprint=strategy.get("parting_stock_footprint"),
        part_line_only=part_line_only,
    )
    solver_ready = (
        non_planar_result is not None and non_planar_result["status"] == "ready"
    )
    if solver_ready:
        # Real non-planar solver path: the C++ solver returns the parting
        # line and both mould halves directly; the split is intrinsic to the
        # construction. Coerce any missing/null shape to an empty Part.Shape
        # so a None can never reach a Shape property downstream.
        part_line = non_planar_result.get("parting_surface")
        if part_line is None or getattr(part_line, "isNull", lambda: True)():
            part_line = Part.Shape()
        lower = non_planar_result.get("lower_shell")
        upper = non_planar_result.get("upper_shell")
        if lower is None or getattr(lower, "isNull", lambda: True)():
            lower = Part.Shape()
        if upper is None or getattr(upper, "isNull", lambda: True)():
            upper = Part.Shape()
        parting = {
            "status": "Ready",
            "summary": non_planar_result.get("summary", ""),
            "curve_summary": "Non-planar marching-equator parting line.",
            "shape": part_line,
            "surface_normal": strategy["direction"],
            "surface_offset": 0.0,
            "surface_area": 0.0,
        }
        mould_halves = {
            "status": "Ready",
            "summary": non_planar_result.get("summary", ""),
            "half_a_shape": lower,
            "half_b_shape": upper,
            "half_a_volume": _shape_volume(lower),
            "half_b_volume": _shape_volume(upper),
        }
        if part_line_only:
            # Part-line-only mode: the solver stops at AfterPartLine, so there
            # are no mould halves by design. Mark them so, and skip the mould
            # validations that would fail on the absent halves. Empty shapes
            # (not None) keep the Shape-property contract intact.
            mould_halves = {
                "status": "N/A",
                "summary": "Part-line only mode: mould halves not generated.",
                "half_a_shape": Part.Shape(),
                "half_b_shape": Part.Shape(),
                "half_a_volume": 0.0,
                "half_b_volume": 0.0,
            }
    else:
        # Non-ready or absent solver result (binding unavailable,
        # fork_degenerate, march_did_not_close, split/skirt failure, ...).
        # The planar fallback has been removed; everything must go through
        # the C++ non-planar solver. Surface the failure — but still carry
        # the part line the solver built before failing, when there is one.
        failing = non_planar_result or {}
        part_line = failing.get("parting_surface")
        if part_line is None or getattr(part_line, "isNull", lambda: True)():
            part_line = Part.Shape()
        failure_summary = failing.get(
            "summary", "C++ non-planar solver produced no result"
        )
        parting = {
            "status": "Fail",
            "summary": failure_summary,
            "curve_summary": "No parting surface generated by the non-planar solver.",
            "shape": part_line,
            "surface_normal": strategy["direction"],
            "surface_offset": 0.0,
            "surface_area": 0.0,
        }
        mould_halves = {
            "status": "Fail",
            "summary": failure_summary,
            "half_a_shape": Part.Shape(),
            "half_b_shape": Part.Shape(),
            "half_a_volume": 0.0,
            "half_b_volume": 0.0,
        }
    if part_line_only and non_planar_result is not None and non_planar_result.get("status") == "ready":
        # Part-line-only: the part line is the deliverable. Bypass the mould
        # validation / withdrawal clearance checks (they gate mould halves).
        status = "Ready" if parting.get("shape") is not None and not getattr(parting.get("shape"), "isNull", lambda: True)() else "Fail"
        return {
            "strategy": strategy,
            "draft_face_screening": draft_face_screening,
            "analysis_gate_status": analysis_gate_status,
            "geometric_evidence": evidence,
            "parting": parting,
            "mould_halves": mould_halves,
            "withdrawal_clearance": {
                "status": "N/A",
                "summary": "Part-line only: no withdrawal clearance check.",
                "sample_count": 0,
                "failure_count": 0,
                "failure_regions": [],
                "half_checks": [],
                "step_mm": 0.0,
            },
            "non_planar_result": non_planar_result,
            "validation": {
                "status": status,
                "summary": "Part-line only: parting line generated; mould halves N/A.",
                "checks": ["INFO: part-line only mode"],
                "reasons": [],
                "reason_codes": [],
            },
            "status": status,
            "reason": "part-line only candidate",
            "planner_score": _planner_score(strategy, status),
            "selection_reason": "",
            "exception": "",
        }
    essential_validation = validate_mould_result(
        parting["status"],
        mould_halves["status"],
        parting["shape"],
        mould_halves["half_a_shape"],
        mould_halves["half_b_shape"],
        source_shape=shape,
        parting_line_shape=(non_planar_result or {}).get("parting_line"),
    )
    # Prefer the native C++ withdrawal-clearance result (computed by the
    # solver at FullPipeline when the mould halves are valid).
    native_wc = (non_planar_result or {}).get("withdrawal_clearance")
    if native_wc and native_wc.get("status"):
        withdrawal_clearance = native_wc
    elif essential_validation["status"] == "Pass":
        withdrawal_clearance = {
            "status": "Unimplemented",
            "summary": "Native C++ withdrawal clearance result not available; pure-Python fallback removed.",
            "sample_count": 0,
            "failure_count": 0,
            "failure_regions": ["Withdrawal clearance: C++ result absent, Python fallback removed."],
            "half_checks": [],
            "step_mm": 0.0,
        }
    else:
        withdrawal_clearance = {
            "status": "Skipped",
            "summary": "Withdrawal clearance skipped because essential geometry validation failed.",
            "sample_count": 0,
            "failure_count": 0,
            "failure_regions": [],
            "half_checks": [],
            "step_mm": 0.0,
        }
    validation = validate_mould_result(
        parting["status"],
        mould_halves["status"],
        parting["shape"],
        mould_halves["half_a_shape"],
        mould_halves["half_b_shape"],
        withdrawal_clearance_status=withdrawal_clearance["status"],
        source_shape=shape,
        parting_line_shape=(non_planar_result or {}).get("parting_line"),
    )

    status = validation["status"]
    if status == "Pass":
        reason = "candidate passed validation"
    elif status == "Warning":
        reason = "candidate produced warning-grade validation"
    else:
        reason = "candidate failed validation"

    return {
        "strategy": strategy,
        "draft_face_screening": draft_face_screening,
        "analysis_gate_status": analysis_gate_status,
        "geometric_evidence": evidence,
        "parting": parting,
        "mould_halves": mould_halves,
        "withdrawal_clearance": withdrawal_clearance,
        "non_planar_result": non_planar_result,
        "validation": validation,
        "status": status,
        "reason": reason,
        "planner_score": _planner_score(strategy, status),
        "selection_reason": "",
        "exception": "",
    }


def _failed_attempt_from_exception(strategy, exc):
    message = str(exc) or exc.__class__.__name__
    status = "Fail"
    return {
        "strategy": strategy,
        "draft_face_screening": {
            "status": "Fail",
            "summary": "Draft face screening unavailable due to strategy exception.",
            "safe_face_area": 0.0,
            "risky_face_area": 0.0,
            "ambiguous_face_area": 0.0,
            "safe_face_count": 0,
            "risky_face_count": 0,
            "ambiguous_face_count": 0,
            "face_classifications": [],
        },
        "analysis_gate_status": "Fail",
        "parting": {
            "status": "Fail",
            "summary": "Parting surface generation failed due to strategy exception.",
            "curve_summary": "No parting curve generated due to strategy exception.",
            "shape": Part.Shape(),
            "surface_normal": _normalized(strategy["direction"]),
            "surface_offset": 0.0,
            "surface_area": 0.0,
        },
        "mould_halves": {
            "status": "Fail",
            "summary": "Mould half generation failed due to strategy exception.",
            "half_a_shape": Part.Shape(),
            "half_b_shape": Part.Shape(),
            "half_a_volume": 0.0,
            "half_b_volume": 0.0,
        },
        "withdrawal_clearance": {
            "status": "Fail",
            "summary": "Withdrawal clearance unavailable due to strategy exception.",
            "failure_count": 0,
        },
        "non_planar_result": None,
        "validation": {
            "status": "Fail",
            "summary": "Validation fail: strategy evaluation raised an exception.",
            "checks": [
                f"FAIL: split strategy attempt exception — {message}",
            ],
        },
        "status": status,
        "reason": f"candidate exception: {message}",
        "planner_score": _planner_score(strategy, status),
        "selection_reason": "",
        "exception": message,
    }


def _evaluate_split_strategy_attempts(shape, strategies):
    attempts = []
    for strategy in strategies:
        try:
            attempt = _evaluate_split_strategy_attempt(shape, strategy)
        except Exception as exc:
            attempt = _failed_attempt_from_exception(strategy, exc)

        attempt["planner_score"] = _planner_score(
            attempt["strategy"],
            attempt["status"],
        )
        attempts.append(attempt)

    if not attempts:
        return None, []

    selected_attempt = max(
        attempts,
        key=lambda attempt: (
            attempt.get("planner_score", float("-inf")),
            -int(attempt["strategy"].get("rank", 0) or 0),
        ),
    )
    selected_id = selected_attempt["strategy"]["strategy_id"]

    for attempt in attempts:
        if attempt["strategy"]["strategy_id"] == selected_id:
            attempt["selection_reason"] = (
                "selected: highest planner score among attempted strategies"
            )
        else:
            attempt["selection_reason"] = (
                f"not_selected: planner score lower than selected strategy {selected_id}"
            )

    return selected_attempt, attempts


def _split_strategy_diagnostics(strategies, selected_strategy, attempts=None):
    attempts = attempts or []
    attempts_by_id = {
        attempt["strategy"]["strategy_id"]: attempt
        for attempt in attempts
    }

    selected_id = selected_strategy.get("strategy_id") if selected_strategy else ""
    diagnostics = []
    for strategy in strategies:
        attempt = attempts_by_id.get(strategy["strategy_id"])
        diagnostics.append(
            {
                "strategy_id": strategy["strategy_id"],
                "selected": strategy["strategy_id"] == selected_id,
                "rank": strategy["rank"],
                "direction": strategy["direction_label"],
                "direction_score": strategy["direction_score"],
                "backface_ratio": strategy["backface_ratio"],
                "geometry_factor": strategy["geometry_factor"],
                "status": strategy["status"],
                "reason": strategy["reason"],
                "attempted": attempt is not None,
                "attempt_status": attempt["status"] if attempt else "not_attempted",
                "planner_score": attempt["planner_score"] if attempt else None,
                "selection_reason": attempt["selection_reason"] if attempt else "",
                "attempt_summary": attempt["validation"]["summary"] if attempt else "",
                "attempt_exception": attempt["exception"] if attempt else "",
            }
        )
    return diagnostics


def _split_strategy_attempt_diagnostics(attempts):
    diagnostics = []
    for index, attempt in enumerate(attempts, start=1):
        strategy = attempt["strategy"]
        diagnostics.append(
            {
                "attempt_index": index,
                "strategy_id": strategy["strategy_id"],
                "rank": strategy["rank"],
                "direction": strategy["direction_label"],
                "status": attempt["status"],
                "reason": attempt["reason"],
                "planner_score": attempt["planner_score"],
                "selection_reason": attempt["selection_reason"],
                "analysis_gate_status": attempt.get("analysis_gate_status", ""),
                "parting_status": attempt["parting"]["status"],
                "mould_halves_status": attempt["mould_halves"]["status"],
                "validation_summary": attempt["validation"]["summary"],
                "exception": attempt["exception"],
            }
        )
    return diagnostics


def _format_split_strategy_summary(
    selected_strategy,
    strategies,
    selected_attempt=None,
    attempts=None,
):
    if selected_strategy is None:
        return "no strategy selected"

    attempts = attempts or []
    selected_status = selected_attempt["status"] if selected_attempt else "unknown"
    selected_planner_score = selected_attempt["planner_score"] if selected_attempt else float("nan")
    selected_reason = selected_attempt["selection_reason"] if selected_attempt else ""
    failed_attempts = len([attempt for attempt in attempts if attempt["status"] == "Fail"])

    return (
        f"selected={selected_strategy['strategy_id']}"
        f"(dir={selected_strategy['direction_label']}, rank={selected_strategy['rank']}, "
        f"score={selected_strategy['direction_score']:.1f}%, status={selected_status}, "
        f"planner_score={selected_planner_score:.3f}), "
        f"selection_reason={selected_reason}, "
        f"candidates={len(strategies)}, attempted={len(attempts)}, failed_attempts={failed_attempts}"
    )


def _projection_bounds(shape, direction):
    unit = _normalized(direction)
    corners = [
        Vector(x, y, z)
        for x in (shape.BoundBox.XMin, shape.BoundBox.XMax)
        for y in (shape.BoundBox.YMin, shape.BoundBox.YMax)
        for z in (shape.BoundBox.ZMin, shape.BoundBox.ZMax)
    ]
    projections = [
        corner.x * unit.x + corner.y * unit.y + corner.z * unit.z
        for corner in corners
    ]
    return min(projections), max(projections)


def _dominant_axis(direction):
    unit = _normalized(direction)
    components = {
        "x": abs(unit.x),
        "y": abs(unit.y),
        "z": abs(unit.z),
    }
    return max(components, key=components.get)


def _import_parting_solver():
    """Lazily import the Composites_parting C++ binding.

    Returns a `(callable, error_message)` pair. The callable is `None` when the
    binding is unavailable (for example, if FreeCAD was built without the C++
    extension). Importing lazily keeps `mould_analysis` loadable headless
    without the .so present.
    """
    try:
        import Composites_parting  # noqa: F401
        return Composites_parting.compute_non_planar_parting, ""
    except ImportError as exc:
        return None, str(exc)


def _propose_non_planar_parting(
    shape,
    direction,
    stock_margin_x=5.0,
    stock_margin_y=5.0,
    stock_margin_z=5.0,
    part_line_tolerance=0.1,
    stock_footprint=None,
    part_line_only=False,
):
    """Call the C++ marching-equator solver and map to the Phase 0 contract.

    Returns a dict shaped for `_evaluate_split_strategy_attempt`'s
    non-planar path: `status` ("ready" | "not_implemented" | "fork_degenerate"
    ...), `summary`, `parting_line` (the 3D part line),
    `parting_line_segments` (the face-attached UV chain), `parting_surface`
    (alias for the part line), `lower_shell` / `upper_shell` (the split source
    halves), `skirt_rays`, and `tangent_face_midpoints` diagnostics. Any
    non-ready status is surfaced to the caller as a failed attempt — there is
    no planar fallback.
    """
    compute, import_error = _import_parting_solver()
    if compute is None:
        summary = "Composites_parting binding unavailable"
        if import_error:
            summary = f"{summary}: {import_error}"
        return {
            "status": "NotImplemented",
            "summary": summary,
            "parting_line": None,
            "parting_surface": None,
            "parting_line_segments": [],
            "lower_shell": None,
            "upper_shell": None,
            "skirt_rays": [],
            "tangent_face_midpoints": [],
            "error": summary,
        }

    footprint = (0.0, 0.0)
    if stock_footprint is not None and getattr(stock_footprint, "Length", 0.0) > 0:
        footprint = (float(stock_footprint.x), float(stock_footprint.y))

    try:
        # Reproduction aid for the nextdrape mould_cli --load-shapefile harness:
        # when FC_PARTING_DUMP_DIR is set, write the EXACT shape + draw direction
        # that feed the binding, so the solver can be debugged at the nextdrape
        # level on byte-identical geometry.
        import os as _os
        _dump = _os.environ.get("FC_PARTING_DUMP_DIR")
        if _dump:
            _bbox = shape.BoundBox
            _tag = f"{_bbox.XLength:.0f}x{_bbox.YLength:.0f}x{_bbox.ZLength:.0f}_{_bbox.Center.x:.0f}_{_bbox.Center.y:.0f}_{_bbox.Center.z:.0f}"
            shape.exportBrep(_os.path.join(_dump, f"{_tag}.brep"))
            with open(_os.path.join(_dump, f"{_tag}.dir"), "w") as f:
                f.write(f"{float(direction.x)},{float(direction.y)},{float(direction.z)}\n")
        raw = compute(
            shape,
            (float(direction.x), float(direction.y), float(direction.z)),
            float(stock_margin_x),
            float(stock_margin_y),
            float(stock_margin_z),
            float(part_line_tolerance),
            footprint,
            part_line_only,
        )
    except Exception as exc:
        return {
            "status": "NotImplemented",
            "summary": f"Composites_parting binding raised: {exc}",
            "parting_line": None,
            "parting_surface": None,
            "parting_line_segments": [],
            "lower_shell": None,
            "upper_shell": None,
            "skirt_rays": [],
            "tangent_face_midpoints": [],
            "error": str(exc),
            "part_line_only": part_line_only,
        }

    status = raw["status"]
    if status != "ready":
        # Non-ready: surface the failure reason to the caller as a failed
        # attempt (no planar fallback).
        # Normalize the binding's lowercase status to the capital form the
        # consumer checks (non_planar_result["status"] != "NotImplemented").
        normalized = {
            "not_implemented": "NotImplemented",
            "fork_degenerate": "fork_degenerate",
            "no_bbox_touch_point": "no_bbox_touch_point",
            "march_did_not_close": "march_did_not_close",
            "split_failed": "split_failed",
            "invalid_solid_result": "invalid_solid_result",
        }.get(status, status)
        # A non-ready verdict does not imply there is no part line. Several
        # late-stage failures (skirt_failed, split_failed, invalid_solid_result)
        # occur after the march has already closed a valid part line, and the
        # binding surfaces it via part_line_3d. Surface it when one was really
        # built, so a mould that cannot finish still shows its parting line.
        part_line = raw.get("part_line_3d")
        if part_line is None or getattr(part_line, "isNull", lambda: True)():
            part_line = None
        return {
            "status": normalized,
            "summary": raw["summary"],
            "parting_line": part_line,
            "parting_surface": part_line,
            "parting_line_segments": raw.get("part_line_segments", []),
            "lower_shell": None,
            "upper_shell": None,
            "skirt_rays": [],
            "tangent_face_midpoints": raw.get("tangent_face_midpoints", []),
            "error": raw["summary"],
            "part_line_only": part_line_only,
        }

    # success: shapes are already live Part.Shape objects from the binding.
    parting_line = raw.get("part_line_3d")
    lower_shell = raw.get("mould_half_lower")
    upper_shell = raw.get("mould_half_upper")
    return {
        "status": "ready",
        "summary": raw["summary"],
        "parting_line": parting_line,
        "parting_surface": parting_line,
        "parting_line_segments": raw.get("part_line_segments", []),
        "lower_shell": lower_shell,
        "upper_shell": upper_shell,
        "skirt_rays": [],
        "tangent_face_midpoints": raw.get("tangent_face_midpoints", []),
        "withdrawal_clearance": raw.get("withdrawal_clearance"),
        "error": "",
        "part_line_only": part_line_only,
    }


def _analysis_gate_status(draft_face_screening):
    """Informational draft-face signal, decoupled from the verdict.

    Pass only when every face drafts cleanly away from the draw direction;
    Warning when any risky or ambiguous face is present (which includes
    legitimate parting faces — this gate does NOT drive the verdict, it only
    reports the crude draft signal alongside the authoritative
    withdrawal-clearance check in validate_mould_result).
    """
    draft = draft_face_screening or {}
    return "Pass" if draft.get("status") == "Ready" else "Warning"


def _shape_center(shape):
    bbox = shape.BoundBox
    return Vector(
        0.5 * (bbox.XMin + bbox.XMax),
        0.5 * (bbox.YMin + bbox.YMax),
        0.5 * (bbox.ZMin + bbox.ZMax),
    )


def _bboxs_overlap(first_bbox, second_bbox, tolerance=1.0e-6):
    return not (
        first_bbox.XMax < (second_bbox.XMin - tolerance)
        or second_bbox.XMax < (first_bbox.XMin - tolerance)
        or first_bbox.YMax < (second_bbox.YMin - tolerance)
        or second_bbox.YMax < (first_bbox.YMin - tolerance)
        or first_bbox.ZMax < (second_bbox.ZMin - tolerance)
        or second_bbox.ZMax < (first_bbox.ZMin - tolerance)
    )


def _shape_volume(shape):
    """Volume of a shape, or zero when null/invalid/unsafe to query."""
    try:
        if shape is None or shape.isNull():
            return 0.0
        return float(shape.Volume or 0.0)
    except Exception:
        return 0.0


def _shape_common_volume(shape_a, shape_b):
    try:
        common = shape_a.common(shape_b)
    except Exception:
        return 0.0

    if getattr(common, "isNull", lambda: True)():
        return 0.0

    try:
        volume = float(getattr(common, "Volume", 0.0) or 0.0)
    except Exception:
        volume = 0.0
    return max(0.0, volume)


def _sample_shape_points(shape, samples_per_edge=PARTING_LINE_ATTACHMENT_SAMPLES):
    points = []
    for edge in getattr(shape, "Edges", []):
        try:
            edge_points = edge.discretize(samples_per_edge)
        except Exception:
            continue
        points.extend(edge_points)
    if points:
        return points

    for vertex in getattr(shape, "Vertexes", []):
        point = getattr(vertex, "Point", None)
        if point is not None:
            points.append(point)
    return points


def _point_distance_to_shape(shape, point):
    try:
        distance, _, _ = shape.distToShape(Part.Vertex(point))
    except Exception:
        return None
    try:
        return float(distance)
    except Exception:
        return None


def _parting_line_stays_on_source(parting_line_shape, source_shape,
                                  tolerance_mm=PARTING_LINE_ATTACHMENT_TOLERANCE_MM):
    if getattr(source_shape, "isNull", lambda: True)():
        return False, "source shape is unavailable"

    sample_points = _sample_shape_points(parting_line_shape)
    if not sample_points:
        return False, "parting line has no sampleable geometry"

    measured = False
    for point in sample_points:
        distance = _point_distance_to_shape(source_shape, point)
        if distance is None:
            continue
        measured = True
        if distance > tolerance_mm:
            return False, (
                f"sampled point is {distance:.4f} mm from the source surface "
                f"(tolerance {tolerance_mm:.4f} mm)"
            )

    if not measured:
        return False, "could not measure parting line attachment to source"
    return True, ""


def _validation_reason_code(severity, label):
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"{severity}_{slug}" if slug else severity


def _extract_validation_reasons(checks):
    reasons = []
    for check in checks:
        if check.startswith("FAIL:"):
            severity = "fail"
            body = check[len("FAIL:") :].strip()
        elif check.startswith("WARN:"):
            severity = "warning"
            body = check[len("WARN:") :].strip()
        else:
            continue

        if " — " in body:
            label, detail = body.split(" — ", 1)
        else:
            label, detail = body, ""

        label = label.strip()
        detail = detail.strip()
        reasons.append(
            {
                "severity": severity,
                "code": _validation_reason_code(severity, label),
                "label": label,
                "detail": detail,
            }
        )
    return reasons


def _dedupe_validation_reasons(reasons):
    deduped = []
    seen = set()
    for reason in reasons:
        key = (
            reason.get("severity", ""),
            reason.get("code", ""),
            reason.get("label", ""),
            reason.get("detail", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reason)
    return deduped


def _validation_reason_payload(checks):
    reasons = _dedupe_validation_reasons(_extract_validation_reasons(list(checks or [])))
    return {
        "reasons": reasons,
        "reason_codes": [reason["code"] for reason in reasons],
    }


def validate_mould_result(
    parting_surface_status,
    mould_halves_status,
    parting_surface_shape,
    mould_half_a_shape,
    mould_half_b_shape,
    withdrawal_clearance_status=None,
    source_shape=None,
    parting_line_shape=None,
):
    checks = []
    failures = 0
    warnings = 0

    def add_check(ok, label, detail=None, warning=False):
        nonlocal failures, warnings
        prefix = "PASS" if ok else ("WARN" if warning else "FAIL")
        if ok:
            checks.append(f"{prefix}: {label}")
            return
        if warning:
            warnings += 1
        else:
            failures += 1
        if detail:
            checks.append(f"{prefix}: {label} — {detail}")
        else:
            checks.append(f"{prefix}: {label}")

    def shape_is_non_null_and_valid(shape):
        if getattr(shape, "isNull", lambda: True)():
            return False
        try:
            return bool(shape.isValid())
        except Exception:
            return True

    parting_shape_valid = shape_is_non_null_and_valid(parting_surface_shape)
    mould_half_a_is_null = getattr(mould_half_a_shape, "isNull", lambda: True)()
    mould_half_b_is_null = getattr(mould_half_b_shape, "isNull", lambda: True)()
    mould_half_a_valid = shape_is_non_null_and_valid(mould_half_a_shape)
    mould_half_b_valid = shape_is_non_null_and_valid(mould_half_b_shape)

    degraded_but_usable = (
        mould_halves_status == "Degraded"
        and (not mould_half_a_is_null)
        and (not mould_half_b_is_null)
        and mould_half_a_valid
        and mould_half_b_valid
    )

    add_check(parting_surface_status == "Ready", "parting surface generated")
    if mould_halves_status == "Ready":
        add_check(True, "mould halves generated")
    elif degraded_but_usable:
        add_check(
            False,
            "mould halves degraded but usable",
            detail="status=Degraded with both half geometries valid",
            warning=True,
        )
    else:
        add_check(
            False,
            "mould halves generated",
            detail=f"status={mould_halves_status}",
        )

    add_check(
        parting_shape_valid,
        "parting surface shape is valid",
    )
    if source_shape is not None and parting_line_shape is not None:
        parting_line_valid = shape_is_non_null_and_valid(parting_line_shape)
        add_check(
            parting_line_valid,
            "parting line shape is valid",
        )
        if parting_line_valid:
            parting_line_attached, attachment_detail = _parting_line_stays_on_source(
                parting_line_shape,
                source_shape,
            )
            add_check(
                parting_line_attached,
                "parting line stays on source shape",
                detail=attachment_detail or "detached from source surface",
            )
    add_check(
        not mould_half_a_is_null,
        "mould half A geometry is non-null",
        detail="null mould half A geometry",
    )
    add_check(
        not mould_half_b_is_null,
        "mould half B geometry is non-null",
        detail="null mould half B geometry",
    )
    add_check(
        mould_half_a_valid,
        "first mould half shape is valid",
    )
    add_check(
        mould_half_b_valid,
        "second mould half shape is valid",
    )

    # Withdrawal clearance is the authoritative necessary test: a mould half
    # that collides with the source on withdrawal makes the mould invalid,
    # regardless of what the draft/accessibility heuristics said. Fail is hard;
    # there is no Warning state (the mould either withdraws or it does not).
    if withdrawal_clearance_status == "Fail":
        add_check(
            False,
            "mould withdraws without collision",
            detail="withdrawal clearance fail: a mould half collides with the source on withdrawal",
        )
    elif withdrawal_clearance_status == "Pass":
        add_check(True, "mould withdraws without collision")

    if failures:
        status = "Fail"
    elif warnings:
        status = "Warning"
    else:
        status = "Pass"

    summary = (
        f"Validation {status.lower()}: {len([c for c in checks if c.startswith('PASS:')])} pass, "
        f"{warnings} warning, {failures} fail"
    )
    payload = _validation_reason_payload(checks)
    return {
        "status": status,
        "summary": summary,
        "checks": checks,
        "reasons": payload["reasons"],
        "reason_codes": payload["reason_codes"],
    }


def _status_and_summary_from_checks(checks):
    pass_count = len([c for c in checks if c.startswith("PASS:")])
    warn_count = len([c for c in checks if c.startswith("WARN:")])
    fail_count = len([c for c in checks if c.startswith("FAIL:")])
    if fail_count:
        status = "Fail"
    elif warn_count:
        status = "Warning"
    else:
        status = "Pass"
    summary = (
        f"Validation {status.lower()}: {pass_count} pass, "
        f"{warn_count} warning, {fail_count} fail"
    )
    return status, summary


def _append_validation_check(validation, check):
    checks = list(validation.get("checks", []))
    checks.append(check)
    status, validation_summary = _status_and_summary_from_checks(checks)
    payload = _validation_reason_payload(checks)
    return {
        "status": status,
        "summary": validation_summary,
        "checks": checks,
        "reasons": payload["reasons"],
        "reason_codes": payload["reason_codes"],
    }


def _append_normalization_validation_check(validation, normalization):
    checks = list(validation.get("checks", []))
    confidence = normalization["confidence"]
    summary = normalization["summary"]

    if confidence == NORMALIZATION_CONFIDENCE_EXACT:
        checks.append(f"PASS: normalization exact — {summary}")
    elif confidence == NORMALIZATION_CONFIDENCE_APPROXIMATE:
        checks.append(f"WARN: normalization approximate — {summary}")
    else:
        checks.append(f"FAIL: normalization failed — {summary}")

    hint_flags = normalization.get("hint_flags", [])
    if "hint_thickness_present" in hint_flags:
        checks.append("PASS: source thickness hint detected")
    if "hint_laminate_present" in hint_flags:
        checks.append("PASS: source laminate hint detected")

    status, validation_summary = _status_and_summary_from_checks(checks)
    payload = _validation_reason_payload(checks)
    return {
        "status": status,
        "summary": validation_summary,
        "checks": checks,
        "reasons": payload["reasons"],
        "reason_codes": payload["reason_codes"],
    }


def _base_analysis_result():
    return {
        "status": "Waiting for source",
        "summary": "Select a solid to begin mould analysis.",
        "shape": Part.Shape(),
        "draw_direction_score": 0.0,
        "best_draw_direction": default_mould_analysis_draw_direction,
        "split_strategy_summary": "No split strategy planned.",
        "split_strategy_diagnostics": [],
        "split_strategy_attempts": [],
        "analysis_gate_status": "Waiting for source",
        "draft_face_summary": "No source shape available.",
        "draft_face_classifications": [],
        "parting_surface_status": "Waiting for source",
        "parting_surface_summary": "No source shape available.",
        "parting_curve_summary": "No source shape available.",
        "parting_surface_shape": Part.Shape(),
        "parting_surface_normal": default_mould_analysis_draw_direction,
        "parting_surface_offset": 0.0,
        "parting_surface_area": 0.0,
        "mould_halves_status": "Waiting for source",
        "mould_halves_summary": "No source shape available.",
        "mould_half_a_shape": Part.Shape(),
        "mould_half_b_shape": Part.Shape(),
        "mould_half_a_volume": 0.0,
        "mould_half_b_volume": 0.0,
        "withdrawal_clearance_status": "Waiting for source",
        "withdrawal_clearance_summary": "No source shape available.",
        "withdrawal_clearance_failure_count": 0,
        "parting_model": "NonPlanar",
        "parting_line": None,
        "parting_skirt_rays": [],
        "non_planar_status": "not_requested",
        "non_planar_summary": "",
        "validation_status": "Waiting for source",
        "validation_summary": "No source shape available.",
        "validation_checks": ["No source shape available."],
        "validation_reasons": [],
        "validation_reason_codes": [],
        "normalization_confidence": NORMALIZATION_CONFIDENCE_FAIL,
        "normalization_source_type": "none",
        "normalization_summary": "Normalization failed: source shape is missing or null.",
        "normalization_reason_flags": ["source_missing_or_null"],
        "normalization_hint_summary": "no source-object hints",
    }


def normalize_source_shape(shape, hints=None):
    base = _base_analysis_result()
    hints = hints or {}
    hint_flags = _normalization_hint_reason_flags(hints)
    hint_summary = _normalization_hint_summary(hints)

    def build_result(confidence, source_type, summary, reason_flags, effective_shape):
        return {
            "confidence": confidence,
            "source_type": source_type,
            "summary": f"{summary} Hints: {hint_summary}.",
            "reason_flags": _normalization_reason_flags(reason_flags, hint_flags),
            "hint_flags": list(hint_flags),
            "hint_summary": hint_summary,
            "effective_shape": effective_shape,
        }

    if shape is None or getattr(shape, "isNull", lambda: True)():
        return build_result(
            NORMALIZATION_CONFIDENCE_FAIL,
            "none",
            base["normalization_summary"],
            base["normalization_reason_flags"],
            Part.Shape(),
        )

    shape_type = getattr(shape, "ShapeType", "Unknown")

    if shape_type in ("Solid", "CompSolid"):
        return build_result(
            NORMALIZATION_CONFIDENCE_EXACT,
            shape_type.lower(),
            "Normalization exact: solid input used without approximation.",
            ["solid_passthrough_exact"],
            _safe_copy_shape(shape),
        )

    if shape_type == "Compound":
        solids = list(getattr(shape, "Solids", []))
        if len(solids) == 1 and not solids[0].isNull():
            return build_result(
                NORMALIZATION_CONFIDENCE_EXACT,
                "compound",
                "Normalization exact: single solid extracted from compound source.",
                ["compound_single_solid_exact"],
                _safe_copy_shape(solids[0]),
            )
        if len(solids) > 1:
            return build_result(
                NORMALIZATION_CONFIDENCE_FAIL,
                "compound",
                "Normalization failed: source compound contains multiple solids; two-piece single-body normalization is ambiguous.",
                ["compound_multi_solid_unsupported"],
                Part.Shape(),
            )
        shells = list(getattr(shape, "Shells", []))
        if len(shells) == 1:
            shape = shells[0]
            shape_type = "Shell"
        else:
            return build_result(
                NORMALIZATION_CONFIDENCE_FAIL,
                "compound",
                "Normalization failed: source compound has no single solid or shell candidate for effective-solid synthesis.",
                ["compound_no_effective_candidate"],
                Part.Shape(),
            )

    if shape_type == "Shell":
        reason_flags = []
        thickness_hint_state = hints.get("thickness_hint_state", "missing")
        thickness_mm = hints.get("thickness_mm")
        thickness_envelope_shape = None
        thickness_envelope_note = ""

        if thickness_mm is not None and thickness_mm > 0.0:
            reason_flags.append("shell_thickness_envelope_attempted")
            try:
                candidate = _bbox_proxy_solid(
                    shape,
                    padding_hint_mm=thickness_mm,
                )
                if not candidate.isNull():
                    thickness_envelope_shape = candidate
                    reason_flags.append("shell_thickness_envelope_succeeded")
                    thickness_envelope_note = (
                        f"thickness envelope attempted with numeric thickness hint {thickness_mm:.3f} mm and succeeded"
                    )
                else:
                    reason_flags.append("shell_thickness_envelope_failed")
                    thickness_envelope_note = (
                        f"thickness envelope attempted with numeric thickness hint {thickness_mm:.3f} mm but returned null"
                    )
            except Exception:
                reason_flags.append("shell_thickness_envelope_failed")
                thickness_envelope_note = (
                    f"thickness envelope attempted with numeric thickness hint {thickness_mm:.3f} mm but raised conversion error"
                )
        else:
            if thickness_hint_state == "invalid_non_positive":
                reason_flags.append("shell_thickness_envelope_skipped_invalid_numeric_thickness")
                thickness_envelope_note = (
                    "thickness envelope skipped due to non-positive numeric thickness hint"
                )
            elif thickness_hint_state == "invalid_non_numeric":
                reason_flags.append("shell_thickness_envelope_skipped_invalid_numeric_thickness")
                thickness_envelope_note = (
                    "thickness envelope skipped due to non-numeric thickness hint"
                )
            else:
                reason_flags.append("shell_thickness_envelope_skipped_missing_numeric_thickness")
                thickness_envelope_note = (
                    "thickness envelope skipped due to missing numeric thickness hint"
                )

            if (
                "hint_laminate_present" in hint_flags
                and "hint_thickness_present" not in hint_flags
            ):
                reason_flags.append("shell_laminate_only_no_numeric_thickness")

        is_closed = getattr(shape, "isClosed", lambda: False)()
        if not is_closed:
            reason_flags.append("shell_open_requires_envelope")
        else:
            try:
                effective_solid = Part.makeSolid(shape)
                if (
                    not getattr(effective_solid, "isNull", lambda: True)()
                    and getattr(effective_solid, "Volume", 0.0) > 0.0
                ):
                    if "hint_thickness_present" in hint_flags or "hint_laminate_present" in hint_flags:
                        shell_summary = (
                            "Normalization approximate: shell converted to effective solid envelope using available source-object hints; "
                            f"{thickness_envelope_note}."
                        )
                    else:
                        shell_summary = (
                            "Normalization approximate: shell converted to effective solid envelope without explicit thickness/laminate metadata; "
                            f"{thickness_envelope_note}."
                        )
                    return build_result(
                        NORMALIZATION_CONFIDENCE_APPROXIMATE,
                        "shell",
                        shell_summary,
                        reason_flags + ["shell_effective_solid_approximate"],
                        _safe_copy_shape(effective_solid),
                    )
                reason_flags.append("shell_no_closed_volume")
            except Exception:
                reason_flags.append("shell_solid_conversion_failed")

        if thickness_envelope_shape is not None:
            return build_result(
                NORMALIZATION_CONFIDENCE_APPROXIMATE,
                "shell",
                "Normalization approximate: shell replaced with thickness-based conservative envelope fallback; "
                f"{thickness_envelope_note}.",
                reason_flags + ["shell_thickness_envelope_used"],
                _safe_copy_shape(thickness_envelope_shape),
            )

        try:
            proxy = _bbox_proxy_solid(shape)
            if not proxy.isNull():
                missing_metadata_flag = []
                if "hint_thickness_present" not in hint_flags and "hint_laminate_present" not in hint_flags:
                    missing_metadata_flag = ["missing_thickness_or_laminate_metadata"]
                return build_result(
                    NORMALIZATION_CONFIDENCE_APPROXIMATE,
                    "shell",
                    "Normalization approximate: shell replaced with conservative bounding proxy solid; "
                    f"{thickness_envelope_note}.",
                    reason_flags + ["shell_proxy_bbox"] + missing_metadata_flag,
                    proxy,
                )
            reason_flags.append("shell_proxy_null")
        except Exception:
            reason_flags.append("shell_proxy_failed")

        return build_result(
            NORMALIZATION_CONFIDENCE_FAIL,
            "shell",
            "Normalization failed: shell source could not be converted to an effective solid; "
            f"{thickness_envelope_note}.",
            reason_flags + ["shell_unrecoverable"],
            Part.Shape(),
        )

    try:
        proxy = _bbox_proxy_solid(
            shape,
            padding_hint_mm=hints.get("thickness_mm"),
        )
        if not proxy.isNull():
            return build_result(
                NORMALIZATION_CONFIDENCE_APPROXIMATE,
                shape_type.lower(),
                "Normalization approximate: non-solid source replaced with conservative bounding proxy solid.",
                ["non_solid_proxy_bbox"],
                proxy,
            )
    except Exception:
        pass

    return build_result(
        NORMALIZATION_CONFIDENCE_FAIL,
        shape_type.lower(),
        f"Normalization failed: unsupported source shape type '{shape_type}'.",
        ["unsupported_source_shape_type"],
        Part.Shape(),
    )


def analyze_source_shape(
    shape,
    draw_direction=default_mould_analysis_draw_direction,
    source_obj=None,
    parting_stock_margin_x=5.0,
    parting_stock_margin_y=5.0,
    parting_stock_margin_z=5.0,
    parting_line_tolerance=0.1,
    parting_stock_footprint=None,
    part_line_only=False,
):
    """Return a lightweight analysis preview for a selected source shape.

    Analyses the user-specified draw direction only (no auto-ranking). The
    draft-face gate is a soft Pass/Warning signal; withdrawal clearance is the
    authoritative necessary test that escalates the verdict to Fail on
    collision.
    """
    result = _base_analysis_result()
    if shape is None or getattr(shape, "isNull", lambda: True)():
        return result

    normalization_hints = _extract_normalization_hints(source_obj)
    normalization = normalize_source_shape(shape, hints=normalization_hints)
    result["normalization_confidence"] = normalization["confidence"]
    result["normalization_source_type"] = normalization["source_type"]
    result["normalization_summary"] = normalization["summary"]
    result["normalization_reason_flags"] = normalization["reason_flags"]
    result["normalization_hint_summary"] = normalization.get(
        "hint_summary", _normalization_hint_summary(normalization_hints)
    )

    if normalization["confidence"] == NORMALIZATION_CONFIDENCE_FAIL:
        normalization_failure_checks = [
            "FAIL: normalization produced no effective solid",
            f"FAIL: {normalization['summary']}",
        ]
        normalization_failure_payload = _validation_reason_payload(
            normalization_failure_checks
        )
        normalization_validation_summary = (
            "Validation fail: normalization did not produce an effective solid."
        )
        result.update(
            {
                "status": "Fail",
                "summary": (
                    "Source fail for mould analysis; "
                    f"normalization={normalization['confidence']} ({normalization['summary']}), "
                    f"validation={normalization_validation_summary}"
                ),
                "validation_status": "Fail",
                "validation_summary": normalization_validation_summary,
                "validation_checks": normalization_failure_checks,
                "validation_reasons": normalization_failure_payload["reasons"],
                "validation_reason_codes": normalization_failure_payload["reason_codes"],
                "parting_surface_status": "Fail",
                "parting_surface_summary": "No parting surface generated because normalization failed.",
                "parting_curve_summary": "No parting surface generated because normalization failed.",
                "mould_halves_status": "Fail",
                "mould_halves_summary": "No mould halves generated because normalization failed.",
                "analysis_gate_status": "Fail",
                "draft_face_summary": "Draft face screening unavailable because normalization failed.",
                "draft_face_classifications": [],
            }
        )
        return result

    effective_shape = normalization["effective_shape"]
    bbox = effective_shape.BoundBox
    preferred_evidence = _direction_geometric_evidence(effective_shape, draw_direction)
    preferred_backface_ratio = preferred_evidence["backface_ratio"]
    preferred_geometry_factor = max(
        0.0,
        1.0 - (GEOMETRY_BACKFACE_WEIGHT * preferred_backface_ratio),
    )
    preferred_extent = _extent_along_direction(bbox, draw_direction)
    preferred_bbox_score = 1.0 / preferred_extent if preferred_extent else 0.0
    preferred_score = preferred_bbox_score * preferred_geometry_factor
    normalized_preferred_score = 100.0 * preferred_score if preferred_score else 0.0
    best_direction = draw_direction
    ranked = [
        {
            "index": 0,
            "direction": _normalized(draw_direction),
            "extent": preferred_extent,
            "bbox_score": preferred_bbox_score,
            "backface_ratio": preferred_backface_ratio,
            "geometry_factor": preferred_geometry_factor,
            "score": preferred_score,
            "normalized_score": 100.0,
            "draft_face_screening": preferred_evidence["draft_face_screening"],
            "analysis_gate_status": preferred_evidence["analysis_gate_status"],
            "geometric_evidence": preferred_evidence,
            "parting_model": "NonPlanar",
            "parting_line_tolerance": parting_line_tolerance,
            "parting_stock_margin_x": parting_stock_margin_x,
            "parting_stock_margin_y": parting_stock_margin_y,
            "parting_stock_margin_z": parting_stock_margin_z,
            "parting_stock_footprint": parting_stock_footprint,
            "part_line_only": part_line_only,
        }
    ]
    split_strategies = _plan_split_strategies(ranked, limit=1)
    if split_strategies:
        selected_split_strategy = split_strategies[0]
    else:
        selected_split_strategy = {
            "strategy_id": "draw_direction",
            "rank": 1,
            "direction": draw_direction,
            "direction_label": _format_vector(draw_direction),
            "direction_score": 100.0,
            "backface_ratio": preferred_backface_ratio,
            "geometry_factor": preferred_geometry_factor,
            "status": "fallback",
            "reason": "draw direction strategy",
        }
        split_strategies = [selected_split_strategy]

    selected_attempt, split_strategy_attempts = _evaluate_split_strategy_attempts(
        effective_shape,
        split_strategies,
    )
    if selected_attempt is None:
        # No attempt produced a candidate. There is no planar fallback —
        # build a nominal fail attempt so the caller reports the failure.
        failure_summary = "C++ non-planar solver produced no result for the selected strategy"
        failing_parting = {
            "status": "Fail",
            "summary": failure_summary,
            "curve_summary": "No parting surface generated by the non-planar solver.",
            "shape": Part.Shape(),
            "surface_normal": selected_split_strategy["direction"],
            "surface_offset": 0.0,
            "surface_area": 0.0,
        }
        failing_mould_halves = {
            "status": "Fail",
            "summary": failure_summary,
            "half_a_shape": Part.Shape(),
            "half_b_shape": Part.Shape(),
            "half_a_volume": 0.0,
            "half_b_volume": 0.0,
        }
        selected_attempt = {
            "strategy": selected_split_strategy,
            "draft_face_screening": {
                "status": "Fail",
                "summary": "Draft face screening unavailable for fallback split strategy.",
                "safe_face_area": 0.0,
                "risky_face_area": 0.0,
                "ambiguous_face_area": 0.0,
                "safe_face_count": 0,
                "risky_face_count": 0,
                "ambiguous_face_count": 0,
                "face_classifications": [],
            },
            "analysis_gate_status": "Fail",
            "parting": failing_parting,
            "mould_halves": failing_mould_halves,
            "withdrawal_clearance": {
                "status": "Fail",
                "summary": "Withdrawal clearance unavailable for fallback split strategy.",
                "failure_count": 0,
            },
            "non_planar_result": None,
            "validation": {
                "status": "Fail",
                "summary": "Validation fail: split strategy attempts produced no candidate.",
                "checks": ["FAIL: split strategy attempts produced no candidate"],
            },
            "status": "Fail",
            "reason": "no split strategy attempt available",
            "planner_score": _planner_score(selected_split_strategy, "Fail"),
            "selection_reason": "selected: only available fallback attempt",
            "exception": "",
        }
        split_strategy_attempts = [selected_attempt]

    selected_split_strategy = selected_attempt["strategy"]
    draft_face_screening = selected_attempt["draft_face_screening"]

    parting = selected_attempt["parting"]
    mould_halves = selected_attempt["mould_halves"]
    withdrawal_clearance = selected_attempt["withdrawal_clearance"]
    validation = selected_attempt["validation"]

    split_strategy_summary = _format_split_strategy_summary(
        selected_split_strategy,
        split_strategies,
        selected_attempt,
        split_strategy_attempts,
    )
    split_strategy_diagnostics = _split_strategy_diagnostics(
        split_strategies,
        selected_split_strategy,
        split_strategy_attempts,
    )
    split_strategy_attempt_diagnostics = _split_strategy_attempt_diagnostics(
        split_strategy_attempts,
    )

    validation = _append_normalization_validation_check(validation, normalization)
    validation = _append_validation_check(
        validation,
        f"PASS: split strategy planning — {split_strategy_summary}",
    )

    if validation["status"] == "Fail":
        status = "Fail"
    elif validation["status"] == "Warning":
        status = "Warning"
    else:
        status = "Ready"

    validation_reasons = validation.get("reasons")
    validation_reason_codes = validation.get("reason_codes")
    if validation_reasons is None or validation_reason_codes is None:
        validation_payload = _validation_reason_payload(validation.get("checks", []))
        validation_reasons = validation_payload["reasons"]
        validation_reason_codes = validation_payload["reason_codes"]

    summary = (
        f"Source {status.lower()} for mould analysis; "
        f"normalization={normalization['confidence']} ({normalization['summary']}), "
        f"bounds=({bbox.XLength:.3f} x {bbox.YLength:.3f} x {bbox.ZLength:.3f}), "
        f"preferred_direction={_format_vector(draw_direction)}, "
        f"direction_score={normalized_preferred_score:.1f}%, "
        f"split_strategy={split_strategy_summary}, "
        f"split_attempts={len(split_strategy_attempt_diagnostics)}, "
        f"parting_surface={parting['summary']}, "
        f"mould_halves={mould_halves['summary']}, "
        f"withdrawal_clearance={withdrawal_clearance['status']}, "
        f"validation={validation['summary']}"
    )

    result.update(
        {
            "status": status,
            "summary": summary,
            "shape": _safe_copy_shape(effective_shape),
            "draw_direction_score": normalized_preferred_score,
            "best_draw_direction": best_direction,
            "split_strategy_summary": split_strategy_summary,
            "split_strategy_diagnostics": split_strategy_diagnostics,
            "split_strategy_attempts": split_strategy_attempt_diagnostics,
            "analysis_gate_status": selected_attempt.get(
                "analysis_gate_status",
                _analysis_gate_status(draft_face_screening),
            ),
            "draft_face_summary": draft_face_screening.get("summary", ""),
            "draft_face_classifications": draft_face_screening.get("face_classifications", []),
            "parting_surface_status": parting["status"],
            "parting_surface_summary": parting["summary"],
            "parting_curve_summary": parting["curve_summary"],
            "parting_surface_shape": parting["shape"],
            "parting_surface_normal": parting["surface_normal"],
            "parting_surface_offset": parting["surface_offset"],
            "parting_surface_area": parting["surface_area"],
            "mould_halves_status": mould_halves["status"],
            "mould_halves_summary": mould_halves["summary"],
            "mould_half_a_shape": mould_halves["half_a_shape"],
            "mould_half_b_shape": mould_halves["half_b_shape"],
            "mould_half_a_volume": mould_halves["half_a_volume"],
            "mould_half_b_volume": mould_halves["half_b_volume"],
            "withdrawal_clearance_status": withdrawal_clearance["status"],
            "withdrawal_clearance_summary": withdrawal_clearance["summary"],
            "withdrawal_clearance_failure_count": withdrawal_clearance["failure_count"],
            "parting_model": selected_split_strategy.get("parting_model", "NonPlanar"),
            "parting_line": (selected_attempt.get("non_planar_result") or {}).get("parting_line"),
            "parting_line_segments": (selected_attempt.get("non_planar_result") or {}).get("parting_line_segments", []),
            "parting_skirt_rays": (selected_attempt.get("non_planar_result") or {}).get("skirt_rays", []),
            "non_planar_status": (
                (selected_attempt.get("non_planar_result") or {}).get("status")
                if selected_split_strategy.get("parting_model") == "NonPlanar"
                else "not_requested"
            ),
            "non_planar_summary": (
                (selected_attempt.get("non_planar_result") or {}).get("summary", "")
                if selected_split_strategy.get("parting_model") == "NonPlanar"
                else ""
            ),
            "validation_status": validation["status"],
            "validation_summary": validation["summary"],
            "validation_checks": validation["checks"],
            "validation_reasons": validation_reasons,
            "validation_reason_codes": validation_reason_codes,
        }
    )
    return result

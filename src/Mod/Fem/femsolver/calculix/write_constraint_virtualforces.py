# ***************************************************************************
# *   Copyright (c) 2026 John Wharington <jwharington@gmail.com>            *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# ***************************************************************************

import math
import os

from FreeCAD import Console, Vector

# Virtual-forces decomposition is configured by code constants.
#
# VF_DECOMPOSE_ACCEL modes:
#   "auto" (default): enable explicit rotational decomposition only when
#   rotational pseudo-acceleration is both significant and numerically safe.
#   True: always decompose (legacy expert/debug mode).
#   False: never decompose (aggregate COM-acceleration representation).
VF_DECOMPOSE_ACCEL = "auto"
VF_DECOMPOSE_OMEGA_EPS = 1.0e-9
VF_DECOMPOSE_ALPHA_EPS = 1.0e-9
VF_DECOMPOSE_COR_RADIUS_MIN = 1.0e-6
VF_DECOMPOSE_COR_RADIUS_MAX = 1.0e6
VF_DECOMPOSE_AUTO_ROT_ACCEL_MIN = 5.0e3
VF_DECOMPOSE_AUTO_ROT_ACCEL_RATIO_MIN = 0.1
VF_DEBUG_CLOSURE = False


def get_analysis_types():
    return ["buckling", "static", "thermomech"]


def get_sets_name():
    return "constraints_virtualforces_element_sets"


def get_constraint_title():
    return "Virtual Forces Constraints"


def get_before_write_meshdata_constraint():
    return ""


def get_after_write_meshdata_constraint():
    return ""


def get_before_write_constraint():
    return ""


def get_after_write_constraint():
    return ""


def vf_body_nodes_name(vf_obj):
    return f"{vf_obj.Name}-BODY"


def _write_axis_dload(f, elset, label, value, axis0, axis_dir, dload_header_fn=None):
    axis_mag = axis_dir.Length
    if axis_mag <= 0.0:
        return False

    # CalculiX DLOAD format for CENTRIF/ROTA/CORIO:
    #   elset, label, magnitude, p1x, p1y, p1z, dvx, dvy, dvz
    # where p1 is a reference point on the axis and (dvx,dvy,dvz) is the
    # axis *direction vector* (CalculiX normalises it internally as dv/|dv|).
    # Write the unit direction directly — NOT p1+direction, because CalculiX
    # would normalise (p1+direction)/|(p1+direction)| giving the wrong axis
    # whenever p1 is far from the origin.
    axis_hat = axis_dir / axis_mag
    header = dload_header_fn() if dload_header_fn is not None else "*DLOAD\n"
    f.write(header)
    f.write(
        "{},{},{:.13G},{:.13G},{:.13G},{:.13G},{:.13G},{:.13G},{:.13G}\n".format(
            elset,
            label,
            value,
            axis0.x,
            axis0.y,
            axis0.z,
            axis_hat.x,
            axis_hat.y,
            axis_hat.z,
        )
    )
    f.write("\n")
    return True


def _write_velocity_initial_conditions(f, nset, velocity):
    f.write("*INITIAL CONDITIONS,TYPE=VELOCITY\n")
    f.write(f"{nset},1,{velocity.x:.13G}\n")
    f.write(f"{nset},2,{velocity.y:.13G}\n")
    f.write(f"{nset},3,{velocity.z:.13G}\n")
    f.write("\n")


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _vec_is_finite(v):
    return all(math.isfinite(c) for c in (float(v.x), float(v.y), float(v.z)))


def _get_inertial_correction_factor(vf_obj):
    factor = getattr(vf_obj, "InertialCorrectionFactor", 1.0)
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        Console.PrintWarning(
            "ConstraintVirtualForces: invalid InertialCorrectionFactor; falling back to 1.0.\n"
        )
        return 1.0

    if not math.isfinite(factor) or factor <= 0.0:
        Console.PrintWarning(
            "ConstraintVirtualForces: non-positive or non-finite InertialCorrectionFactor; "
            "falling back to 1.0.\n"
        )
        return 1.0

    return factor


def _should_emit_corio(vf_obj, omega, relative_velocity, linear_velocity):
    if not _env_bool("FREECAD_FEM_JIG321_ENABLE_CORIO", True):
        return False, "disabled-by-env"

    mode = os.environ.get("FREECAD_FEM_JIG321_CORIO_MODE", "guarded").strip().lower()
    if mode == "legacy":
        return True, "legacy"

    if not (
        _vec_is_finite(omega)
        and _vec_is_finite(relative_velocity)
        and _vec_is_finite(linear_velocity)
    ):
        return False, "nonfinite-kinematics"

    omega_eps = float(os.environ.get("FREECAD_FEM_JIG321_CORIO_OMEGA_EPS", "1.0e-9"))
    relvel_eps = float(os.environ.get("FREECAD_FEM_JIG321_CORIO_RELVEL_EPS", "1.0e-9"))
    if omega.Length <= omega_eps:
        return False, "omega-below-eps"
    if relative_velocity.Length <= relvel_eps:
        return False, "relative-velocity-below-eps"

    require_rel_diff = _env_bool(
        "FREECAD_FEM_JIG321_CORIO_REQUIRE_RELVEL_DIFFERENT_FROM_LINEAR",
        True,
    )
    if require_rel_diff:
        rel_diff_eps = float(os.environ.get("FREECAD_FEM_JIG321_CORIO_RELVEL_DIFF_EPS", "1.0e-9"))
        if (relative_velocity - linear_velocity).Length <= rel_diff_eps:
            return False, "relative-velocity-equals-linear"

    center_of_rotation = getattr(vf_obj, "CenterOfRotation", Vector(0, 0, 0))
    if not _vec_is_finite(center_of_rotation):
        return False, "nonfinite-center-of-rotation"

    return True, "guarded"


def _resolve_decompose_mode(
    accel,
    omega,
    angular_acceleration,
    rel_com,
    is_static,
    decompose_cor_ok,
):
    mode = VF_DECOMPOSE_ACCEL
    if isinstance(mode, bool):
        return mode

    mode_str = str(mode).strip().lower()
    if mode_str in {"1", "true", "yes", "on", "force", "always"}:
        return True
    if mode_str in {"0", "false", "no", "off", "never"}:
        return False

    # Auto mode: keep aggregate COM representation unless rotational split is
    # both significant and numerically trustworthy.
    if not decompose_cor_ok:
        return False

    o_mag = omega.Length
    a_mag = angular_acceleration.Length
    if o_mag <= VF_DECOMPOSE_OMEGA_EPS and (not is_static or a_mag <= VF_DECOMPOSE_ALPHA_EPS):
        return False

    rot_equiv = Vector(0, 0, 0)
    if o_mag > VF_DECOMPOSE_OMEGA_EPS:
        rot_equiv = rot_equiv + omega.cross(omega.cross(rel_com))
    if is_static and a_mag > VF_DECOMPOSE_ALPHA_EPS:
        rot_equiv = rot_equiv + angular_acceleration.cross(rel_com)

    rot_mag = rot_equiv.Length
    if rot_mag <= 0.0:
        return False

    raw_mag = max(accel.Length, 1.0)
    return (
        rot_mag >= VF_DECOMPOSE_AUTO_ROT_ACCEL_MIN
        and (rot_mag / raw_mag) >= VF_DECOMPOSE_AUTO_ROT_ACCEL_RATIO_MIN
    )


def write_meshdata_constraint(f, femobj, vf_obj, ccxwriter):
    body_nodes = sorted(set(femobj.get("BodyNodes", [])))
    if body_nodes:
        f.write(f"*NSET,NSET={vf_body_nodes_name(vf_obj)}\n")
        for node in body_nodes:
            f.write(f"{node},\n")


def write_constraint(f, femobj, vf_obj, ccxwriter, op_new=False):
    if _env_bool("FREECAD_FEM_SKIP_CONSTRAINT_VIRTUAL_FORCES", False):
        f.write(f"** FREECAD_FEM_SKIP_CONSTRAINT_VIRTUAL_FORCES: {vf_obj.Name} loads suppressed\n")
        return

    # op_new: emit OP=NEW on the first *DLOAD line in this step block to
    # clear all distributed loads from the previous step, giving an independent
    # per-load-case result. Only the first *DLOAD in this constraint write
    # carries OP=NEW; subsequent ones do not (CalculiX OP=NEW is additive with
    # loads that follow within the same step block).
    _op_new_pending = [op_new]

    def _dload_hdr():
        h = "*DLOAD, OP=NEW\n" if _op_new_pending[0] else "*DLOAD\n"
        _op_new_pending[0] = False
        return h

    is_static = str(getattr(ccxwriter, "analysis_type", "")).lower() == "static"
    # Short-term mesh/discretisation correction model:
    # - no CoG shift between exact and mesh representations
    # - I_exact / I_mesh == m_exact / m_mesh
    # Under these assumptions, one scalar factor can scale all inertial
    # equivalents emitted to CalculiX (GRAV/CENTRIF/ROTA/CORIO).
    inertial_correction_factor = _get_inertial_correction_factor(vf_obj)

    center_of_mass = getattr(vf_obj, "CenterOfMass", Vector(0, 0, 0))
    center_of_rotation = getattr(vf_obj, "CenterOfRotation", Vector(0, 0, 0))
    rel_com = center_of_mass - center_of_rotation
    rel_com_len = rel_com.Length

    decompose_omega_eps = VF_DECOMPOSE_OMEGA_EPS
    decompose_alpha_eps = VF_DECOMPOSE_ALPHA_EPS
    decompose_cor_radius_min = VF_DECOMPOSE_COR_RADIUS_MIN
    decompose_cor_radius_max = VF_DECOMPOSE_COR_RADIUS_MAX
    decompose_cor_ok = (
        _vec_is_finite(center_of_rotation)
        and decompose_cor_radius_min <= rel_com_len <= decompose_cor_radius_max
    )

    accel = getattr(vf_obj, "LinearAcceleration", Vector(0, 0, 0))
    grav_accel = Vector(accel.x, accel.y, accel.z)
    grav_accel = grav_accel * inertial_correction_factor

    omega = getattr(vf_obj, "AngularVelocity", Vector(0, 0, 0))
    angular_acceleration = getattr(vf_obj, "AngularAcceleration", Vector(0, 0, 0))
    angular_acceleration = angular_acceleration * inertial_correction_factor
    decompose = _resolve_decompose_mode(
        accel,
        omega,
        angular_acceleration,
        rel_com,
        is_static,
        decompose_cor_ok,
    )

    o_mag = omega.Length
    if decompose and decompose_cor_ok and o_mag > decompose_omega_eps:
        # Only emit CENTRIF in decompose mode: in non-decompose mode the full
        # absolute body acceleration (including centrifugal) is already encoded
        # in LinearAcceleration and captured by the GRAV load below.  Emitting
        # CENTRIF without subtracting it from GRAV would double-count the term.
        wrote_centrif = _write_axis_dload(
            f,
            ccxwriter.ccx_eall,
            "CENTRIF",
            inertial_correction_factor * (o_mag**2),
            center_of_rotation,
            omega,
            dload_header_fn=_dload_hdr,
        )
        if wrote_centrif:
            # Keep GRAV orthogonal to explicit centrifugal term.
            grav_accel = grav_accel - (
                inertial_correction_factor * omega.cross(omega.cross(rel_com))
            )

    if (
        decompose
        and is_static
        and decompose_cor_ok
        and angular_acceleration.Length > decompose_alpha_eps
    ):
        # Only emit ROTA in decompose mode: same reason as CENTRIF above.
        wrote_rota = _write_axis_dload(
            f,
            ccxwriter.ccx_eall,
            "ROTA",
            angular_acceleration.Length,
            center_of_rotation,
            angular_acceleration,
            dload_header_fn=_dload_hdr,
        )
        if wrote_rota:
            # Keep GRAV orthogonal to explicit Euler term.
            grav_accel = grav_accel - angular_acceleration.cross(rel_com)
    elif not decompose and is_static and angular_acceleration.Length > 0.0:
        # In non-decompose mode GRAV already carries the full translational
        # D'Alembert term (including the Euler translational component at CM).
        # However the angular-inertia moment  -I·α  is absent from GRAV.
        # Emitting ROTA with its axis through the CM produces zero net body
        # force (axis at CM → net force = α × ∫ρ·r_local dV = 0) and delivers
        # a moment about the CM equal to I·α_applied, where α_applied is the
        # angular acceleration vector used for the ROTA axis.
        # CalculiX ROTA convention: it applies +ρ·(α×r), giving moment +I·α.
        # D'Alembert requires moment −I·α, so we must negate the axis direction.
        _write_axis_dload(
            f,
            ccxwriter.ccx_eall,
            "ROTA",
            angular_acceleration.Length,
            center_of_mass,  # axis through CM → zero net force
            -angular_acceleration,  # negated: ROTA gives +I·α, need −I·α
            dload_header_fn=_dload_hdr,
        )

    relative_velocity = getattr(vf_obj, "RelativeVelocity", Vector(0, 0, 0))
    linear_velocity = getattr(vf_obj, "LinearVelocity", Vector(0, 0, 0))

    allow_linear_fallback = _env_bool("FREECAD_FEM_JIG321_CORIO_ALLOW_LINEAR_FALLBACK", False)
    if allow_linear_fallback and relative_velocity.Length <= 0.0:
        relative_velocity = linear_velocity

    emit_corio = False
    reason = ""
    if decompose and is_static:
        # Only emit CORIO in decompose mode: same reason as CENTRIF/ROTA above.
        emit_corio, reason = _should_emit_corio(vf_obj, omega, relative_velocity, linear_velocity)
        if emit_corio:
            # Keep GRAV orthogonal to explicit Coriolis term.
            grav_accel = grav_accel - (
                inertial_correction_factor * (2.0 * omega.cross(relative_velocity))
            )

    a_mag = grav_accel.Length
    if a_mag > 0.0:
        a_norm = -grav_accel / a_mag
        f.write(_dload_hdr())
        f.write(
            "{},GRAV,{:.13G},{:.13G},{:.13G},{:.13G}\n".format(
                ccxwriter.ccx_eall,
                a_mag,
                a_norm.x,
                a_norm.y,
                a_norm.z,
            )
        )
        f.write("\n")

    if VF_DEBUG_CLOSURE:
        _debug_log_closure_vectors(
            vf_obj,
            center_of_mass,
            center_of_rotation,
            accel,
            grav_accel,
            omega,
            angular_acceleration,
            relative_velocity,
            emit_corio,
            decompose,
        )

    if not is_static:
        return

    if not emit_corio:
        Console.PrintLog("ConstraintVirtualForces: skipping CORIO export (" + reason + ").\n")
        return

    if femobj.get("BodyNodes"):
        velocity_set = vf_body_nodes_name(vf_obj)
    else:
        velocity_set = ccxwriter.ccx_nall
        Console.PrintWarning(
            "ConstraintVirtualForces: Body node set unavailable for Coriolis velocity IC; "
            "falling back to Nall.\n"
        )

    _write_velocity_initial_conditions(f, velocity_set, relative_velocity)
    _write_axis_dload(
        f,
        ccxwriter.ccx_eall,
        "CORIO",
        inertial_correction_factor * (o_mag**2),
        center_of_rotation,
        omega,
        dload_header_fn=_dload_hdr,
    )


def _debug_log_closure_vectors(
    vf_obj,
    center_of_mass,
    center_of_rotation,
    raw_accel,
    grav_accel,
    omega,
    angular_acceleration,
    relative_velocity,
    emit_corio,
    decompose,
):
    """Log effective virtual-forces equivalent vectors in world frame.

    Controlled by VF_DEBUG_CLOSURE module constant. Produces one Console
    message per write_constraint call with all scalar inputs, derived
    equivalent force direction, and decomposition state for closure diagnostics.
    """
    o_mag = omega.Length
    rel_com = center_of_mass - center_of_rotation
    a_mag = grav_accel.Length
    a_norm = (-grav_accel / a_mag) if a_mag > 0.0 else Vector(0, 0, 0)

    # Centrifugal equivalent net force direction (body-force, axis thru COR).
    centrif_equiv = Vector(0, 0, 0)
    if o_mag > 0.0:
        centrif_equiv = -(omega.cross(omega.cross(rel_com)))

    # Euler (ROTA) equivalent net force direction.
    rota_equiv = Vector(0, 0, 0)
    if angular_acceleration.Length > 0.0:
        rota_equiv = -(angular_acceleration.cross(rel_com))

    # Coriolis equivalent net force direction.
    corio_equiv = Vector(0, 0, 0)
    if emit_corio and o_mag > 0.0:
        corio_equiv = -(2.0 * omega.cross(relative_velocity))

    Console.PrintMessage(
        f"[VF-closure] {getattr(vf_obj, 'Name', '?')}\n"
        f"  COM={center_of_mass}  COR={center_of_rotation}  rel_COM={rel_com}\n"
        f"  raw_accel={raw_accel}  grav_accel(after_decompose)={grav_accel}\n"
        f"  GRAV: mag={a_mag:.6g}  dir={a_norm}  (body force = -m*grav_accel)\n"
        f"  CENTRIF: omega={omega}  |omega|={o_mag:.6g}  equiv_net_accel={centrif_equiv}\n"
        f"  ROTA: alpha={angular_acceleration}  |alpha|={angular_acceleration.Length:.6g}"
        f"  equiv_net_accel={rota_equiv}\n"
        f"  CORIO: emit={emit_corio}  v_rel={relative_velocity}  equiv_net_accel={corio_equiv}\n"
        f"  decompose={decompose}\n"
    )

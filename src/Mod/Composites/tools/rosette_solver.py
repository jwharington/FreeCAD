# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Iterative rosette-angle solver for AlignFibreRosette and TransferRosette.

Both features fix a rosette's ``Angle`` by minimising a scalar error that is
a function of the candidate angle. Each evaluation sets the angle, re-drives
the host ``CompositeShell`` (directly, never via a nested recompute), waits
for the shell's draper to be valid, and reads the error back from the draper.

The residual is near-linear in the seed angle: rotating the rosette rotates
the warp field across the draped patch almost rigidly, so a secant through
two true evaluations extrapolates the root in one large step. The remaining
iterations only correct for real drape deviation, re-grounded by one drape
each — there is no blind bracket search re-draping the shell per halving.
"""

from __future__ import annotations

from typing import Callable

import FreeCAD
import math


class RosetteSolveError(RuntimeError):
    """Raised when the iterative solve fails to converge."""


def wrap_angle(angle_deg: float, angle_min_deg: float = -90.0,
               angle_max_deg: float = 90.0) -> float:
    """Fold an angle into the fibre's principal period.

    A fabric's warp direction has no arrow: angle and angle + period are
    the same layup, so an angle solve lives on a circle, not a line.
    Wrapping keeps iterates in the principal period instead of pinning
    them at a clamp bound whenever the root lies beyond it.
    """
    period = angle_max_deg - angle_min_deg
    a = math.fmod(angle_deg - angle_min_deg, period)
    if a < 0.0:
        a += period
    return angle_min_deg + a


def solve_rosette_angle(
    shell,
    rosette,
    error_fn: Callable[[float], float],
    *,
    angle_min_deg: float = -90.0,
    angle_max_deg: float = 90.0,
    angle_tol_deg: float = 0.05,
    residual_tol: float = 1e-3,
    max_iters: int = 40,
) -> float:
    """Find the rosette ``Angle`` that drives ``error_fn(angle)`` to zero.

    Parameters
    ----------
    shell : CompositeShell FeaturePython
        The shell whose drape is re-driven each iteration. Its draper must be
        valid after each recompute.
    rosette : Rosette FeaturePython
        The rosette whose ``Angle`` property is iterated.
    error_fn : callable(float) -> float
        Residual as a function of the candidate angle (degrees). Called after
        each recompute with the angle just applied.
    angle_min_deg, angle_max_deg : float
        Clamp bounds for iterated angles (degrees).
    angle_tol_deg : float
        Convergence tolerance on the angle step.
    residual_tol : float
        Convergence tolerance on the residual magnitude.
    max_iters : int
        Hard iteration cap.

    Returns
    -------
    float
        The converged angle (degrees).

    Raises
    ------
    RosetteSolveError
        If convergence is not reached within ``max_iters``.
    """

    def _eval(angle_deg: float) -> float:
        # Skip no-op writes: assigning the same Angle still touches the
        # rosette, and every touch propagates to dependent shells (and
        # through them to the laminates that resolve this rosette).
        if abs(float(getattr(rosette, "Angle", 0.0) or 0.0) - float(angle_deg)) > 1e-9:
            rosette.Angle = float(angle_deg)
        # Place the rosette LCS for the new angle BEFORE re-driving the
        # shell. FreeCAD's recompute dependency ordering does not always
        # execute the rosette (and thus update its child LCS placement)
        # before the shell reads that LCS as its drape seed, so the shell
        # can re-drape against a stale warp direction. Placing the LCS
        # here guarantees the shell sees the current candidate orientation.
        try:
            rosette.Proxy.execute(rosette)
        except Exception:
            pass
        # Re-drive the host shell's drape DIRECTLY. The solve may run
        # nested inside another object's recompute (e.g. a laminate
        # resolving its transfer angles during execute), and a nested
        # doc.recompute() does not re-execute an object touched within
        # the nested scope — the draper would freeze at the bootstrap
        # angle and the residual would flatline.  Calling the shell's
        # execute drives the drape synchronously; execute() re-runs the
        # full pipeline including any freshness guards, which see the
        # just-updated rosette angle and LCS placement.
        shell.Proxy.execute(shell)
        _require_valid_draper(shell)
        return float(error_fn(angle_deg))

    def _wrap(angle_deg: float) -> float:
        return wrap_angle(angle_deg, angle_min_deg, angle_max_deg)

    # Start from the rosette's current angle: when it already drapes at
    # that angle, the first evaluation costs no re-drape at all — the
    # shell's fingerprint fast path skips the solve.
    lo = _wrap(float(getattr(rosette, "Angle", 0.0) or 0.0))
    f_lo = _eval(lo)
    if abs(f_lo) <= residual_tol:
        return lo

    # Probe once to capture the local slope of the near-linear residual
    # (the rigid-rotation assumption: rotating the rosette rotates the
    # warp field with it), then extrapolate the root in one large step.
    probe = max(2.0, min(10.0, (angle_max_deg - angle_min_deg) / 20.0))
    hi = _wrap(lo + probe)
    f_hi = _eval(hi)
    if abs(f_hi) <= residual_tol:
        return hi

    for _ in range(max_iters):
        rise = f_hi - f_lo
        if rise == 0.0 or hi == lo:
            raise RosetteSolveError(
                f"Residual is flat near [{lo:.4g}, {hi:.4g}] deg "
                f"(f={f_lo:.6g}, {f_hi:.6g}) — cannot extrapolate"
            )
        candidate = _wrap(hi - f_hi * (hi - lo) / rise)
        if abs(candidate - hi) < angle_tol_deg:
            # The root lies within the angle tolerance of the candidate;
            # its residual is within tolerance to first order.
            return candidate
        f_candidate = _eval(candidate)
        if abs(f_candidate) <= residual_tol:
            return candidate
        # Slide the secant window onto the two freshest evaluations.
        lo, f_lo = hi, f_hi
        hi, f_hi = candidate, f_candidate

    raise RosetteSolveError(
        f"Did not converge within {max_iters} iterations "
        f"(last angle {hi:.4g} deg, residual {f_hi:.6g})"
    )


def _require_valid_draper(shell) -> None:
    """Assert the shell's draper is valid after a recompute."""
    proxy = getattr(shell, "Proxy", None)
    if proxy is None or not hasattr(proxy, "get_draper"):
        raise RosetteSolveError(
            f"Shell '{shell.Name}' has no draper proxy"
        )
    try:
        draper = proxy.get_draper()
    except Exception as exc:  # noqa: BLE001 - surface as solve error
        raise RosetteSolveError(
            f"get_draper() failed on '{shell.Name}': {exc}"
        ) from exc
    if draper is None or not draper.is_valid():
        raise RosetteSolveError(
            f"Draper for '{shell.Name}' is not valid after recompute"
        )

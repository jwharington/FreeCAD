# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Iterative rosette-angle solver for AlignFibreRosette and TransferRosette.

Both features fix a rosette's ``Angle`` by minimising a scalar error that is
a function of the candidate angle. Each evaluation sets the angle, re-drives
the host ``CompositeShell`` (via ``Document.recompute()``), waits for the
shell's draper to be valid, and reads the error back from the draper.

The solver is a bounded secant/bisection root-find over an angle range
(default ``[-90, 90]`` degrees). Because the warp field rotates monotonically
with the rosette angle on a single connected patch, one root exists in the
range; the bracket is refined until the angle step or the residual drops below
its tolerance.
"""

from __future__ import annotations

from typing import Callable

import FreeCAD


class RosetteSolveError(RuntimeError):
    """Raised when the iterative solve fails to converge."""


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
        Bracket bounds (degrees).
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
        If no sign change is found in the bracket or convergence is not reached
        within ``max_iters``.
    """
    doc = shell.Document

    def _eval(angle_deg: float) -> float:
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
        # Force a genuine re-solve (not a stale rehydrate): the persisted
        # cache (_can_use_persisted) can short-circuit to a rehydrate that
        # leaves _backend pointing at the previous angle's data.
        try:
            shell._LastRosetteAngle = float(angle_deg) + 999.0
        except Exception:
            pass
        shell.touch()
        doc.recompute()
        _require_valid_draper(shell)
        return float(error_fn(angle_deg))

    lo = float(angle_min_deg)
    hi = float(angle_max_deg)
    f_lo = _eval(lo)
    f_hi = _eval(hi)

    if f_lo == 0.0:
        return lo
    if f_hi == 0.0:
        return hi
    if f_lo * f_hi > 0.0:
        raise RosetteSolveError(
            f"No sign change in [{lo}, {hi}] deg "
            f"(f(lo)={f_lo:.6g}, f(hi)={f_hi:.6g})"
        )

    # Bracket refinement: bisection (robust) with a secant guess mixed in.
    for _ in range(max_iters):
        mid = 0.5 * (lo + hi)
        if abs(hi - lo) < angle_tol_deg:
            return mid
        # Secant guess, kept inside the bracket.
        if (f_hi - f_lo) != 0.0:
            secant = lo - f_lo * (hi - lo) / (f_hi - f_lo)
        else:
            secant = mid
        if not (lo < secant < hi):
            secant = mid
        candidate = secant
        f_c = _eval(candidate)
        if abs(f_c) < residual_tol:
            return candidate
        if f_lo * f_c < 0.0:
            hi, f_hi = candidate, f_c
        else:
            lo, f_lo = candidate, f_c

    raise RosetteSolveError(
        f"Did not converge within {max_iters} iterations "
        f"(bracket [{lo:.4f}, {hi:.4f}] deg)"
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

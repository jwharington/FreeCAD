# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Repro loop for the fine-pitch `solver_failure` flake (known-issues).

The seam example (cyl_sphere_seam) intermittently fails its drape with
`solver_failure` at DrapePitch <= 2.5 mm while the identical geometry
solves at coarse pitch. nextdrape's own pitch-sweep regression tests do
not reproduce the flake; this tool drives the *production* drape path —
the exact cap face from the example, the exact rosette seed rule, and
the exact NextDrapeBackend call — many times per pitch and reports every
failure, so the failure can be characterised at FreeCAD scale and then
extracted into a nextdrape-side pin.

For each solve the loop mimics the example: a fresh engine (each
CompositeShell owns one backend per solve) over the shared per-process
state, with an optional warm-up drape of the cylinder panel first (the
example drapes the panel before the cap, warming the solver's face
cache).

Usage:
    FreeCADCmd -c "exec(open('.../inspect_fine_pitch_flake.py').read())"
    with env FLAKE_ARGS, e.g.
    FLAKE_ARGS="--pitches 2.5,2.0,1.5 --repeats 20 --warm-panel --angles 0,41"

Exits non-zero when any solve fails (usable as a loop-driver target).
"""

import argparse
import os
import shlex
import sys


def _repo_build_mod():
    """Locate the build-tree Mod directory holding the Composites package.

    Primary: the running FreeCAD's own build prefix (Mod sits next to
    bin/). Fallback: this file's source location, when __file__ exists.
    """
    import FreeCAD
    home = FreeCAD.getHomePath()
    if home and os.path.isdir(os.path.join(home, "Mod", "Composites")):
        return os.path.join(home, "Mod")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(
        os.path.join(here, "..", "..", "..", "..", "build", "debug", "Mod")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pitches", default="2.5,2.0,1.5,1.0")
    parser.add_argument("--angles", default="0,41")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--warm-panel", action="store_true",
                        help="drape the cylinder panel once per pitch first, "
                             "like the example does before the cap")
    args = parser.parse_args(shlex.split(os.environ.get("FLAKE_ARGS", "")))

    sys.path.insert(0, _repo_build_mod())

    import FreeCAD
    from Composites.compositeexamples.examples.cyl_sphere_seam import (
        _cylinder_panel,
        _spherical_cap,
    )
    from Composites.features.Rosette import _frame_rotation
    from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

    pitches = [float(p) for p in args.pitches.split(",")]
    angles = [float(a) for a in args.angles.split(",")]

    cap = _spherical_cap()
    panel = _cylinder_panel()

    class _Params:
        """Lightweight pitch carrier, as run_drape_task passes the backend."""

        def __init__(self, pitch):
            self.pitch = float(pitch)

    class _LcsStub:
        """LCS stand-in feeding NextDrapeBackend._build_seed exactly as the
        rosette's Part::LocalCoordinateSystem would."""

        def __init__(self, face, angle_deg):
            position, rotation = _frame_rotation(face, angle_deg)
            self.Placement = FreeCAD.Placement(position, rotation)

    failures = 0
    total = 0
    print(f"# fine-pitch flake probe: pitches={pitches} angles={angles} "
          f"repeats={args.repeats} warm_panel={args.warm_panel}")

    for pitch in pitches:
        if args.warm_panel:
            warm_backend = NextDrapeBackend(_Params(pitch), None, panel)
            warm_result = warm_backend._run_solve()
            print(f"# warm panel @ pitch {pitch}: "
                  f"success={warm_result.get('success')}")
        for angle in angles:
            lcs = _LcsStub(cap, angle)
            for i in range(args.repeats):
                total += 1
                backend = NextDrapeBackend(_Params(pitch), lcs, cap)
                result = backend._run_solve()
                ok = bool(result.get("success"))
                if not ok:
                    failures += 1
                diag = result.get("diagnostics", {})
                status = (
                    "ok"
                    if ok
                    else str(result.get("error", "solver_failure"))
                )
                print(
                    f"pitch={pitch:<5} angle={angle:<5} rep={i:<4} "
                    f"{status:<28} nodes={diag.get('total_nodes', 0):<5} "
                    f"quads={len(result.get('quads', [])):<5} "
                    f"coverage={diag.get('coverage_ratio', 0.0):.3f} "
                    f"t={result.get('solve_time_ms', 0.0):.0f}ms"
                )

    print(f"# summary: {failures}/{total} failures")
    return 1 if failures else 0


main()

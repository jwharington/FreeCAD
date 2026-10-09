# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Where the mixed wing's wall time actually goes, stage by stage.

The suspicion this exists to test is that mesh handling costs far more than
the solve, and that is a measurement, not an opinion: a suspicion of this kind
gets acted on, and acting on the wrong half wastes the work.

It reports wall time for every stage that can be separated, with the share of
the total, and no stage is inferred from another. In particular the three
things the mixed route does to a mesh are timed apart, because they fail
differently:

* generating each part's mesh (gmsh, one process per part);
* merging the parts (Python, and the step that turned out to be quadratic);
* writing the deck (element sets and sections, Python).

The last two are the ones with no external excuse for being slow, so they are
the ones worth seeing in isolation.

Usage:
    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_wing_pipeline_cost.py
    with args, e.g. --repeats 3
"""

import argparse
import sys
import time

import FreeCAD

from femexamples.meshes import merged_mesh
from femmesh import meshtools

from Composites.compositeexamples.examples import _shell_example_common as shell_common
from Composites.compositeexamples.examples import mixed_shell_solid_wing as wing


def _stage(label, fn, timings):
    """Run one stage, record its wall time, and print it as it finishes."""
    start = time.perf_counter()
    value = fn()
    timings[label] = time.perf_counter() - start
    print(f"  {label:<26} {timings[label]:8.2f} s", flush=True)
    return value


def measure(repeats=1):
    """Run the wing pipeline, timing each stage. Returns the timing dict."""
    timings = {}
    doc = None
    try:
        doc = FreeCAD.newDocument("WingPipelineCost")

        # Geometry and draping are separated because they are different kinds
        # of cost: geometry is OCCT, draping drives the nextdrape solver.
        upper, lower = wing.naca4_ordinates(
            wing.NACA_CAMBER,
            wing.NACA_CAMBER_POSITION,
            wing.NACA_THICKNESS,
            wing.CHORD_MM,
            wing.SURFACE_INTERVALS,
        )
        core = _stage("geometry.core", lambda: wing._make_core(doc), timings)
        upper_support = _stage(
            "geometry.upper_support",
            lambda: wing._make_skin_support(doc, "WingUpperSkinSupport", upper),
            timings,
        )
        lower_support = _stage(
            "geometry.lower_support",
            lambda: wing._make_skin_support(doc, "WingLowerSkinSupport", lower),
            timings,
        )
        upper_skin, _ = _stage(
            "drape.upper",
            lambda: wing._make_skin(doc, upper_support, "WingUpperSkin"),
            timings,
        )
        lower_skin, _ = _stage(
            "drape.lower",
            lambda: wing._make_skin(doc, lower_support, "WingLowerSkin"),
            timings,
        )

        tag = "WingPipelineCost"
        analysis, solver, mesh_obj = _stage(
            "fem.analysis_base",
            lambda: wing._create_fem_base(doc, tag),
            timings,
        )
        _stage(
            "fem.sections_and_loads",
            lambda: _sections_and_loads(doc, analysis, core, upper_support, lower_support,
                                        upper_skin, lower_skin, tag),
            timings,
        )

        # Mesh generation and merging, apart. mesh_parts_separately does both,
        # and they are the two stages this tool exists to separate.
        parts = [core, upper_support, lower_support]
        generated = []
        for index, part in enumerate(parts):
            generated.append(
                _stage(
                    f"mesh.gmsh[{part.Name}]",
                    lambda part=part, index=index: merged_mesh._meshed_part(
                        doc, index, part, wing.MESH_SIZE_MM, "2nd", 0
                    ),
                    timings,
                )
            )
        merged = _stage(
            "mesh.merge",
            lambda: _merge_all(generated),
            timings,
        )
        mesh_obj.FemMesh = merged

        fem = shell_common._ccx_tools(analysis, solver, mesh_obj)
        _stage("deck.write", lambda: fem.write_inp_file(), timings)
        _stage("solve.ccx", lambda: fem.start_ccx(), timings)
        _stage("results.load", lambda: fem.load_results(), timings)
    finally:
        if doc is not None:
            FreeCAD.closeDocument(doc.Name)
    return timings


def _sections_and_loads(doc, analysis, core, upper_support, lower_support, upper_skin,
                        lower_skin, tag):
    lower_face, upper_face = wing._lateral_face_names(core)
    shell_common._add_shell_section_and_material(
        doc, analysis, upper_support, f"{tag}_UpperSkin", shell_obj=upper_skin
    )
    shell_common._add_shell_section_and_material(
        doc, analysis, lower_support, f"{tag}_LowerSkin", shell_obj=lower_skin
    )
    wing._add_core_material(doc, analysis, core, tag)
    wing._add_load_case(doc, analysis, core, tag)
    wing._add_tie(doc, analysis, upper_support, core, upper_face, f"{tag}_Upper")
    wing._add_tie(doc, analysis, lower_support, core, lower_face, f"{tag}_Lower")


def _merge_all(generated):
    """The merge half of mesh_parts_separately, so it can be timed alone."""
    merged = generated[0][1]
    for _, extra in generated[1:]:
        merged, _, _ = meshtools.merge_femmeshes(merged, extra)
    return merged


def report(timings):
    total = sum(timings.values())
    print("\n  stage                               seconds     share", flush=True)
    for label, seconds in sorted(timings.items(), key=lambda kv: -kv[1]):
        print(f"  {label:<26} {seconds:9.2f} {100.0 * seconds / total:8.1f}%", flush=True)
    print(f"  {'TOTAL':<26} {total:9.2f}", flush=True)

    mesh_side = sum(v for k, v in timings.items() if k.startswith("mesh."))
    solve_side = sum(v for k, v in timings.items() if k.startswith(("solve.", "deck.")))
    print(
        f"\n  mesh handling (gmsh + merge) {mesh_side:8.2f} s "
        f"({100.0 * mesh_side / total:.1f}%)",
        flush=True,
    )
    print(
        f"  deck + solve                 {solve_side:8.2f} s "
        f"({100.0 * solve_side / total:.1f}%)",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=1, help="how many times to run")
    args = parser.parse_args()

    if args.repeats < 1:
        # A zero-run measurement silently reports nothing, which reads as
        # "instant" rather than as a mistake.
        parser.error("--repeats must be at least 1")

    for run_index in range(args.repeats):
        print(f"\n=== run {run_index + 1}/{args.repeats} ===", flush=True)
        timings = measure()
        report(timings)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    main()

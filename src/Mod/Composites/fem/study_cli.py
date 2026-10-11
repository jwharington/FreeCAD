# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The command line and entry point every shell FEM study shares.

A study is geometry, load cases, materials and hooks; this module is the
run-time surface in front of them.  It owns the flags a run needs whatever
it is studying — which cases go in the deck, how fine the mesh is, which
solves to attempt, where the report goes — and a study adds the flags only
it understands through ``add_arguments(parser)`` and applies them, with the
common ones, through ``configure(args)``.

Building the ``Run`` and performing it live here too: build -> mesh -> deck
-> solve -> report is the driver's sequence, and a study has no reason to
repeat it.  A study that declares no flags of its own is still runnable.
"""

import argparse
import time

from . import study_driver


# The six resultant components a load case is stated in.  DECK order, so a
# ``--load`` value names the same component everywhere.
COMPONENTS = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")


def parse_load_overrides(items):
    """``--load COMP=VALUE`` arguments as a ``{component: float}`` dict.

    A component is case-insensitive; an entry that is not ``COMP=VALUE``, or
    names a component outside the six, is refused rather than dropped — a
    silently ignored override writes a valid-looking deck that does not
    carry what the command line asked for.
    """
    canonical = {comp.lower(): comp for comp in COMPONENTS}
    overrides = {}
    for item in items:
        component, _, value = item.partition("=")
        component = canonical.get(component.strip().lower())
        if component is None or not value:
            raise RuntimeError("--load %r is not COMP=VALUE with COMP in %s"
                               % (item, ", ".join(COMPONENTS)))
        overrides[component] = float(value)
    return overrides


def selected_cases(cases, one, subset):
    """The load cases to put in the deck, in deck order.

    ``subset`` (comma separated, deck order) wins over ``one``, and the
    special value ``"all"`` means every case in ``cases``.  Deck order is
    case order, and the results come back in that order, so the two must not
    diverge.
    """
    if subset is not None:
        names = [name.strip() for name in subset.split(",") if name.strip()]
        if not names:
            raise RuntimeError("--cases names no case: %r" % subset)
    elif one == "all":
        names = list(cases)
    else:
        names = [one]
    unknown = sorted({name for name in names if name not in cases})
    if unknown:
        raise RuntimeError("load case %s %s not in %s"
                           % (", ".join(unknown),
                              "is" if len(unknown) == 1 else "are",
                              ", ".join(cases)))
    return names


def refinement(spec):
    """One ``--refine-at`` value as ``(x, y, z, radius, size)`` floats."""
    values = [float(value) for value in spec.split(",")]
    if len(values) != 5:
        raise RuntimeError("--refine-at %r is not x,y,z,radius,size" % spec)
    return tuple(values)


def build_parser(study):
    """The argument parser for a study: the common flags plus its own.

    ``study.add_arguments`` is called last, so a study's flags sit beside the
    common ones and it can read anything the common ones set.
    """
    parser = argparse.ArgumentParser(
        description="Run a %s shell FEM study." % study.name,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=sorted(study.variants()),
                        help="which named variant of this geometry to solve; "
                             "omitted means the study's own defaults")
    parser.add_argument("--case", default="all", metavar="lcNN|all",
                        help="one case, or all (default) for one deck "
                             "carrying every case as its own step")
    parser.add_argument("--cases", metavar="lcNN,...",
                        help="explicit subset, in deck order (wins over "
                             "--case)")
    parser.add_argument("--load", action="append", default=[],
                        metavar="COMP=VALUE",
                        help="override one load component of one case")
    parser.add_argument("--out-dir", help="where the log and report go "
                                          "(default: ./fem-results)")
    parser.add_argument("--remesh", action="store_true",
                        help="ignore a cached mesh and cut a new one")
    parser.add_argument("--mesh-cache",
                        help="where cached meshes live (default: the "
                             "standard cache)")
    parser.add_argument("--no-mesh-cache", action="store_true",
                        help="never read or write the mesh cache")
    parser.add_argument("--gmsh", help="gmsh executable to mesh with")
    parser.add_argument("--mesh-max", type=float, default=60.0, metavar="MM",
                        help="gmsh far-field element size in mm (default 60)")
    parser.add_argument("--mesh-min", type=float, default=5.0, metavar="MM",
                        help="gmsh smallest element size in mm (default 5)")
    parser.add_argument("--refine-at", action="append", default=[],
                        metavar="X,Y,Z,RADIUS,SIZE",
                        help="local refinement sphere: centre (mm), radius "
                             "and element size inside it; repeatable")
    parser.add_argument("--modes", type=int, default=study_driver.DEFAULT_MODES,
                        help="buckling modes per case")
    parser.add_argument("--frequency-modes", type=int,
                        default=study_driver.DEFAULT_FREQUENCIES,
                        help="natural frequencies to solve for")
    parser.add_argument("--buckling", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="also solve for lambda (default: on)")
    parser.add_argument("--frequency", action=argparse.BooleanOptionalAction,
                        default=False,
                        help="also solve for natural frequencies "
                             "(default: off)")
    parser.add_argument("--mass", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="report the article's mass (default: on)")
    parser.add_argument("--model-only", action="store_true",
                        help="build and save the model, then stop: no mesh, "
                             "no deck, no solve — a geometry review run")
    study.add_arguments(parser)
    return parser


def parse_args(study, argv=None):
    """The run's arguments, validated.

    The common flags are resolved here (which cases, which overrides, which
    mesh refinements); a study's own flags are added by
    ``study.add_arguments`` and applied, together with the common ones, by
    ``study.configure(args)``.
    """
    parser = build_parser(study)
    args = parser.parse_args(argv)
    if args.modes < 1:
        raise RuntimeError("--modes %d: at least one mode is required"
                           % args.modes)
    if args.frequency_modes < 1:
        raise RuntimeError("--frequency-modes %d: at least one mode is "
                           "required" % args.frequency_modes)
    if args.case != "all" and args.cases:
        raise RuntimeError("--case and --cases cannot both be given; "
                           "--cases already states the order")
    cases = selected_cases(study.cases(), args.case, args.cases)
    overrides = parse_load_overrides(args.load)
    if len(cases) > 1 and overrides:
        # A component override names one load case.  Applied to a deck it
        # would silently reach the first case only, so it is refused rather
        # than quietly half-applied.
        raise RuntimeError(
            "--load %s overrides one load case and cannot be combined with "
            "a %d-case deck — drop the override or run one case"
            % (", ".join(sorted(overrides)), len(cases)))
    args.selected_cases = cases
    args.load_overrides = overrides
    args.refinements = [refinement(spec) for spec in args.refine_at]
    return args


def build_run(study, args):
    """The :class:`~Composites.fem.study_driver.Run` a command line describes."""
    run = study_driver.Run(
        study, variant=args.variant, cases=args.selected_cases,
        out_dir=args.out_dir, buckling=args.buckling, modes=args.modes,
        frequency=args.frequency, frequency_modes=args.frequency_modes,
        mass=args.mass, remesh=args.remesh, cache=not args.no_mesh_cache,
        cache_root=args.mesh_cache, gmsh=args.gmsh,
        mesh_max=args.mesh_max, mesh_min=args.mesh_min,
        refinements=args.refinements)
    # The stack model is deliberately outside the mesh signature (a layup
    # iteration keeps its mesh), so a study states what else defined its
    # run here or two runs differing only in stack model read as twins.
    run.provenance.update(study.provenance())
    return run


def main(study, argv=None):
    """Parse a study's command line, run it, and write its artifact."""
    args = parse_args(study, argv)
    study.configure(args)
    run = build_run(study, args)
    if args.model_only:
        # Build and save through the study's own path — the same build a
        # solving run runs — then stop before any mesh or deck work.
        started = time.time()
        run.study.build(run.geometry_arguments)
        study_driver.log("model-only: geometry built in %.1fs"
                         % (time.time() - started))
        return None
    report = study_driver.solve(run)
    study_driver.write_artifact(run, report)
    study_driver.log("report: %s" % run.artifact_path)
    return report

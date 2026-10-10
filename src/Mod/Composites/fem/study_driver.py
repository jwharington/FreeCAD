"""Driving a shell FEM study: geometry in, signed mesh, decks, results, report.

Everything here is about the mechanics of a run and none of it is about a
fuselage. What a study has to provide is the things only it knows, and the
whole of this module is written against them:

    build(arguments)        a document holding the geometry, from arguments
    geometry_arguments()    the arguments the geometry was cut from
    parts(doc)              {name: shape} for the geometry a hotspot lands on
    constraints(doc, analysis)  the boundary conditions, created idempotently
    snapshot(case)          the writer's per-step load snapshot for one case
    deck_audit(doc, deck)   (rows, problems) for the deck against the model
    mass_report(doc, deck)  the article's mass, weighed from the deck
    part_clouds(doc, deck, parts)  the deck nodes each part owns
    run_paths(out_dir, name, variant, cases)  (log, artifact) for one run

The last four are the study's naming and geography — which objects are
sections, how a member is named in the deck, where its results go — handed to
the driver as calls, so no module outside the study has to know them.  A study
also names its `mesh_name`, and may offer `laminates(doc)` when its material
reaches the deck through laminate objects rather than section properties.

The reason for drawing the line there is that these are exactly the things a
new geometry answers differently, and everything on this side of the line —
how a mesh is signed and cached, how a deck is written and audited, how a
*CLOAD block is read back to prove the loads arrived, how strain exposure and
lambda are combined into one governing answer — is independent of any one
fuselage.

Output goes where it is told. The default is a directory beside the caller's
working directory, never /tmp: /tmp fills up, is wiped, and on this machine is
96% full, and a run whose artefacts are undiscoverable cannot be re-summarised
a week later.
"""

import argparse
import json
import os
import shutil
import subprocess
import time

import FreeCAD
import Fem
import numpy as np
import ObjectsFem
import Part
from feminout import ccxdat
from femmesh import gmshtools, meshcache, meshsignature
from femtools import checksanalysis
from femtools import deckcheck
from femtools import modelmass
from femtools import partexposure
from femresult import failuremodels

from Composites.compositeexamples.examples._shell_example_common import (
    _add_analysis_member, _ccx_tools, _mesh_has_shell_or_volume_elements,
    _set_constraint_refs)


PREFIX = "[fem]"
DEFAULT_MODES = 5
# How many natural frequencies to ask for.  Nothing about the article's
# response to anything a person can hear lives above the first half dozen,
# and the first eight is where a shell airframe stops being interesting.
DEFAULT_FREQUENCIES = 8



def log(message):
    print("[fem] %s" % message, flush=True)



def gmsh_binary(configured=None):
    """Where gmsh is, resolved rather than assumed.

    An executable location is a fact about the machine, not a choice about the
    analysis, so it is not one of the run-time options this project keeps off
    the environment — but a home directory spelled into the source is still a
    lie about every other machine. Argument first, then FreeCAD's own
    preference, then PATH; a run that finds neither says so instead of meshing
    with whatever gmsh happens to be near.
    """
    preference = FreeCAD.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/Fem/Gmsh").GetString("gmshBinaryPath")
    for candidate in (configured, preference, shutil.which("gmsh")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("no gmsh found: pass --gmsh PATH, or configure it under "
                       "Edit > Preferences > FEM > Meshing")


def _ensure_mesh(mesh_obj, remesh=False, gmsh_path=None,
                 mesh_max=60.0, mesh_min=5.0):
    """The gmsh shell mesh; regenerate when empty or asked.

    ``mesh_max``/``mesh_min`` are gmsh's far-field and smallest element
    sizes (mm).  The mesh signature covers every mesh property, so a
    refined mesh cannot be served from a coarser run's cache.
    """
    if remesh:
        mesh_obj.FemMesh = Fem.FemMesh()  # drop the old mesh
    if _mesh_has_shell_or_volume_elements(mesh_obj):
        log("mesh: %d nodes, %d faces (existing)"
             % (mesh_obj.FemMesh.NodeCount, mesh_obj.FemMesh.FaceCount))
        return
    log("mesh: regenerating gmsh shell mesh (max %.4g mm, min %.4g mm)..."
         % (mesh_max, mesh_min))
    mesh_obj.ElementDimension = "2D"
    mesh_obj.CharacteristicLengthMax = mesh_max
    mesh_obj.CharacteristicLengthMin = mesh_min
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Gmsh").SetString(
        "gmshBinaryPath", gmsh_binary(gmsh_path))
    t0 = time.time()
    gmshtools.GmshTools(mesh_obj).run(True)
    if not _mesh_has_shell_or_volume_elements(mesh_obj):
        raise RuntimeError("gmsh produced an empty mesh")
    log("mesh: %d nodes, %d faces in %.1fs"
         % (mesh_obj.FemMesh.NodeCount, mesh_obj.FemMesh.FaceCount,
            time.time() - t0))


def _apply_mesh_shapes(mesh_obj, refinements, size_out):
    """Local refinement spheres, as ``Fem::MeshShape`` size fields.

    ``refinements`` are ``(x, y, z, radius, size)`` tuples in mm: a sphere
    of ``size`` inside a ``radius`` ball, transitioning to the far-field
    (``size_out``) beyond ``radius + thickness``.  Each object is named for
    its spec: the mesh signature renders a refinement by name, so two
    refinements must differ in name to be told apart, and an unnamed one
    would let a finer run reuse a coarser mesh.
    """
    doc = mesh_obj.Document
    for x, y, z, radius, size in refinements:
        name = ("Refine_x%.6g_y%.6g_z%.6g_r%.6g_s%.6g"
                % (x, y, z, radius, size))
        if doc.getObject(name) is not None:
            continue
        shape = ObjectsFem.makeMeshShape(doc, mesh_obj, name=name)
        shape.ShapeType = "Sphere"
        shape.SphereCenter = FreeCAD.Vector(x, y, z)
        shape.SphereRadius = radius
        shape.SizeIn = size
        shape.SizeOut = size_out
        shape.Thickness = radius


def _uncull_fem_views(doc):
    """Shell meshes render one-sided by default; culling off (GUI only)."""
    if not FreeCAD.GuiUp:
        return
    for obj in doc.Objects:
        vo = getattr(obj, "ViewObject", None)
        if vo is not None and "BackfaceCulling" in vo.PropertiesList \
                and vo.BackfaceCulling:
            vo.BackfaceCulling = False
            log("backface culling off: %s" % obj.Name)


def _box_gap(point, box):
    """How far a point is from a bounding box.

    Never more than the distance to what is inside it, which is what makes it
    safe to skip a part on.
    """
    gaps = [max(box.XMin - point[0], 0.0, point[0] - box.XMax),
            max(box.YMin - point[1], 0.0, point[1] - box.YMax),
            max(box.ZMin - point[2], 0.0, point[2] - box.ZMax)]
    return sum(gap * gap for gap in gaps) ** 0.5


def _nearest_part(point, parts, tolerance=1e-6):
    """The part whose geometry sits nearest a position, "" if there is none.

    A point on the boundary between two parts belongs to both and names both.
    """
    if point is None or not parts:
        return ""
    vertex = Part.Vertex(FreeCAD.Vector(*tuple(point)[:3]))
    distances, best = {}, None
    for name, shape in parts.items():
        gap = _box_gap(point, shape.BoundBox)
        if best is not None and gap > best:
            continue
        found = shape.distToShape(vertex)[0]
        distances[name] = found
        if best is None or found < best:
            best = found
    return "+".join(name for name in sorted(distances)
                    if distances[name] <= best + tolerance)


def _position_text(point):
    """Where a value sits, in the one form every report line uses — or nothing
    at all, which the case line then reports by node instead."""
    return "at (%.1f, %.1f, %.1f)" % tuple(point)[:3] if point is not None else ""


def _exposure_summary(result_obj, parts, coords=None, clouds=None):
    """Per-node maximum-strain exposure from one result increment.

    The design criterion is MAXIMUM STRAIN (femresult.failuremodels.
    calc_failure_maximum_strain): per node, the max of the 12
    tension/compression strain ratios against the design strains
    (stretch 3.2e-3, compression 2.7e-3, shear 5.3e-3 — the module's
    defaults, unitless). Exposure is that max ratio over components and nodes
    (bigger = worse); its reciprocal is the load multiplier. Vectorized over
    all nodes directly.

    A row's position comes from the result's own expanded mesh, whose node
    numbers `NodeNumbers` gives. It is not looked up in the model mesh (which
    holds none of the through-thickness points) nor by the frd's node
    numbering, which orders the same points differently — measured on a real
    two-case deck by check_frd_node_table.py.
    """
    o = failuremodels.default_options
    limits = np.array([
        [o["sxxt"], -o["sxxc"]],
        [o["sxxt"], -o["sxxc"]],
        [o["sxxt"], -o["sxxc"]],
        [o["sxy"], -o["sxy"]],
        [o["sxy"], -o["sxy"]],
        [o["sxy"], -o["sxy"]],
    ])

    try:
        strain = np.vstack([
            result_obj.NodeStrainXX, result_obj.NodeStrainYY,
            result_obj.NodeStrainZZ, result_obj.NodeStrainXY,
            result_obj.NodeStrainXZ, result_obj.NodeStrainYZ,
        ]).transpose()
    except AttributeError as error:
        log("exposure: no strain field to read — %s" % error)
        return {}
    if not len(strain):
        log("exposure: the result holds no strain rows")
        return {}
    ratio_pos = (strain > 0) * strain / limits[:, 0]
    ratio_neg = (strain < 0) * strain / limits[:, 1]
    utilization = np.max(np.hstack([ratio_pos, ratio_neg]), axis=1)
    hotspot = int(np.argmax(utilization))
    # The array runs over the expanded mesh CalculiX numbered itself, and no
    # deck declares those numbers, so no node number is reported. What the
    # value does own is a position, and the model's geometry says which part
    # that position is on — the deck cannot, having grouped by laminate.
    hotspot_point = None
    reason = ""
    ids = getattr(result_obj, "NodeNumbers", None)
    nodes = result_obj.Mesh.FemMesh.Nodes if result_obj.Mesh else {}
    if len(nodes) != len(strain):
        # The arrays and the mesh must be the same node list. When they are not,
        # an id lookup silently returns another point or nothing at all, and a
        # hotspot three metres away looks exactly like a hotspot.
        reason = ("the result mesh holds %d nodes for %d strain rows"
                  % (len(nodes), len(strain)))
    elif ids is None:
        reason = "the result carries no NodeNumbers at all"
    elif len(ids) != len(strain):
        reason = ("NodeNumbers holds %d ids for %d strain rows" % (len(ids),
                                                                   len(strain)))
    elif int(ids[hotspot]) not in nodes:
        reason = ("node %s is not on the result mesh (%d nodes)"
                  % (ids[hotspot], len(nodes)))
    else:
        hotspot_point = nodes[int(ids[hotspot])]
    if reason:
        log("exposure: no hotspot position — %s" % reason)
    where = _position_text(hotspot_point)
    report = {
        # Two numbers, one reciprocal of the other, named for what they are
        # (Composites CONTEXT.md, "Structural verification"): the exposure
        # factor is demand over capacity and fails above 1, the load
        # multiplier is how much of the applied load survives and fails
        # below 1.  Calling the second one an exposure factor inverts the
        # test, which is how 0.723 came to be read as a pass on a structure
        # whose exposure factor is 1.383.
        "strain_exposure_max": float(utilization.max()),
        "hotspot_point": (tuple(hotspot_point)[:3]
                          if hotspot_point is not None else None),
        "hotspot_part": _nearest_part(hotspot_point, parts),
    }
    log("exposure: strain exposure factor max %.3g%s%s"
         % (report["strain_exposure_max"],
            " " + where if where else "",
            " in %s" % report["hotspot_part"] if report["hotspot_part"] else ""))
    if clouds and not reason:
        _part_exposures(utilization, ids, nodes, clouds, report)
    return report


def _part_exposures(utilization, ids, nodes, clouds, report):
    """Worst exposure per member of the meshed structure, into ``report``.

    The global hotspot names one part; the part table says what every other
    part is carrying, which is the answer to "how much is the bay box
    taking" without a rerun per part.  Positions come from the result's own
    expanded mesh as the hotspot's do, so they share the same gate: when
    the hotspot has no position, no node gets attributed either.
    """
    positions = np.array([tuple(nodes[int(node_id)])[:3]
                          for node_id in ids])
    assignment, unclaimed = partexposure.assign(positions, clouds)
    if unclaimed:
        log("exposure: %d of %d result nodes sit further than %.0f mm from "
            "every member — they belong to no part and no part's worst "
            "includes them"
            % (unclaimed, len(positions), partexposure._UNREACHED_MM))
    by_part = partexposure.maxima(utilization, assignment)
    report["exposure_by_part"] = by_part
    ranked = sorted(by_part.items(), key=lambda item: -item[1])
    log("exposure by part: %s" % "; ".join(
        "%s %.3f" % (name, value) for name, value in ranked[:6]))


def _result_objects(analysis, expected):
    """The result increments of a solve, in step order.

    ccx writes one result block per increment and the frd importer keys them
    by cumulative time, which advances every step — so one increment per
    step means the group order is the step order.  The count is asserted,
    never binned: mapping cases onto results by even bins (what the Assembly
    workbench does) would report a case against the wrong numbers.
    """
    results = [o for o in analysis.Group
               if o.isDerivedFrom("Fem::FemResultObject")]
    if len(results) != expected:
        raise RuntimeError(
            "%d load case%s but %d result increment%s — the case-to-result "
            "mapping is undefined, refusing to guess"
            % (expected, "" if expected == 1 else "s", len(results),
               "" if len(results) == 1 else "s"))
    return results


def _max_displacement(result_obj):
    lengths = getattr(result_obj, "DisplacementLengths", None)
    if not lengths:
        return None
    return max(float(v) for v in lengths)


def _dat_of(inp_file):
    """The ``.dat`` beside a deck — where CalculiX states its factors."""
    return os.path.splitext(inp_file)[0] + ".dat"


def _frd_of(inp_file):
    """The ``.frd`` beside a deck — where the nodes ccx solved at are listed."""
    return os.path.splitext(inp_file)[0] + ".frd"


def _sta_of(inp_file):
    """The ``.sta`` beside a deck — where CalculiX records each step."""
    return os.path.splitext(inp_file)[0] + ".sta"


def _retain_results(run, inp_file):
    """Keep a solved deck's CalculiX fields beside the run log.

    The working directory is temporary and is removed when the document
    closes, so the ``.frd`` — the solver's own field, where a post-process
    or a picture of the stress comes from — would vanish with it.
    """
    destination = run.log_path + ".results"
    os.makedirs(destination, exist_ok=True)
    for path in (inp_file, _frd_of(inp_file), _dat_of(inp_file)):
        if os.path.exists(path):
            shutil.copy2(path, destination)
    return destination


def _retain_failing_deck(run, inp_file):
    """Keep the deck of a failed solve beside the run's log.

    The solver writes its deck into a temporary working directory that is
    removed when the document closes, so a deck ccx rejected is gone with
    it and there is nothing left to inspect.  Copy the deck and CalculiX's
    own state files out before that happens.
    """
    destination = run.log_path + ".failing-deck"
    os.makedirs(destination, exist_ok=True)
    for path in (inp_file, _sta_of(inp_file), _dat_of(inp_file)):
        if os.path.exists(path):
            shutil.copy2(path, destination)
    return destination


def _mode_tail_text(factors):
    """Everything after λ₁: λ₂, then the rest as a range.

    Only mode 1 is quoted as a number: mode numbering past the first moves
    when the mesh or geometry moves, so the tail is a spectrum, not a list
    to act on.
    """
    if len(factors) <= 1:
        return ""
    text = ", lambda2 %.4g" % factors[1]
    if len(factors) > 2:
        text += ", %d-%d %.3g-%.3g" % (3, len(factors),
                                       min(factors[2:]), max(factors[2:]))
    return text


def _governing(per_case):
    """The worst case by stress exposure factor — one quantity, one
    direction, whichever mechanism produced it.

    Strength and buckling are put on the same footing by dividing: the
    strain exposure factor is already demand over capacity, and a buckling
    factor is a load multiplier whose exposure form is 1/λ.  λ and a strain
    exposure factor must not be compared directly (CONTEXT.md), which is why
    this takes the maximum of the quotients rather than a minimum of the
    multipliers.
    """
    worst = None
    for name, row in per_case.items():
        candidates = []
        if row.get("strain_exposure") is not None:
            candidates.append(("strain", row["strain_exposure"],
                               row.get("part", ""), row.get("point")))
        if row.get("lambda_min"):
            candidates.append(("buckling", 1.0 / row["lambda_min"], "", None))
        for mechanism, exposure, part, point in candidates:
            if worst is None or exposure > worst["exposure"]:
                worst = {"case": name, "mechanism": mechanism,
                         "exposure": exposure,
                         "part": part, "point": point}
    return worst


def _mesh_for(run, parts, mesh_obj):
    """The mesh this geometry is entitled to: from cache if the signature
    matches, from gmsh otherwise.

    A mesh is a function of the shapes and the mesh parameters, and a run that
    reuses one has to know that rather than assume it. A stale mesh is the worst
    failure available: the deck's element blocks and the results' node IDs are
    both read positionally, so a reused mesh from other geometry reports a
    displacement belonging to a different node, and nothing complains.

    Measured, which is why this is worth its cost: geometry builds in 35 s,
    gmsh takes 44 s, and signing 47 parts costs 0.5 s. A hit saves about a third
    of a run; a miss costs the check, not a rebuild.
    """
    # The requested element sizes are part of what the mesh is: apply them
    # before signing it, or every refinement level hashes the same default
    # and the cache serves the first mesh back for all of them.
    mesh_obj.CharacteristicLengthMax = run.mesh_max
    mesh_obj.CharacteristicLengthMin = run.mesh_min
    _apply_mesh_shapes(mesh_obj, run.refinements, run.mesh_max)
    builder = run.study.builder_path()
    geometry = meshsignature.geometry_components(parts, run.geometry_arguments,
                                                 builder)
    components = meshsignature.mesh_components(geometry, mesh_obj)
    wanted = meshsignature.digest_of(components)
    run.provenance["geometry_key"] = meshsignature.digest_of(geometry)[:16]
    run.provenance["mesh_key"] = wanted[:16]
    run.provenance["signature"] = components
    if run.cache_root is None:
        run.provenance["mesh_outcome"] = "meshed (cache off)"
        log("mesh: %s, cache off" % wanted[:12])
        t0 = time.time()
        _ensure_mesh(mesh_obj, run.remesh, mesh_max=run.mesh_max,
                     mesh_min=run.mesh_min)
        run.provenance["mesh_seconds"] = time.time() - t0
        return
    previous = meshcache.latest(run.cache_root)
    if previous is not None and previous["digest"] != wanted:
        log("mesh: %s since the last run"
             % meshsignature.explain(previous["components"], components))
    if not run.remesh:
        t0 = time.time()
        found, nodes, elements = meshcache.load(run.cache_root, wanted, mesh_obj)
        if found:
            run.provenance["mesh_outcome"] = "cached"
            run.provenance["mesh_seconds"] = time.time() - t0
            log("mesh: %d nodes, %d faces, cached, restored in %.1fs"
                 % (nodes, elements, time.time() - t0))
            meshcache.note(run.cache_root, wanted, components,
                           mesh_obj.FemMesh, "cached")
            return
    t0 = time.time()
    _ensure_mesh(mesh_obj, run.remesh, mesh_max=run.mesh_max,
                 mesh_min=run.mesh_min)
    run.provenance["mesh_seconds"] = time.time() - t0
    run.provenance["mesh_outcome"] = "meshed"
    stored = meshcache.store(run.cache_root, wanted, mesh_obj.FemMesh, components)
    log("mesh: stored as %s" % os.path.basename(stored))
    meshcache.note(run.cache_root, wanted, components, mesh_obj.FemMesh, "meshed")


def _write_and_audit(run, ctx, fem, cases, audit=True, verify=True):
    """Write one deck for these cases and prove it says what it should.

    ``verify`` is off only for a deck that carries no load by construction —
    an eigenvalue step of a run whose answer does not depend on one.
    """
    doc, mesh_obj = ctx["doc"], ctx["mesh"]
    fem.step_count = len(cases)
    fem.reaction_snapshots = [run.study.snapshot(case) for case in cases]
    t0 = time.time()
    fem.write_inp_file()
    log("input written in %.1fs: %s" % (time.time() - t0, fem.inp_file_name))
    if audit:
        rows, problems = run.study.deck_audit(doc, fem.inp_file_name)
        for name, laminate, kind, layers, thickness, blocks, elements in rows:
            log("  %-40s %-24s %-8s %2d layers %.3f mm (%d blocks, %d elements)"
                 % (name, laminate, kind, layers, thickness, blocks, elements))
        if problems:
            raise RuntimeError("deck section audit failed:\n  "
                               + "\n  ".join(problems))
        log("deck audit: %d sections carry their laminate" % len(rows))
    # The ground truth of the load case is the file ccx consumes.
    if verify:
        deckcheck.verify_loads(fem.inp_file_name, mesh_obj.FemMesh,
                               ctx["origin"], run.study.load_tag, cases,
                               run.study.targets(cases))
    return fem.inp_file_name


def solve_static(run, ctx):
    """Solve the strength deck and report displacement and strain exposure."""
    cases = ctx["cases"]
    analysis, solver, mesh_obj = ctx["analysis"], ctx["solver"], ctx["mesh"]
    log("writing solver input (per-layer sections from the laminates)...")
    run.study.refresh(ctx["doc"])
    fem = _ccx_tools(analysis, solver, mesh_obj)
    if hasattr(fem, "setup_working_dir"):
        fem.setup_working_dir()
    fem.set_inp_file_name()
    # One *STEP per case, each carrying its own complete wrench.  The mesh
    # and the per-element laminate blocks — all but the load lines of the
    # file — are then written once for the whole deck instead of once per
    # case, which is where most of a run's non-solve time goes.
    inp = _write_and_audit(run, ctx, fem, cases)
    ctx["inp_file"] = inp

    log("running CalculiX (%d step%s)..."
         % (len(cases), "" if len(cases) == 1 else "s"))
    t0 = time.time()
    ret_code = fem.ccx_run()
    result = ret_code == 0
    if result:
        fem.load_results()
        log("solver fields kept: %s" % _retain_results(run, inp))
    log("solve %s in %.1fs"
         % ("OK" if result else "FAILED (rc=%s)" % ret_code, time.time() - t0))
    if not result:
        log("failing deck kept: %s" % _retain_failing_deck(run, inp))
        log("nothing to report: ccx stops the whole deck at the first bad "
             "step. Read the .sta for which step died, then re-run the "
             "suspect on its own (--cases lcNN) — that isolates it, it is "
             "not a retry of the same deck.")
        return None

    parts = ctx["parts"]
    clouds, note = run.study.part_clouds(ctx["doc"], ctx["inp_file"], parts)
    if note:
        log("part attribution: %s" % note)
    per_case = {}
    for name, result_obj in zip(cases, _result_objects(analysis, len(cases))):
        report = _exposure_summary(result_obj, parts, clouds=clouds) or {}
        per_case[name] = {
            "max_displacement": _max_displacement(result_obj),
            "strain_exposure": report.get("strain_exposure_max"),
            "part": report.get("hotspot_part", ""),
            "point": report.get("hotspot_point"),
            "exposure_by_part": report.get("exposure_by_part", {}),
        }
        log("case %s: max disp %s mm; strain exposure factor %s%s%s"
             % (name,
                "%.4f" % per_case[name]["max_displacement"]
                if per_case[name]["max_displacement"] is not None else "n/a",
                "%.3g" % report["strain_exposure_max"] if report else "n/a",
                " " + _position_text(report.get("hotspot_point"))
                if report.get("hotspot_point") else "",
                " in %s" % report["hotspot_part"]
                if report.get("hotspot_part") else ""))
    return per_case


def solve_buckling(run, ctx):
    """Solve a second deck for λ and return {case: [factors in mode order]}.

    The analysis type is a deck-wide solver property, so buckling cannot
    share the static deck — but it reuses its mesh and its per-step CLOAD
    delivery, and that delivery is verified against the case wrench here too
    rather than assumed, because a λ computed against the wrong load is
    worse than no λ.
    """
    cases = ctx["cases"]
    modes = run.modes
    analysis, solver, mesh_obj = ctx["analysis"], ctx["solver"], ctx["mesh"]
    log("buckling: %d modes per case, a second deck "
         "(linear: about the undeformed shape, no NLGEOM)" % modes)
    solver.AnalysisType = "buckling"
    solver.BucklingFactors = modes
    # A mode's element stresses are per mode and per ply: most of the deck's
    # size, and read by nothing.  The writer owns that decision now, so no deck
    # is edited after it has been written.
    previous_element_output = solver.EigenmodeElementOutput
    solver.EigenmodeElementOutput = False
    try:
        fem = _ccx_tools(analysis, solver, mesh_obj)
        work_dir = os.path.join(os.path.dirname(ctx["inp_file"]), "buckling")
        # ccx refuses to make its own working directory: it reports "Dir ...
        # doesn't exist or cannot be created" and stops with a nonzero code.
        os.makedirs(work_dir, exist_ok=True)
        if hasattr(fem, "setup_working_dir"):
            fem.setup_working_dir(work_dir, create=True)
        fem.set_inp_file_name()
        inp = _write_and_audit(run, ctx, fem, cases, audit=False)
        log("running CalculiX buckling (%d step%s)..."
             % (len(cases), "" if len(cases) == 1 else "s"))
        t0 = time.time()
        ret_code = fem.ccx_run()
        log("buckling solve %s in %.1fs"
             % ("OK" if ret_code == 0 else "FAILED (rc=%s)" % ret_code,
                time.time() - t0))
        if ret_code != 0:
            raise RuntimeError("ccx failed the buckling deck (rc=%s)" % ret_code)
        factors = ccxdat.buckling_factors_for_cases(_dat_of(inp), cases, modes)
    finally:
        # Back to the type the saved model was configured for, so a later
        # write of the static deck cannot inherit a buckling step.
        solver.AnalysisType = "static"
        solver.EigenmodeElementOutput = previous_element_output
    ctx["buckling_inp_file"] = inp
    for name in cases:
        tail = _mode_tail_text(factors[name])
        log("case %s buckling: lambda1 %.4g%s; buckling exposure factor %.3g"
             % (name, factors[name][0], tail, 1.0 / factors[name][0]))
    return factors


def solve_frequency(run, ctx):
    """Solve a third deck for the article's natural frequencies.

    An eigenvalue run is a deck-wide solver property, so frequencies cannot
    share the static deck or the buckling one; they reuse their mesh.

    It is one step, not one per load case, and it carries no load.  That is
    what the solver input can say: FreeCAD writes no ``*CLOAD`` into a
    ``*FREQUENCY`` step, and the load-stiffened frequencies of a case would
    need a ``*STATIC`` step continued into a ``*FREQUENCY`` one, which the
    writer does not emit.  So these are the frequencies of the unloaded
    article — which is the right question for a resonance check, and the
    wrong one for a flutter one.
    """
    modes = run.frequency_modes
    analysis, solver, mesh_obj = ctx["analysis"], ctx["solver"], ctx["mesh"]
    log("frequencies: %d modes, one step, no load (the article's own "
         "stiffness and mass, not a case's)" % modes)
    solver.AnalysisType = "frequency"
    solver.EigenmodesCount = modes
    # Both limits at zero is what makes the writer state a count rather than
    # a band to search, which is the difference between "the lowest eight"
    # and "up to eight, somewhere under a megahertz".
    solver.EigenmodeLowLimit = 0.0
    solver.EigenmodeHighLimit = 0.0
    previous_element_output = solver.EigenmodeElementOutput
    solver.EigenmodeElementOutput = False
    try:
        fem = _ccx_tools(analysis, solver, mesh_obj)
        work_dir = os.path.join(os.path.dirname(ctx["inp_file"]), "frequency")
        # ccx refuses to make its own working directory.
        os.makedirs(work_dir, exist_ok=True)
        if hasattr(fem, "setup_working_dir"):
            fem.setup_working_dir(work_dir, create=True)
        fem.set_inp_file_name()
        inp = _write_and_audit(run, ctx, fem, ctx["cases"][:1], audit=False,
                               verify=False)
        log("running CalculiX frequencies...")
        t0 = time.time()
        ret_code = fem.ccx_run()
        log("frequency solve %s in %.1fs"
             % ("OK" if ret_code == 0 else "FAILED (rc=%s)" % ret_code,
                time.time() - t0))
        if ret_code != 0:
            raise RuntimeError("ccx failed the frequency deck (rc=%s)" % ret_code)
        found = ccxdat.modes_for_run(_dat_of(inp), modes)
    finally:
        # Back to the type the saved model was configured for, so a later
        # write of the static deck cannot inherit an eigenvalue step.
        solver.AnalysisType = "static"
        solver.EigenmodeElementOutput = previous_element_output
    ctx["frequency_inp_file"] = inp
    log("frequencies: %s"
         % ", ".join("f%d %s" % (index + 1, ccxdat.mode_text(mode))
                     for index, mode in enumerate(found)))
    return found


def _provenance(run):
    """What this run was, for the report.

    A report that cannot say which geometry it came from is how a superseded
    number ends up in a design decision, so the signature travels with the
    result rather than living in a separate log.
    """
    return dict(run.provenance, study=run.study.name,
                geometry_arguments=run.geometry_arguments,
                versions=meshsignature.versions(),
                builder=meshsignature.builder_digest(run.study.builder_path()),
                mesh_cache=run.cache_root or "off",
                git=_git_commit(os.path.dirname(run.study.builder_path())))


def _git_commit(directory):
    """The commit the builder in ``directory`` was read from.

    Worth having next to the builder's own digest: the digest says the text,
    and this says whether that text was committed, which is how a result gets
    traced back to something a later checkout can reproduce.
    """
    try:
        finished = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return finished.stdout.strip() or "unknown"


def solve(run, ctx=None):
    """One study pass: strength and buckling over every case, one answer.

    This is the entry point for an iteration loop — build the model once, then
    call it per candidate layup. It changes no geometry and rebuilds no mesh; a
    layup reaches the deck through the section and material cards, so what is
    re-solved is exactly what changed.
    """
    ctx = ctx if ctx is not None else prepare(run)
    cases = ctx["cases"]
    t0 = time.time()
    per_case = solve_static(run, ctx)
    run.provenance["solve_seconds"] = time.time() - t0
    if per_case is None:
        return {"result": False, "cases": cases,
                "inp_file": ctx.get("inp_file"),
                "constraints": [c.Name for c in ctx["constraints"]],
                "provenance": _provenance(run)}

    if run.buckling:
        t0 = time.time()
        factors = solve_buckling(run, ctx)
        run.provenance["buckling_seconds"] = time.time() - t0
        for name in cases:
            per_case[name]["lambda"] = factors[name]
            per_case[name]["lambda_min"] = factors[name][0]

    frequencies = None
    if run.frequency:
        t0 = time.time()
        frequencies = solve_frequency(run, ctx)
        run.provenance["frequency_seconds"] = time.time() - t0

    mass = None
    if run.mass:
        # The plies' densities and thicknesses are already in the deck the
        # static solve wrote, so mass costs a pass over it and nothing else.
        mass = run.study.mass_report(ctx["doc"], ctx["inp_file"])
        log("mass of the article:")
        modelmass.log_report(mass, log)

    governing = _governing(per_case)
    # Tsai-Wu and Hashin stay OFF (owner decision): the material cards do
    # not carry correct interaction terms for them, so any index they
    # produce is a number without a meaning.  The strain exposure against
    # the design strains is the criterion the study answers to.
    log("governing: %s %s, exposure factor %.3g%s"
         % (governing["case"], governing["mechanism"], governing["exposure"],
            " in %s" % governing["part"] if governing["part"] else ""))
    return {
        "result": True,
        "cases": cases,
        "per_case": per_case,
        "governing": governing,
        "max_displacement": max(c["max_displacement"] or 0.0
                                for c in per_case.values()),
        "mass": mass,
        "frequencies": frequencies,
        "inp_file": ctx.get("inp_file"),
        "buckling_inp_file": ctx.get("buckling_inp_file"),
        "frequency_inp_file": ctx.get("frequency_inp_file"),
        "constraints": [c.Name for c in ctx["constraints"]],
        "provenance": _provenance(run),
    }


def prepare(run):
    """Build the study's geometry and give it a mesh — once, for a whole study.

    Built rather than opened: a saved model is a claim about which arguments
    produced it, and nothing inside the file can be checked against them. The
    build is cheap next to a solve, and staleness becomes impossible instead of
    something to detect.

    A layup iteration does not move geometry — plies reach the deck through the
    section and material cards — so the mesh belongs to the study, not to an
    iteration, and solve() never rebuilds it.
    """
    t0 = time.time()
    doc = run.study.build(run.geometry_arguments)
    run.provenance["build_seconds"] = time.time() - t0
    log("geometry built in %.1fs: %s" % (time.time() - t0, _arguments_text(run)))
    FreeCAD.setActiveDocument(doc.Name)

    parts = run.study.parts(doc)
    analysis = doc.getObject("Analysis")
    solver = doc.getObject("SolverCcxTools")
    mesh_obj = doc.getObject(run.study.mesh_name)
    if analysis is None or solver is None or mesh_obj is None:
        raise RuntimeError("the built model has no FEM scaffolding — the study's "
                           "build() must create Analysis, SolverCcxTools and %s"
                           % run.study.mesh_name)

    log("load cases: %s (%d)" % (", ".join(run.cases), len(run.cases)))
    doc.RecomputesFrozen = False
    _mesh_for(run, parts, mesh_obj)
    _uncull_fem_views(doc)
    if not any(getattr(o, "References", None) is not None
               and o.Name.endswith("_Section") for o in analysis.Group):
        raise RuntimeError("no referenced sections in the analysis")
    message = checksanalysis.check_sections_reference_the_mesh(analysis, mesh_obj)
    if message:
        raise RuntimeError(message)
    constraints = run.study.constraints(doc, analysis)
    doc.recompute()
    return {
        "doc": doc, "analysis": analysis, "solver": solver,
        "mesh": mesh_obj, "parts": parts, "constraints": constraints,
        "origin": run.study.origin(doc), "cases": run.cases,
    }


def _arguments_text(run):
    return ", ".join("%s=%s" % (name, run.geometry_arguments[name])
                     for name in sorted(run.geometry_arguments))


def artifact_paths(paths, out_dir, study_name, variant, cases):
    """Where a run's log and report go.

    One name, two suffixes, so a summary finds a run's numbers beside the
    sentences about it.  ``paths`` is the study's namer, because the sweep and
    the driver must agree on it without importing each other.
    """
    return paths(out_dir, study_name, variant, cases)


class Run:
    """One run's plan: which study, which geometry, where it writes.

    Paths are decided once, here, so that no function further down composes a
    filename and nothing defaults to /tmp.
    """

    def __init__(self, study, variant=None, cases=None, out_dir=None,
                 buckling=True, modes=None, frequency=False,
                 frequency_modes=None, mass=True, remesh=False, cache=True,
                 cache_root=None, gmsh=None, mesh_max=60.0, mesh_min=5.0,
                 refinements=()):
        self.study = study
        variants = study.variants()
        if variant is not None and variant not in variants:
            raise RuntimeError("variant %r is not one of %s"
                               % (variant, ", ".join(sorted(variants)) or "(none)"))
        self.variant = variant
        self.overrides = dict(variants.get(variant, {}))
        self.cases = list(cases if cases is not None else study.cases())
        if not self.cases:
            raise RuntimeError("no load cases selected")
        for name in self.cases:
            if name not in study.cases():
                raise RuntimeError("case %r is not one of %s"
                                   % (name, ", ".join(study.cases())))
        self.buckling = buckling
        self.modes = modes or DEFAULT_MODES
        self.frequency = frequency
        self.frequency_modes = frequency_modes or DEFAULT_FREQUENCIES
        self.mass = mass
        self.remesh = remesh
        self.gmsh = gmsh
        self.mesh_max = mesh_max
        self.mesh_min = mesh_min
        self.refinements = tuple(refinements)
        self.cache_root = (meshcache.ensure_root(cache_root or study.cache_root())
                           if cache else None)
        whole_table = self.cases == list(study.cases())
        self.log_path, self.artifact_path = artifact_paths(
            study.run_paths, out_dir, study.name, variant,
            None if whole_table else self.cases)
        self.provenance = {"build_seconds": None, "mesh_seconds": None,
                           "solve_seconds": None, "buckling_seconds": None,
                           "frequency_seconds": None,
                           "mesh_outcome": "", "mesh_key": "",
                           "geometry_key": "", "signature": {}}

    @property
    def geometry_arguments(self):
        """The study's own defaults with this variant's overrides applied."""
        merged = dict(self.study.geometry_arguments())
        merged.update(self.overrides)
        return merged


def _json_value(value):
    """A FreeCAD value in a run report, as plain JSON: a Vector as three
    numbers, a Matrix as three rows, so the artifact is readable by a report
    tool that has no FreeCAD at all."""
    if hasattr(value, "A11"):  # FreeCAD.Matrix
        return [[value.A11, value.A12, value.A13],
                [value.A21, value.A22, value.A23],
                [value.A31, value.A32, value.A33]]
    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        return [value.x, value.y, value.z]
    raise TypeError("no JSON form for %s" % type(value).__name__)


def write_artifact(run, report):
    """Write the run's numbers where the report will look for them."""
    with open(run.artifact_path, "w") as handle:
        json.dump(dict(report, study=run.study.name, log=run.log_path),
                  handle, indent=1, sort_keys=True, default=_json_value)
    return run.artifact_path



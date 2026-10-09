# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Probe the mesh-level premises of the mixed shell+solid FEM plan.

Answers premises P4-P6 of docs/plan-mixed-shell-solid-fem.md section 9 by
executing them rather than reading them:

  M1  getFacesOnly() reports a node-disjoint shell inside a mixed FemMesh, and
      writeABAQUS(elemParam=2) emits the volumes and the Efaces elset together
  MT  the same quad sharing the brick's nodes leaves getFacesOnly() empty.
      That is Trap A, and it is why the merge route stays node-disjoint.
  M2  compact_mesh, the renumbering discipline the merge helper will reuse,
      preserves both of the above

Only the existing FemMesh and meshtools APIs are called; no production file is
touched, so this can run before any of the plan's stages exist.

Note: FreeCAD writes one bare `0` line to C++ stdout per writeABAQUS call and
per compact_mesh call. Those lines are not produced here, but they are flushed
immediately while Python's output is block-buffered, so they appear before this
probe's report rather than interleaved with it.

Running it, from the repo root with the pixi env on the library path (see the
freecad-dev skill for the canonical form):

    FreeCADCmd -c "
    import sys
    sys.path.insert(0, '<repo>/src/Mod')
    sys.path.insert(0, '<repo>/src/Mod/Composites')
    from compositestests.inspect_mixed_mesh_premises import main
    main([])
    " > /tmp/probe.log 2>&1

The redirect is not cosmetic: on failure FreeCADCmd's own diagnostics go to the
tty and are easy to lose in a pipe. The wrapper script exists as well, but it
must flush stdout before raising SystemExit - without that a SystemExit under
FreeCADCmd discards everything Python has buffered and the wrapper looks as if
it did nothing at all.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import Fem

from femmesh import meshtools

# A brick whose bottom face is nodes 1-4. A quad added on those same four
# coordinates is then either node-disjoint from the brick (the merge route) or
# exactly shared with it (Trap A), and nothing else differs.
BRICK_CORNERS = [
    (0.0, 0.0, 0.0),
    (10.0, 0.0, 0.0),
    (10.0, 10.0, 0.0),
    (0.0, 10.0, 0.0),
    (0.0, 0.0, 10.0),
    (10.0, 0.0, 10.0),
    (10.0, 10.0, 10.0),
    (0.0, 10.0, 10.0),
]


def _add_brick(mesh: "Fem.FemMesh") -> list[int]:
    ids = []
    for index, (x, y, z) in enumerate(BRICK_CORNERS, start=1):
        mesh.addNode(x, y, z, index)
        ids.append(index)
    mesh.addVolume(ids)
    return ids


def build_mixed_mesh(shared_nodes: bool) -> "Fem.FemMesh":
    """A brick plus a quad at the same four coordinates.

    With shared_nodes the quad reuses the brick's nodes 1-4, so its node set is
    a subset of the volume's and Trap A applies. Otherwise it gets its own
    nodes at identical coordinates, which is what merging two separately meshed
    bodies produces.
    """
    mesh = Fem.FemMesh()
    brick = _add_brick(mesh)
    if shared_nodes:
        quad = list(brick[:4])
    else:
        quad = []
        for offset, (x, y, z) in enumerate(BRICK_CORNERS[:4]):
            node_id = len(brick) + 1 + offset
            mesh.addNode(x, y, z, node_id)
            quad.append(node_id)
    mesh.addFace(quad)
    return mesh


def describe(mesh: "Fem.FemMesh") -> dict:
    return {
        "nodes": len(mesh.Nodes),
        "volumes": len(mesh.Volumes),
        "faces": len(mesh.Faces),
        "faces_only": len(mesh.FacesOnly),
        "edges_only": len(mesh.EdgesOnly),
    }


def abaqus_text(mesh: "Fem.FemMesh", stem: str) -> str:
    """Write the mesh with elemParam=2 and return the deck text."""
    with tempfile.TemporaryDirectory(prefix="mixed_mesh_premise_") as tmp:
        path = Path(tmp) / f"{stem}.inp"
        mesh.writeABAQUS(str(path), 2, False)
        return path.read_text()


def abaqus_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.startswith("*Element") or line.startswith("*ELSET")
    ]


def element_ids(mesh: "Fem.FemMesh") -> list[int]:
    return list(mesh.Edges) + list(mesh.Faces) + list(mesh.Volumes)


def _report(name: str, ok: bool, detail: str) -> bool:
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}")
    for line in detail.splitlines():
        print(f"        {line}")
    return ok


def case_m1() -> bool:
    """P4 and P5: a node-disjoint shell survives detection and reaches the deck."""
    mesh = build_mixed_mesh(shared_nodes=False)
    counts = describe(mesh)
    lines = abaqus_lines(abaqus_text(mesh, "m1"))
    text = "\n".join(lines)

    detail = (
        f"counts: {counts}\n"
        f"deck: {lines}\n"
        f"expect: faces_only == 1, ELSET=Evolumes and ELSET=Efaces both present"
    )
    ok = counts["faces_only"] == 1 and "ELSET=Evolumes" in text and "ELSET=Efaces" in text
    return _report("M1 / P4+P5  node-disjoint shell is detected and written", ok, detail)


def case_mt() -> bool:
    """Trap A: the same quad sharing the brick's nodes vanishes from FacesOnly."""
    mesh = build_mixed_mesh(shared_nodes=True)
    counts = describe(mesh)
    lines = abaqus_lines(abaqus_text(mesh, "mt"))

    detail = (
        f"counts: {counts}\n"
        f"deck: {lines}\n"
        f"expect: faces_only == 0 and no ELSET=Efaces, i.e. the shell is dropped"
    )
    ok = counts["faces_only"] == 0 and "ELSET=Efaces" not in "\n".join(lines)
    return _report("MT / Trap A  shared-node shell disappears", ok, detail)


def case_m2() -> bool:
    """P6: renumbering the merge preserves detection and the id discipline."""
    mesh = build_mixed_mesh(shared_nodes=False)
    before = describe(mesh)
    compacted, _node_map, _elem_map = meshtools.compact_mesh(mesh)
    after = describe(compacted)

    ids = element_ids(compacted)
    unique = len(ids) == len(set(ids))
    sorted_ids = sorted(ids)
    contiguous = sorted_ids == list(range(1, len(sorted_ids) + 1))

    lines = abaqus_lines(abaqus_text(compacted, "m2"))
    text = "\n".join(lines)

    detail = (
        f"before: {before}\n"
        f"after:  {after}\n"
        f"element ids unique={unique}, contiguous={contiguous}\n"
        f"deck: {lines}\n"
        f"expect: faces_only survives, ELSET=Efaces present, ids unique.\n"
        f"Contiguity is deliberately not required - compact_mesh advances the\n"
        f"element id twice per face, so gaps are expected and asserting\n"
        f"contiguity would fail on correct output."
    )
    ok = (
        after["faces_only"] == 1
        and "ELSET=Efaces" in text
        and unique
    )
    return _report("M2 / P6  compact_mesh preserves the mixed mesh", ok, detail)


CASES = {"m1": case_m1, "mt": case_mt, "m2": case_m2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "cases",
        nargs="*",
        default=None,
        help="which cases to run (default: all)",
    )
    args = parser.parse_args(argv)
    # Not argparse `choices`: a nargs="*" positional validates its empty default
    # against choices and rejects it, so an argument-less call fails.
    cases = args.cases or list(CASES)
    unknown = [case for case in cases if case not in CASES]
    if unknown:
        parser.error(f"unknown case(s): {', '.join(unknown)}; choose from {', '.join(CASES)}")

    results = {case: CASES[case]() for case in cases}

    print("\nsummary")
    for case in CASES:
        if case in results:
            print(f"  {case}: {'holds' if results[case] else 'FAILS'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""What opening a document costs, and what re-runs while it opens.

A solved mixed model freezes the GUI, and that has been blamed on several
different things - the geometry, the composite shells, the FEM mesh, the result -
without any of them being measured. This measures one document per run so the
stages can be told apart: build the same model up to each stage, save it, and
open each save with this.

Two numbers matter and they answer different questions:

* **open** - parsing the file and creating the objects, which is what the GUI
  does on the way up;
* **recompute after open** - whether anything was left dirty by the load, and
  what it costs to settle it.  A drape that re-solves on open is minutes of a
  frozen event loop, and it would look exactly like "the GUI is unresponsive".

The marker tap counts drape solves during each phase, so "something re-executed"
is a measurement rather than an inference.  Only cheap mesh properties are read:
``FemMesh.FacesOnly`` and friends scan the whole mesh, and calling one here would
put the very cost this is trying to isolate into the measurement.

Usage:
    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_document_load_cost.py \\
        /tmp/wing_geom.FCStd /tmp/wing_shells.FCStd ...
"""

import argparse
import os
import sys
import time

import FreeCAD


class MarkerTap:
    """Counts occurrences of a marker in everything written through it."""

    def __init__(self, stream, marker):
        self._stream = stream
        self._marker = marker
        self.count = 0

    def write(self, text):
        self.count += str(text).count(self._marker)
        return self._stream.write(text)

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        # FreeCAD replaces sys.stdout with its own object and may ask it for
        # anything; anything this tap does not implement goes to the real one.
        return getattr(self._stream, name)


def _open_and_settle(path):
    """Open the document, then recompute. Returns the two times and the drape count."""
    tap = MarkerTap(sys.stdout, "[drape]")
    real_stdout = sys.stdout
    sys.stdout = tap
    doc = None
    try:
        start = time.perf_counter()
        doc = FreeCAD.openDocument(path)
        open_seconds = time.perf_counter() - start
        drapes_on_open = tap.count

        # Anything the load left dirty settles here.  If this is where the
        # drape runs, the load itself was not the cost - the recompute was.
        start = time.perf_counter()
        doc.recompute()
        settle_seconds = time.perf_counter() - start
        drapes_on_settle = tap.count - drapes_on_open
    finally:
        sys.stdout = real_stdout

    counted = _count_objects(doc)
    FreeCAD.closeDocument(doc.Name)
    return {
        "open_seconds": open_seconds,
        "settle_seconds": settle_seconds,
        "drapes_on_open": drapes_on_open,
        "drapes_on_settle": drapes_on_settle,
        "counted": counted,
    }


def _count_objects(doc):
    """Object counts by type, with the cheap size properties of mesh and result."""
    counts = {}
    mesh_nodes = None
    result_values = None
    for obj in doc.Objects:
        counts[obj.TypeId] = counts.get(obj.TypeId, 0) + 1
        if obj.isDerivedFrom("Fem::FemMeshObject") and mesh_nodes is None:
            mesh_nodes = obj.FemMesh.NodeCount
        if obj.isDerivedFrom("Fem::FemResultObject") and result_values is None:
            result_values = len(getattr(obj, "DisplacementLengths", []) or [])
    return counts, mesh_nodes, result_values


def measure(path):
    if not os.path.exists(path):
        print(f"{os.path.basename(path):<22} MISSING", flush=True)
        return
    size_mb = os.path.getsize(path) / (1024.0 * 1024.0)
    result = _open_and_settle(path)
    counts, mesh_nodes, result_values = result["counted"]
    print(
        f"{os.path.basename(path):<22} size={size_mb:7.1f} MB"
        f"  open={result['open_seconds']:7.2f}s"
        f"  settle={result['settle_seconds']:7.2f}s"
        f"  drapes={result['drapes_on_open']}+{result['drapes_on_settle']}"
        f"  objects={sum(counts.values())}"
        f"  mesh_nodes={mesh_nodes}"
        f"  result_values={result_values}",
        flush=True,
    )
    for type_id in sorted(counts):
        print(f"    {type_id:<38} {counts[type_id]}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("documents", nargs="+", help=".FCStd files to open and measure")
    args = parser.parse_args()

    print("drapes=on-open+on-settle; both zero means nothing re-executed", flush=True)
    for path in args.documents:
        measure(path)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Is the layered COMPOSITE *SHELL SECTION what makes ccx write an expanded
mesh to the .frd, or is it the model's size?

The wing deck is large *and* every one of its shell elements carries its own
layered COMPOSITE section, so the two are confounded. The probe's mixed model is
small *and* homogeneous, and its .frd node count equals its mesh's. This tool
breaks the confound: it takes a deck, keeps the nodes and elements byte for
byte, and replaces every per-element layered COMPOSITE section with one
homogeneous *SHELL SECTION over the same shell elements. Then it runs ccx and
counts the nodes the .frd declares.

Structure the transform relies on, verified against the wing deck before it was
written: each shell element owns a data block of the form

    *ELSET,ELSET=<name>
    <element id>
    *ORIENTATION,NAME=<name>
    <a>,<b>,<c>,<d>,<e>,<f>
    *SHELL SECTION, ELSET=<name>, COMPOSITE,ORIENTATION=<name>, OFFSET=0
    <thickness>,,<ply material>
    ... one line per ply ...
    <blank>

so the ELSET, its ORIENTATION and the COMPOSITE section all belong to one
element and are dropped together. Nothing before or after the sections is
touched, so the mesh stays byte-identical.

Usage:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_shell_section_expansion.py \\
        --deck /tmp/fcfem_6lntjgmu/WingPipelineCost_FEMMesh.inp

To just count an existing .frd, pass --frd and no --deck.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_CCX = os.path.expanduser("~/.local/bin/ccx")
DEFAULT_OUTDIR = "/tmp/fe_shell_section_expansion"

# ccx is stopped only by a wall-clock bound and an output cap, and its output is
# drained line by line, so a degenerate deck costs a bounded amount of memory
# and disk rather than filling the machine.
DEFAULT_TIMEOUT = 1800.0
DEFAULT_OUTPUT_CAP = 200_000

_MATERIAL_RE = re.compile(r"MATERIAL\s*=\s*([^,\s]+)", re.IGNORECASE)


def _read_lines(path):
    with open(path, "r", errors="replace") as handle:
        return handle.readlines()


def _is_composite_shell_section(line):
    upper = line.upper()
    return line.startswith("*") and "SHELL SECTION" in upper and "COMPOSITE" in upper


def _mesh_node_ids(lines):
    """Every node id the deck's *Node card defines."""
    ids = []
    in_nodes = False
    for line in lines:
        if line.startswith("*"):
            keyword = line.upper().split(",")[0].strip()
            in_nodes = keyword == "*NODE"
            continue
        if in_nodes and line.strip():
            ids.append(int(line.split(",")[0]))
    return ids


def _solid_material(lines):
    for line in lines:
        if line.upper().startswith("*SOLID SECTION"):
            match = _MATERIAL_RE.search(line)
            if match:
                return match.group(1)
    return None


def _first_section_thickness(lines, first_section):
    """Sum the ply thicknesses of the first surviving COMPOSITE section."""
    total = 0.0
    for line in lines[first_section + 1:]:
        if line.startswith("*"):
            break
        stripped = line.strip()
        if not stripped:
            continue
        total += float(stripped.split(",")[0])
    return total


def transform(lines, elset, material):
    """Replace the layered COMPOSITE sections with one homogeneous section.

    Returns (new lines, report dict). The mesh is copied through untouched.
    """
    section_indices = [i for i, line in enumerate(lines) if _is_composite_shell_section(line)]
    if not section_indices:
        raise SystemExit("deck has no layered COMPOSITE *SHELL SECTION to isolate")
    if material is None:
        material = _solid_material(lines)
        if material is None:
            raise SystemExit("no *SOLID SECTION to take a homogeneous material from; pass --material")

    thickness = _first_section_thickness(lines, section_indices[0])

    drop = set()
    for k in section_indices:
        # the section keyword itself
        drop.add(k)
        # the ply data, and the blank that follows the last ply
        j = k + 1
        while j < len(lines) and not lines[j].startswith("*"):
            drop.add(j)
            j += 1
        # the ORIENTATION card and its data
        j = k - 1
        while j >= 0 and not lines[j].startswith("*"):
            drop.add(j)
            j -= 1
        if j >= 0 and lines[j].upper().startswith("*ORIENTATION"):
            drop.add(j)
            j -= 1
            while j >= 0 and not lines[j].startswith("*"):
                drop.add(j)
                j -= 1
            if j >= 0 and lines[j].upper().startswith("*ELSET"):
                drop.add(j)

    first_drop = min(drop)
    replacement = [
        f"*SHELL SECTION, ELSET={elset}, MATERIAL={material}\n",
        f"{thickness:.14g}\n",
        "\n",
    ]

    out = []
    inserted = False
    for i, line in enumerate(lines):
        if i == first_drop and not inserted:
            out.extend(replacement)
            inserted = True
        if i in drop:
            continue
        out.append(line)

    report = {
        "composite_sections": len(section_indices),
        "lines_removed": len(drop),
        "material": material,
        "thickness": thickness,
        "elset": elset,
    }
    return out, report


def run_ccx(ccx, inp_path, workdir, timeout, output_cap):
    """Run ccx, draining stdout line by line under a wall-clock bound.

    Returns (returncode, elapsed, tail lines, timed_out).
    """
    tail = collections.deque(maxlen=40)
    timed_out = [False]

    def kill():
        timed_out[0] = True
        if proc.poll() is None:
            proc.kill()

    start = time.perf_counter()
    proc = subprocess.Popen(
        [ccx, "-i", inp_path],
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    timer = threading.Timer(timeout, kill)
    timer.start()
    try:
        count = 0
        for line in proc.stdout:
            count += 1
            if count <= output_cap:
                tail.append(line.rstrip("\n"))
            elif count == output_cap + 1:
                tail.append(f"... output capped at {output_cap} lines ...")
        proc.wait()
    finally:
        timer.cancel()
    elapsed = time.perf_counter() - start
    return proc.returncode, elapsed, list(tail), timed_out[0]


def analyse_frd(path):
    """Node block of an frd: declared count, records, id range."""
    declared = None
    ids = []
    in_nodes = False
    with open(path, "r", errors="replace") as handle:
        for line in handle:
            if declared is None and line.startswith("    2C"):
                declared = int(line[22:].split()[0])
                in_nodes = True
                continue
            if in_nodes:
                if not line.startswith(" -1"):
                    break
                ids.append(int(line[3:14]))
            elif len(ids) > 200000:
                break
    return {
        "declared": declared,
        "records": len(ids),
        "unique": len(set(ids)),
        "min_id": min(ids) if ids else None,
        "max_id": max(ids) if ids else None,
    }


def _report_frd(label, frd, deck_node_count, deck_node_max):
    print(f"[{label}] frd {frd['records']} node records (declared {frd['declared']}), "
          f"unique {frd['unique']}, ids {frd['min_id']}..{frd['max_id']}")
    if deck_node_count:
        extra = frd["records"] - deck_node_count
        print(f"[{label}] deck nodes {deck_node_count} (max id {deck_node_max}) "
              f"-> extra frd nodes {extra} "
              f"({extra / deck_node_count:.2f}x the mesh)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deck", help="input CalculiX deck to transform")
    parser.add_argument("--frd", help="existing .frd to analyse instead of running")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help="working directory")
    parser.add_argument("--ccx", default=DEFAULT_CCX, help="path to the ccx binary")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="wall-clock bound for ccx, seconds")
    parser.add_argument("--output-cap", type=int, default=DEFAULT_OUTPUT_CAP,
                        help="maximum ccx stdout lines kept")
    parser.add_argument("--material", help="homogeneous shell material; default the solid's")
    parser.add_argument("--elset", default="Efaces",
                        help="element set the homogeneous section covers")
    parser.add_argument("--transform-only", action="store_true", help="write the deck, do not run ccx")
    args = parser.parse_args(argv)

    if args.frd and not args.deck:
        frd = analyse_frd(args.frd)
        _report_frd(args.frd, frd, 0, 0)
        return 0

    if not args.deck:
        parser.error("pass --deck or --frd")

    in_path = Path(args.deck)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[deck] reading {in_path}")
    lines = _read_lines(in_path)

    deck_node_ids = _mesh_node_ids(lines)
    print(f"[deck] {len(deck_node_ids)} nodes (max id {max(deck_node_ids)})")

    new_lines, report = transform(lines, args.elset, args.material)
    print(f"[transform] {report['composite_sections']} COMPOSITE sections -> "
          f"1 homogeneous section, material {report['material']}, "
          f"thickness {report['thickness']:.6g}, {report['lines_removed']} lines removed")

    inp_path = outdir / (in_path.stem + "_homogeneous.inp")
    with open(inp_path, "w") as handle:
        handle.writelines(new_lines)
    print(f"[transform] wrote {inp_path}")

    if args.transform_only:
        return 0

    if not os.path.exists(args.ccx):
        raise SystemExit(f"ccx not found at {args.ccx}")

    print(f"[ccx] solving (timeout {args.timeout:.0f}s, output cap {args.output_cap} lines)")
    rc, elapsed, tail, timed_out = run_ccx(
        args.ccx, inp_path.stem, str(outdir), args.timeout, args.output_cap)
    for line in tail:
        print(f"    {line}")
    print(f"[ccx] returncode {rc}, {elapsed:.1f} s, timed_out={timed_out}")

    frd_path = outdir / (inp_path.stem + ".frd")
    if not frd_path.exists():
        raise SystemExit(f"no .frd produced at {frd_path}")
    frd = analyse_frd(frd_path)
    _report_frd(inp_path.stem, frd, len(deck_node_ids), max(deck_node_ids))
    return 0 if rc == 0 and not timed_out else 1


if __name__ == "__main__":
    sys.exit(main())

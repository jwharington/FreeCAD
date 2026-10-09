#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Deck-level premise probes for the mixed shell+solid FEM plan.

Answers, with real CalculiX runs and no FreeCAD involvement, the gate
premises P1-P3 of docs/plan-mixed-shell-solid-fem.md section 9:

  D1 / P1  ccx accepts one deck containing solids and shells.
  D2 / P2  *TIE between a shell and a solid transfers moment (a tie)
           rather than behaving as a hinge.
  D3 / P3  a composite *SHELL SECTION coexists with *SOLID SECTION.

Each case writes a deck, runs ccx, and reports a mechanical verdict.  The
geometry is deliberately minimal: one C3D8 block and one or two S4 shells.

Usage:
    python3 inspect_mixed_deck_premises.py [--ccx PATH] [--keep] [d1 d2 d3]

Without case arguments all three run.  --keep leaves the work directory in
place and prints its path for inspection.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_CCX = os.path.expanduser("~/.local/bin/ccx")

# --------------------------------------------------------------------------
# Shared deck fragments
# --------------------------------------------------------------------------

MATERIAL = """\
*MATERIAL, NAME=STEEL
*ELASTIC
210000., 0.3
"""

# Block occupying x[0,10] y[-10,0] z[-5,5], one C3D8, fixed at the y=-10 face.
# Faces: S3=1-5-6-2 (y=-10), S5=3-7-8-4 (y=0).
BLOCK_NODES = """\
1, 0., -10., -5.
2, 10., -10., -5.
3, 10., 0., -5.
4, 0., 0., -5.
5, 0., -10., 5.
6, 10., -10., 5.
7, 10., 0., 5.
8, 0., 0., 5.
"""

BLOCK_ELEM = """\
*ELEMENT, TYPE=C3D8, ELSET=ESOLID
1, 1, 2, 3, 4, 5, 6, 7, 8
"""

BLOCK_FIX = """\
*NSET, NSET=NFIX
1, 2, 5, 6
*BOUNDARY
NFIX, 1, 3
"""


def _header(title: str) -> str:
    return f"*HEADING\n{title}\n"


# --------------------------------------------------------------------------
# D1 - does ccx accept a mixed solid+shell deck at all?          (premise P1)
# --------------------------------------------------------------------------


def deck_d1() -> str:
    """S8R plate lying on the block's top face, tied, uniformly loaded.

    S8R rather than S4 because composite shell sections are restricted to S8R
    and S6 (CalculiX manual, *SHELL SECTION); D3 must differ from D1 only in
    the section card, so both use S8R.
    """
    return (
        _header("D1 mixed C3D8 + S8R acceptance")
        + "*NODE\n"
        + BLOCK_NODES
        # shell on the block top face z=5, node-disjoint from the block
        + "9, 0., -10., 5.\n"
        + "10, 10., -10., 5.\n"
        + "11, 10., 0., 5.\n"
        + "12, 0., 0., 5.\n"
        + "13, 5., -10., 5.\n"
        + "14, 10., -5., 5.\n"
        + "15, 5., 0., 5.\n"
        + "16, 0., -5., 5.\n"
        + BLOCK_ELEM
        + "*ELEMENT, TYPE=S8R, ELSET=ESHELL\n2, 9, 10, 11, 12, 13, 14, 15, 16\n"
        + BLOCK_FIX
        + "*NSET, NSET=NALL, GENERATE\n1, 16\n"
        + MATERIAL
        + "*SOLID SECTION, ELSET=ESOLID, MATERIAL=STEEL\n"
        + "*SHELL SECTION, ELSET=ESHELL, MATERIAL=STEEL\n2.0\n"
        + "*SURFACE, NAME=BLOCKTOP, TYPE=ELEMENT\n1, S5\n"
        + "*SURFACE, NAME=SHELLFACE, TYPE=ELEMENT\n2, S2\n"
        + "*TIE, NAME=T1, POSITION TOLERANCE=0.5\nSHELLFACE, BLOCKTOP\n"
        + "*STEP\n*STATIC\n"
        + "*DLOAD\n2, P, 1.0\n"
        + "*NODE PRINT, NSET=NALL, TOTALS=ONLY\nU\n"
        + "*NODE FILE\nU\n"
        + "*EL FILE\nS\n"
        + "*END STEP\n"
    )


# --------------------------------------------------------------------------
# D3 - composite shell section alongside a solid section        (premise P3)
# --------------------------------------------------------------------------


def deck_d3() -> str:
    """D1 with a two-layer composite shell section."""
    return deck_d1().replace(
        "*SHELL SECTION, ELSET=ESHELL, MATERIAL=STEEL\n2.0\n",
        "*SHELL SECTION, ELSET=ESHELL, COMPOSITE\n"
        "1.0, , STEEL\n"
        "1.0, , STEEL\n",
    )


# --------------------------------------------------------------------------
# D2 - does a shell<->solid *TIE transfer moment?                (premise P2)
# --------------------------------------------------------------------------
#
# Shell cantilever in the plane z=0, root edge at y=0, which is an *edge*
# interface with the block (the E family of the plan's section 8.4).
# Tip load in -z at nodes 13, 14.
#

#   variant "clamped"  shell root edge nodes fixed in DOF 1-6 (reference)
#   variant "hinge"    shell root edge nodes fixed in DOF 1-3 only -- the
#                      manual's definition of a hinge for a shell, so this is
#                      the deformation a tie must be much stiffer than
#   variant "tie"      shell root edge tied to the block's y=0 face (S5)
#   variant "free"     no coupling at all (must be a rigid-body mechanism)
#
# A tie that carries moment lands close to "clamped"; a tie that behaves as a
# hinge lands close to "hinge", which is unbounded and so is unusable as a
# numeric reference.  "free" exists only to confirm the harness can tell a
# mechanism from a solution.

SHELL_CANTILEVER_NODES = """\
9, 0., 0., 0.
10, 10., 0., 0.
11, 10., 10., 0.
12, 0., 10., 0.
13, 10., 20., 0.
14, 0., 20., 0.
"""


# --------------------------------------------------------------------------
# D2 - does a shell<->solid *TIE transfer moment?                (premise P2)
# --------------------------------------------------------------------------
SHELL_CANTILEVER_ELEMS = """\
*ELEMENT, TYPE=S4, ELSET=ESHELL
2, 9, 10, 11, 12
3, 12, 11, 13, 14
"""


def deck_d2(variant: str) -> str:
    if variant == "clamped":
        coupling = "*BOUNDARY\n9, 1, 6\n10, 1, 6\n"
    elif variant == "hinge":
        coupling = "*BOUNDARY\n9, 1, 3\n10, 1, 3\n"
    elif variant == "free":
        coupling = ""
    elif variant == "tie":
        # Shell local edge 1-2 is face S3; block face S5 is the y=0 plane.
        coupling = (
            "*SURFACE, NAME=ROOTEDGE, TYPE=ELEMENT\n2, S3\n"
            "*SURFACE, NAME=BLOCKY0, TYPE=ELEMENT\n1, S5\n"
            "*TIE, NAME=T1, POSITION TOLERANCE=0.5\nROOTEDGE, BLOCKY0\n"
        )
    else:
        raise ValueError(f"unknown D2 variant: {variant!r}")

    return (
        _header(f"D2 shell/solid coupling, variant={variant}")
        + "*NODE\n"
        + BLOCK_NODES
        + SHELL_CANTILEVER_NODES
        + BLOCK_ELEM
        + SHELL_CANTILEVER_ELEMS
        + BLOCK_FIX
        + coupling
        + "*NSET, NSET=NALL, GENERATE\n1, 14\n"
        + MATERIAL
        + "*SOLID SECTION, ELSET=ESOLID, MATERIAL=STEEL\n"
        + "*SHELL SECTION, ELSET=ESHELL, MATERIAL=STEEL\n2.0\n"
        + "*STEP\n*STATIC\n"
        + "*CLOAD\n13, 3, -1.0\n14, 3, -1.0\n"
        + "*NODE PRINT, NSET=NALL\nU\n"
        + "*NODE FILE\nU\n"
        + "*EL FILE\nS\n"
        + "*END STEP\n"
    )


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

DISPLACEMENT_BLOCK = re.compile(
    r"displacements \(vx,vy,vz\) for set (?P<set>\S+) and time\s+\S+\s*\n(?P<body>(?:\s*\d+.*\n)+)"
)


def parse_displacements(dat_text: str) -> dict[int, tuple[float, float, float]]:
    """Node id -> (ux, uy, uz) from the first displacement block in a .dat."""
    match = DISPLACEMENT_BLOCK.search(dat_text)
    if match is None:
        return {}
    out: dict[int, tuple[float, float, float]] = {}
    for line in match.group("body").splitlines():
        parts = [p for p in re.split(r"[,\s]+", line.strip()) if p]
        if len(parts) < 4:
            continue
        try:
            node = int(float(parts[0]))
            vals = [float(p.replace("D", "E")) for p in parts[1:4]]
        except ValueError:
            continue
        out[node] = (vals[0], vals[1], vals[2])
    return out


def run_ccx(deck: str, name: str, ccx: str, keep: bool) -> dict:
    """Write deck.inp, run ccx, return a result dict."""
    workdir = tempfile.mkdtemp(prefix=f"mixed_premise_{name}_")
    inp = os.path.join(workdir, f"{name}.inp")
    with open(inp, "w") as handle:
        handle.write(deck)

    try:
        proc = subprocess.run(
            [ccx, "-i", name],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        stdout = proc.stdout + proc.stderr
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        stdout, returncode = "TIMEOUT", None

    dat_path = os.path.join(workdir, f"{name}.dat")
    dat = ""
    if os.path.exists(dat_path):
        with open(dat_path) as handle:
            dat = handle.read()

    errors = [ln for ln in dat.splitlines() if "*ERROR" in ln]
    errors += [ln for ln in stdout.splitlines() if "*ERROR" in ln]
    result = {
        "name": name,
        "workdir": workdir,
        "returncode": returncode,
        "dat": dat,
        "stdout": stdout,
        "errors": errors,
        "displacements": parse_displacements(dat),
        # ccx prints "Job finished" and returns 0 on a completed run.  A non-zero
        # exit alone is not conclusive (ccx returns 201 on a clean input error),
        # and an empty .dat is normal when only *NODE FILE was requested.
        "ok": returncode == 0 and not errors and "Job finished" in stdout,
    }
    if not keep:
        shutil.rmtree(workdir, ignore_errors=True)
    else:
        result["kept"] = workdir
    return result


def report(result: dict, headline: str) -> None:
    status = "OK  " if result["ok"] else "FAIL"
    print(f"[{status}] {headline}")
    print(f"        ccx exit={result['returncode']}")
    for err in result["errors"][:5]:
        print(f"        {err.strip()}")
    if not result["ok"] and not result["errors"]:
        tail = [ln for ln in result["stdout"].splitlines() if ln.strip()][-5:]
        for line in tail:
            print(f"        | {line.strip()}")


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


def case_d1(ccx: str, keep: bool) -> bool:
    result = run_ccx(deck_d1(), "d1", ccx, keep)
    report(result, "D1 / P1  ccx accepts a mixed solid+shell deck")
    return result["ok"]


def case_d3(ccx: str, keep: bool) -> bool:
    result = run_ccx(deck_d3(), "d3", ccx, keep)
    report(result, "D3 / P3  composite *SHELL SECTION beside *SOLID SECTION")
    return result["ok"]


def case_d2(ccx: str, keep: bool) -> bool | None:
    """Return True if *TIE behaves as a moment-carrying tie, False if hinge,
    None if the probe could not reach a verdict."""
    print("\nD2 / P2  does *TIE between shell and solid carry moment?")
    runs = {}
    for variant in ("clamped", "hinge", "tie"):
        runs[variant] = run_ccx(deck_d2(variant), f"d2_{variant}", ccx, keep)

    for variant in ("clamped", "hinge", "tie"):
        report(runs[variant], f"  D2 variant '{variant}'")

    def tip(variant: str) -> float | None:
        disps = runs[variant]["displacements"]
        vals = [abs(disps[n][2]) for n in (13, 14) if n in disps]
        return sum(vals) / len(vals) if vals else None

    u_clamped, u_hinge, u_tie = tip("clamped"), tip("hinge"), tip("tie")
    print(
        f"        tip |uz|: clamped={u_clamped} hinge={u_hinge} tie={u_tie}"
    )

    if u_clamped is None or u_tie is None:
        print("        VERDICT: inconclusive - no tip displacements recovered")
        return None

    ratio = u_tie / u_clamped
    print(f"        ratio tie/clamped = {ratio:.4f}")
    if u_hinge is not None:
        print(f"        ratio hinge/clamped = {u_hinge / u_clamped:.4g}")

    # Tolerance fixed before the run, per docs/plan-mixed-shell-solid-fem.md 9.4
    if ratio < 1.10:
        print("        VERDICT: TIE carries moment (P2 holds)")
        return True
    if ratio > 3.0:
        print("        VERDICT: TIE is a hinge (P2 FAILS)")
        return False
    print(f"        VERDICT: inconclusive - ratio {ratio:.4f} in (1.10, 3.0]")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ccx", default=DEFAULT_CCX, help="path to the ccx binary")
    parser.add_argument("--keep", action="store_true", help="keep the work directories")
    parser.add_argument(
        "cases",
        nargs="*",
        default=None,
        help="which cases to run (default: all)",
    )
    args = parser.parse_args(argv)
    # Not argparse `choices`: a nargs="*" positional validates its empty default
    # against choices and rejects it, so an argument-less call fails.
    if not args.cases:
        args.cases = ["d1", "d3", "d2"]
    unknown = [case for case in args.cases if case not in ("d1", "d3", "d2")]
    if unknown:
        parser.error(f"unknown case(s): {', '.join(unknown)}; choose from d1, d3, d2")

    if not os.path.exists(args.ccx):
        print(f"ccx not found at {args.ccx}; use --ccx to point at one", file=sys.stderr)
        return 2

    results = {}
    if "d1" in args.cases:
        results["d1"] = case_d1(args.ccx, args.keep)
    if "d3" in args.cases:
        results["d3"] = case_d3(args.ccx, args.keep)
    if "d2" in args.cases:
        results["d2"] = case_d2(args.ccx, args.keep)

    print("\nsummary")
    for case in ("d1", "d3", "d2"):
        if case not in results:
            continue
        value = results[case]
        label = {True: "holds", False: "FAILS", None: "inconclusive"}[value]
        print(f"  {case}: {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

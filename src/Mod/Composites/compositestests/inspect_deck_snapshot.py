# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Snapshot every generated CalculiX deck, so a stage can prove it changed none.

The mixed shell+solid plan's invariant is "with the flag off, every generated
.inp is byte-identical to today's". The obvious way to check that - compare
against the golden decks in femtest/data/calculix/ - conflates two different
claims:

    my change altered nothing                    <- what the plan needs
    the output has not changed since the goldens <- currently false

Six of those goldens are stale for reasons unrelated to the plan (the examples
were renamed and re-meshed without refreshing them), so they cannot serve as the
reference. This tool isolates the first claim instead: hash every example deck
with the tree as it stands, then re-hash after a change and require the hashes
to be equal. A stale golden cannot mask a leak and no golden has to be current.

It compares **outcomes**, not just hashes. An example that stops producing a deck
leaves the hash map and enters ``not_written``, and an example whose *failure*
changes moves no hash at all - a digest-only comparison is blind to both, which
is the drift it most needs to catch. So the reason an example could not be
written is snapshotted and diffed too, and a changed reason is printed with its
old and new text.

Usage, from the repo root:

    FreeCADCmd -c "
    import sys
    sys.path.insert(0, '<repo>/src/Mod')
    sys.path.insert(0, '<repo>/src/Mod/Fem')
    from Composites.compositestests.inspect_deck_snapshot import main
    main(['--check'])
    "

    --write   create or refresh the snapshot (do this on a tree you trust)
    --check   report any deck whose hash moved (the default)
    --list    print the snapshot without generating anything
    --names   print the examples that would be snapshotted and stop

Only lines the writer emits that vary run to run are normalised away, using the
same filter the ccxtools golden comparison uses, so the hash is of the deck's
content and not of its timestamp.

Under `FreeCADCmd -c` you must flush stdout before exiting: `raise SystemExit`
there discards whatever Python has buffered, so a comparison prints into a lost
buffer and the run looks silent. Assign the status, `sys.stdout.flush()`, and
do not raise.

REPRODUCIBILITY, MEASURED. Run twice on an unchanged tree with the mesher at
its default thread count, 11 of 42 decks differed - permuted element node lists,
reordered nodes, moved coordinates - and one example intermittently produced no
mesh at all. The cause is Gmsh's multicore meshing: MeshGmsh.ParallelProcessing
defaults on (femobjects/mesh_gmsh.py) and gmshtools writes
``General.NumThreads = idealThreadCount()`` into every .geo, and multithreaded
Gmsh is not order-stable. Pinning it to one thread - what --threads defaults to,
restoring the user's value afterwards - makes two runs of the same tree produce
42 decks with none changed, so a byte comparison is meaningful after all. While
running with --threads above 1, do not read a moved deck as a real change.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import shutil
import tempfile
from pathlib import Path

import FreeCAD

from femtools import ccxtools

# Volatile header lines the writer stamps into every deck. Kept in step with
# femtest.app.support_utils.compare_inp_files, which drops the same ones; a
# deck hash that includes them would differ on every run.
VOLATILE_PREFIXES = ("**   written ", "**   file ", "17671.0,1")

SNAPSHOT_PATH = Path(__file__).with_name("deck_snapshot.json")

# Examples that are helpers rather than runnable analyses, plus the module the
# browser uses. get_information() already excludes most of these; this is the
# belt to that braces.
SKIP_MODULES = {"__init__", "examplesgui", "manager"}

# The mesher writes `General.NumThreads = <this preference>` into every .geo, and
# multithreaded Gmsh is not run-to-run reproducible: element node lists permute
# and node coordinates move between runs of the same tree. Pinning it is the only
# way to make a generated deck reproducible without touching the example modules.
GMSH_PREFERENCE_PATH = "User parameter:BaseApp/Preferences/Mod/Fem/Gmsh"


@contextlib.contextmanager
def pinned_gmsh_threads(count: int):
    """Run with Gmsh pinned to ``count`` threads, restoring the user's value."""
    group = FreeCAD.ParamGet(GMSH_PREFERENCE_PATH)
    previous = group.GetInt("NumOfThreads", 0)
    group.SetInt("NumOfThreads", count)
    try:
        yield
    finally:
        if previous:
            group.SetInt("NumOfThreads", previous)
        else:
            group.RemInt("NumOfThreads")


def _normalised_digest(path: Path) -> str:
    """SHA-256 of a deck with its volatile header lines removed."""
    lines = [
        line.replace("\r\n", "\n")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        if not line.startswith(VOLATILE_PREFIXES)
    ]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def discover_examples() -> list[str]:
    """femexamples modules that build an analysis a ccx solver can be run on.

    Discovered from get_information() rather than from a list kept here, so an
    example added later is snapshotted without anyone remembering to add it.
    """
    femexamples_dir = Path(FreeCAD.getHomePath()) / "Mod" / "Fem" / "femexamples"
    names = []
    for path in sorted(femexamples_dir.glob("*.py")):
        name = path.stem
        if name in SKIP_MODULES:
            continue
        try:
            module = importlib.import_module(f"femexamples.{name}")
        except Exception:
            continue
        get_information = getattr(module, "get_information", None)
        setup = getattr(module, "setup", None)
        if get_information is None or setup is None:
            continue
        try:
            info = get_information()
        except Exception:
            continue
        if "ccxtools" in info.get("solvers", []):
            names.append(name)
    return names


def generate_deck(module_name: str, workdir: Path) -> Path | None:
    """Build the example and write its deck, exactly as the ccxtools test does."""
    document = FreeCAD.newDocument("deck_snapshot")
    try:
        module = importlib.import_module(f"femexamples.{module_name}")
        module.setup(document, "ccxtools")
        fea = ccxtools.FemToolsCcx(document.Analysis, document.CalculiXCcxTools, test_mode=True)
        fea.update_objects()
        fea.setup_working_dir(str(workdir))
        error = fea.check_prerequisites()
        if error:
            # Expected for a mixed model while the flag is off, and for any
            # example the guard now rejects. Not a snapshot failure - record it.
            raise RuntimeError(str(error).strip())
        error = fea.write_inp_file()
        if error:
            raise RuntimeError(str(error).strip())
        return workdir / "Mesh.inp"
    finally:
        FreeCAD.closeDocument(document.Name)


def build_snapshot(threads: int = 1) -> tuple[dict, dict]:
    """Return ({example: digest}, {example: reason_it_was_skipped})."""
    with pinned_gmsh_threads(threads):
        return _build_snapshot()


def _build_snapshot() -> tuple[dict, dict]:
    digests: dict[str, str] = {}
    skipped: dict[str, str] = {}
    # A FIXED work directory, not a fresh temporary one. The path reaches the
    # deck (the writer logs *INCLUDE and file lines containing it), so a random
    # path changes the hash of every deck on every run and the snapshot can
    # never reproduce. Verified by the check failing with the same
    # PYTHONHASHSEED, which ruled out string-hash ordering as the cause.
    root = Path(tempfile.gettempdir()) / "deck_snapshot_work"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for module_name in discover_examples():
        workdir = root / module_name
        workdir.mkdir()
        try:
            deck = generate_deck(module_name, workdir)
        except Exception as exc:
            skipped[module_name] = f"{type(exc).__name__}: {exc}"[:200]
            continue
        if deck is None or not deck.exists():
            skipped[module_name] = "writer produced no deck"
            continue
        digests[module_name] = _normalised_digest(deck)
    return digests, skipped


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(digests: dict, skipped: dict, path: Path = SNAPSHOT_PATH) -> None:
    payload = {
        "_comment": (
            "Hashes of generated CalculiX decks with volatile header lines removed. "
            "Proves a change altered no deck; independent of whether any golden is "
            "current. Refresh with --write only on a tree you trust."
        ),
        "decks": dict(sorted(digests.items())),
        "not_written": dict(sorted(skipped.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _outcomes(decks: dict, skipped: dict) -> dict:
    """Every example mapped to what happened to it: a digest, or why it has none."""
    outcomes = {name: ("written", digest) for name, digest in decks.items()}
    outcomes.update({name: ("not written", reason) for name, reason in skipped.items()})
    return outcomes


def compare(current: dict, recorded: dict, skipped: dict) -> int:
    """Report anything that moved, including why an example could not be written.

    Comparing digests alone is not enough, and the gap is not theoretical: an
    example that stops producing a deck leaves the digest map and enters
    ``not_written``, and an example whose *failure* changes alters no digest at
    all. Both are exactly the drift this tool exists to catch, and both walked
    straight through a digest-only comparison. So outcomes are compared as a
    whole, and a changed reason is reported with its old and new text.
    """
    recorded_outcomes = _outcomes(recorded.get("decks", {}), recorded.get("not_written", {}))
    if not recorded_outcomes:
        print("No snapshot to compare against. Run --write first.")
        return 2
    current_outcomes = _outcomes(current, skipped)

    moved: list[str] = []
    for name in sorted(set(recorded_outcomes) & set(current_outcomes)):
        was_kind, was_value = recorded_outcomes[name]
        now_kind, now_value = current_outcomes[name]
        if was_kind != now_kind:
            moved.append(f"  {was_kind} -> {now_kind}: {name}")
        elif was_value != now_value:
            moved.append(f"  {was_kind} changed: {name}")
            if was_kind == "not written":
                moved.append(f"      was: {was_value}")
                moved.append(f"      now: {now_value}")

    added = sorted(set(current_outcomes) - set(recorded_outcomes))
    missing = sorted(set(recorded_outcomes) - set(current_outcomes))

    print(f"examples snapshotted : {len(recorded_outcomes)}")
    print(f"examples seen        : {len(current_outcomes)}")
    print(f"  written            : {len(current)}")
    print(f"  not written        : {len(skipped)}")
    for name in added:
        print(f"  ADDED: {name} ({current_outcomes[name][0]})")
    for name in missing:
        print(f"  MISSING: {name} ({recorded_outcomes[name][0]})")
    for line in moved:
        print(line)

    ok = not moved and not added and not missing
    print(
        "\nverdict:",
        "no deck changed and no example moved" if ok else "SNAPSHOT MOVED",
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="create or refresh the snapshot")
    group.add_argument("--check", action="store_true", help="report moved decks (default)")
    group.add_argument("--list", action="store_true", help="print the snapshot and stop")
    group.add_argument("--names", action="store_true", help="list examples and stop")
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="Gmsh thread count to pin for the run (default 1: reproducible)",
    )
    parser.add_argument(
        "--snapshot",
        default="",
        help="snapshot file to read or write (default: beside this module)",
    )
    args = parser.parse_args(argv)

    if args.list:
        recorded = load_snapshot(_snapshot_path(args))
        for name, digest in recorded.get("decks", {}).items():
            print(f"{digest[:16]}  {name}")
        return 0

    if args.names:
        for name in discover_examples():
            print(name)
        return 0

    # The invariant this tool records is "with the flag off, every deck is
    # unchanged". The flag now defaults to on, so set it off explicitly here,
    # or the mixed examples would start appearing as new decks and the
    # snapshot would stop meaning what it says.
    flag_group = FreeCAD.ParamGet(MIXED_FLAG_PATH)
    previous_flag = flag_group.GetBool(MIXED_FLAG_NAME, True)
    flag_group.SetBool(MIXED_FLAG_NAME, False)
    try:
        current, skipped = build_snapshot(args.threads)
    finally:
        flag_group.SetBool(MIXED_FLAG_NAME, previous_flag)
    snapshot_path = _snapshot_path(args)
    if args.write:
        save_snapshot(current, skipped, snapshot_path)
        print(f"wrote {snapshot_path} with {len(current)} decks")
        return 0
    return compare(current, load_snapshot(snapshot_path), skipped)


def _snapshot_path(args) -> Path:
    return Path(args.snapshot) if args.snapshot else SNAPSHOT_PATH


MIXED_FLAG_PATH = "User parameter:BaseApp/Preferences/Mod/Fem/General"
MIXED_FLAG_NAME = "AllowMixedShellSolid"


if __name__ == "__main__":
    raise SystemExit(main())

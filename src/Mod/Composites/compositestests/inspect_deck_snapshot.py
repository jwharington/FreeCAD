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

NOT YET USABLE AS A PROOF. Run twice on an unchanged tree, it reported 11 decks
CHANGED and one MISSING (`boxanalysis_static` failed to generate the second
time at all). Generation is therefore not reproducible run to run, so the
snapshot cannot yet distinguish a real leak from noise, and no snapshot file is
committed. Diagnose that before relying on this: the likely causes are state
leaking between examples built in one process, a document name that FreeCAD
silently uniquifies, or unordered iteration feeding the writer - which the repo
has been bitten by before. Note this cuts both ways: if generated decks really
do differ run to run, then "byte-identical deck" is not an achievable invariant
as the plan states it, and that needs settling before Stage 2 depends on it.
"""

from __future__ import annotations

import argparse
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


def build_snapshot() -> tuple[dict, dict]:
    """Return ({example: digest}, {example: reason_it_was_skipped})."""
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


def load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def save_snapshot(digests: dict, skipped: dict) -> None:
    payload = {
        "_comment": (
            "Hashes of generated CalculiX decks with volatile header lines removed. "
            "Proves a change altered no deck; independent of whether any golden is "
            "current. Refresh with --write only on a tree you trust."
        ),
        "decks": dict(sorted(digests.items())),
        "not_written": dict(sorted(skipped.items())),
    }
    SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def compare(current: dict, recorded: dict, skipped: dict) -> int:
    """Report decks that moved, appeared or vanished. Returns a shell status."""
    recorded_decks = recorded.get("decks", {})
    if not recorded_decks:
        print("No snapshot to compare against. Run --write first.")
        return 2

    changed = [n for n in current if n in recorded_decks and current[n] != recorded_decks[n]]
    added = [n for n in current if n not in recorded_decks]
    missing = [n for n in recorded_decks if n not in current]
    ok = not changed and not added and not missing

    print(f"decks snapshotted : {len(recorded_decks)}")
    print(f"decks generated   : {len(current)}")
    for label, names in (("CHANGED", changed), ("ADDED", added), ("MISSING", missing)):
        for name in names:
            print(f"  {label}: {name}")
    if skipped:
        print(f"not written ({len(skipped)}) - check_prerequisites refused, which is")
        print("expected for a mixed model while the flag is off:")
        for name, reason in sorted(skipped.items()):
            print(f"  {name}: {reason}")

    print("\nverdict:", "no deck changed" if ok else "DECKS MOVED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="create or refresh the snapshot")
    group.add_argument("--check", action="store_true", help="report moved decks (default)")
    group.add_argument("--list", action="store_true", help="print the snapshot and stop")
    group.add_argument("--names", action="store_true", help="list examples and stop")
    args = parser.parse_args(argv)

    if args.list:
        recorded = load_snapshot()
        for name, digest in recorded.get("decks", {}).items():
            print(f"{digest[:16]}  {name}")
        return 0

    if args.names:
        for name in discover_examples():
            print(name)
        return 0

    current, skipped = build_snapshot()
    if args.write:
        save_snapshot(current, skipped)
        print(f"wrote {SNAPSHOT_PATH} with {len(current)} decks")
        return 0
    return compare(current, load_snapshot(), skipped)


if __name__ == "__main__":
    raise SystemExit(main())

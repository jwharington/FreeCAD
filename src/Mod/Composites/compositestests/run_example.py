# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Run one registered Composites example by id and report its document.

Examples are package modules with relative imports, so they cannot be launched
by path — the registry is the entry point. Examples print their own status
lines; this prints the resulting document afterwards so a silent example still
shows what it built.

Usage, through the repo runner which forwards arguments:

    run-script.sh .../compositestests/run_example.py mould_fixture_loft
    run-script.sh .../compositestests/run_example.py mould_fixture_loft --save /tmp/loft.FCStd
"""

import argparse

from Composites.compositeexamples import runner


def _print_objects(doc):
    for obj in doc.Objects:
        print("  %-24s %-24s %s" % (obj.Name, obj.TypeId, obj.State), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example_id", help="registry id, e.g. mould_fixture_loft")
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="save the example's document to PATH",
    )
    args = parser.parse_args(argv)

    result = runner.run(args.example_id, run_solver=False)
    doc = result["doc"]

    print("example  : %s" % args.example_id, flush=True)
    print("document : %s" % doc.Name, flush=True)
    _print_objects(doc)
    if args.save:
        doc.saveAs(args.save)
        print("saved    : %s" % args.save, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

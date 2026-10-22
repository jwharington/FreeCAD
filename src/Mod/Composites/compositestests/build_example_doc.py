# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Build a registered Composites example headless and save it as .FCStd.

Some examples are expensive to recompute: the fixtured lofted mould grinds for
minutes in its boolean cuts, and a GUI recomputing it cannot be used or even
screenshotted. Building the document headless and saving it lets FreeCAD open
finished geometry instead, so the expensive stage runs once, in a process whose
output is a log rather than a frozen window.

The document is built through the examples' own registry and runner, so this
holds no example-specific knowledge: it names an example, and the example builds
itself. Anything the example leaves switched off is still switched off when the
saved document is opened.

Run it through the headless wrapper, which owns the environment:

    run-script.sh src/Mod/Composites/compositestests/build_example_doc.py \
        --example mould_fixture_loft --out /tmp/mould_fixture_loft.FCStd
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

import FreeCAD as App

from Composites.compositeexamples import runner

DEFAULT_EXAMPLE = "mould_fixture_loft"


def _say(text):
    """Print one line, flushed.

    FreeCADCmd leaves Python's stdout block-buffered and exits without flushing
    it, so a long run's report would otherwise be discarded — and on a run that
    takes minutes, the lines are the only progress there is.
    """
    print(text, flush=True)


def _resolve_example(name):
    """`name` if the registry knows it, otherwise a refusal that lists them."""
    known = runner.list_examples()
    if name not in known:
        raise SystemExit(f"unknown example '{name}'. Known ids: {', '.join(known)}")
    return name


def _document_of(built):
    """The document an example built into.

    Examples return what they made — a dict carrying the document, or whatever
    else they consider their result — so the document is looked for there first
    and falls back to the one the example created.
    """
    if isinstance(built, dict) and "doc" in built:
        return built["doc"]
    documents = App.listDocuments()
    if not documents:
        raise SystemExit("the example created no document")
    return next(iter(documents.values()))


def build(example, out_path):
    """Build `example`, save its document to `out_path`.

    ``(document, saved path, seconds)``. The seconds cover the example's own
    recompute, which is the part that can take minutes.
    """
    started = time.perf_counter()
    document = _document_of(runner.run(example))
    elapsed = time.perf_counter() - started
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.saveAs(str(out_path))
    return document, out_path, elapsed


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--example",
        default=DEFAULT_EXAMPLE,
        help="Registry id of the example to build. Defaults to %(default)s; "
             "the ids are listed by the refusal for an unknown one.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="OUT.FCStd",
        help="Where to write the document. Defaults to the temporary directory, "
             "as <example id>.FCStd.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    example = _resolve_example(args.example)
    out_path = args.out or Path(tempfile.gettempdir()) / f"{example}.FCStd"

    document, saved, elapsed = build(example, out_path)

    _say(f"example : {example}")
    _say(f"document: {document.Name}")
    _say(f"objects : {[obj.Name for obj in document.Objects]}")
    _say(f"elapsed : {elapsed:.1f} s")
    _say(f"saved   : {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
saved document is opened — which for the mould examples is the levelling and the
seal groove, so showing those means asking for them by name:

    --set Mould.SkirtLevelling=s-curve --set MouldFixture.SealGroove=True

The document is recomputed after the settings, because a property that changes
geometry only takes effect on a recompute — and for these examples that recompute
is the expensive part, so it is timed and reported.

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


def _property_value(obj, name, text):
    """`text` as the type of `obj`'s `name` property expects.

    Read from the property itself rather than guessed from the text, so a bool,
    an int, a length and a string can all be written the obvious way.
    """
    kind = obj.getTypeIdOfProperty(name)
    if kind.endswith("PropertyBool"):
        return text.strip().lower() in ("1", "true", "yes", "on")
    if kind.endswith("PropertyInteger"):
        return int(text)
    if kind.endswith(("PropertyFloat", "PropertyLength", "PropertyAngle")):
        return float(text)
    return text


def _apply_settings(document, settings):
    """Set each `Object.Property=value` on `document`, saying what it set."""
    for setting in settings:
        path, _, text = setting.partition("=")
        name, _, prop = path.partition(".")
        obj = document.getObject(name)
        if obj is None or not prop:
            raise SystemExit(f"--set expects Object.Property=value, not '{setting}'")
        if not hasattr(obj, prop):
            raise SystemExit(f"{name} has no property '{prop}'")
        value = _property_value(obj, prop, text)
        setattr(obj, prop, value)
        _say(f"set    : {name}.{prop} = {value!r}")


def build(example, out_path, settings=(), build_kwargs=None):
    """Build `example`, apply `settings`, save its document to `out_path`.

    ``build_kwargs`` are passed to the example's own ``build()``, so an option that is
    a solve input (the skirt continuity) reaches the first recompute instead of forcing
    a second one through ``settings``. ``(document, saved path, seconds)``. The seconds
    cover the example's own recompute plus the one the settings force, which is the part
    that can take minutes.
    """
    started = time.perf_counter()
    document = _document_of(runner.run(example, **(build_kwargs or {})))
    if settings:
        _apply_settings(document, settings)
        document.recompute()
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
    parser.add_argument(
        "--skirt-continuity",
        choices=("c0", "c1"),
        default=None,
        help="Skirt band continuity to build with, for the examples that take one. It "
             "is a solve input, so unlike --set it does not cost a second solve.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="OBJ.PROP=VALUE",
        dest="settings",
        help="Set a property on a built object, once per property, before the "
             "document is recomputed and saved. The value is read as the "
             "property's own type. Repeatable.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    example = _resolve_example(args.example)
    out_path = args.out or Path(tempfile.gettempdir()) / f"{example}.FCStd"

    build_kwargs = (
        {"skirt_continuity": args.skirt_continuity} if args.skirt_continuity else {}
    )
    document, saved, elapsed = build(example, out_path, args.settings, build_kwargs)

    _say(f"example : {example}")
    _say(f"document: {document.Name}")
    _say(f"objects : {[obj.Name for obj in document.Objects]}")
    _say(f"elapsed : {elapsed:.1f} s")
    _say(f"saved   : {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

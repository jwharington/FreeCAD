# SPDX-License-Identifier: LGPL-2.1-or-later

"""Render a composite FEM sweep from the runs' own JSON artifacts.

Every run of the study driver writes its numbers to a JSON artifact beside its
log: the per-case results, the buckling factors per mode, the layups, the mass,
the frequencies, the geometry signature and the provenance.  This module reads
those artifacts and nothing else.

It deliberately does not read the logs.  A log is prose, and a summary built by
reading sentences back goes blank one column at a time without complaining;
the artifact is written by the run that knows, in a shape the report can rely
on.

    run_report.py run.json [run.json ...]
    run_report.py --markdown report.md --json-report report.json run.json

Named explicitly, with no "every run in the results directory" mode: that
directory keeps every sweep ever done, including superseded case tables, and a
stale row is indistinguishable from a current one here.

Run it through FreeCADCmd, which is what puts the workbench on the path.
"""

import argparse
import datetime
import json
import os


SCHEMA = 1


def _variant_of(stem):
    """cut or nocut, from the run's own name — the only place it is written.

    The runner never reports which variant it was: it is built from arguments,
    and `--uncut` says nothing once it has been applied. The name the sweep
    gave the run is the surviving record, so a file renamed by hand loses it.
    """
    parts = stem.split("_")
    return parts[1] if len(parts) > 2 else "?"


def artifact_of(path):
    """The run's JSON artifact for a path, log or artifact.

    A log names its artifact and an artifact names its log, so a sweep
    directory can be pointed at by whichever file the caller has to hand.
    Returns None when there is no artifact — that run cannot be reported
    from here.
    """
    if path.endswith(".json"):
        return path
    if path.endswith(".log"):
        candidate = path[: -len(".log")] + ".json"
        return candidate if os.path.isfile(candidate) else None
    return None


def _stem_of(path):
    if path.endswith(".json"):
        path = path[: -len(".json")]
    elif path.endswith(".log"):
        path = path[: -len(".log")]
    return os.path.splitext(os.path.basename(path))[0]


def report(paths):
    """What a sweep knows, read from each run's own artifact.

    ``paths`` may name artifacts or logs; a log is followed to its artifact.
    A run with no artifact is noted rather than guessed at from its log.
    """
    runs, notes = [], []
    for path in paths:
        artifact = artifact_of(path)
        stem = _stem_of(path)
        if artifact is None:
            notes.append(
                "%s: no JSON artifact, and the report reads no logs" % stem
            )
            continue
        with open(artifact) as handle:
            data = json.load(handle)
        mass = data.get("mass") if isinstance(data.get("mass"), dict) else {}
        runs.append(
            {
                "source": "artifact",
                "artifact": artifact,
                "variant": _variant_of(stem),
                "provenance": data.get("provenance", {}),
                "cases": data.get("cases", []),
                "governing": data.get("governing"),
                "criteria": data.get("criteria"),
                "per_case": data.get("per_case", {}),
                "layups": mass.get("layups", {}),
                "frequencies": data.get("frequencies"),
                "solved": data.get("result", True),
            }
        )
    return {
        "schema": SCHEMA,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "runs": runs,
        "notes": notes,
    }


def _seconds(value):
    return "" if value is None else "%.0f s" % value


def _provenance_table(runs):
    lines = [
        "| variant | geometry | mesh | build | mesh time | solve time | git | FreeCAD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        provenance = run["provenance"]
        if not provenance:
            lines.append("| %s | no artifact | | | | | | |" % run["variant"])
            continue
        arguments = provenance.get("geometry_arguments") or {}
        geometry = (
            ", ".join(
                "%s=%s" % (name, arguments[name]) for name in sorted(arguments)
            )
            or "none"
        )
        mesh = "%s (%s)" % (
            provenance.get("mesh_outcome", "?"),
            provenance.get("mesh_key", "?"),
        )
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                run["variant"],
                geometry,
                mesh,
                _seconds(provenance.get("build_seconds")),
                _seconds(provenance.get("mesh_seconds")),
                _seconds(provenance.get("solve_seconds")),
                provenance.get("git", "?"),
                (provenance.get("versions") or {}).get("freecad", "?"),
            )
        )
    return lines


def _case_rows(run):
    """One dict per case: the numbers, and which criterion governs it.

    Buckling exposure is 1/lambda — the exposure form of a load multiplier —
    and never printed beside strain exposure as if the two scales compared.
    """
    rows = []
    for name, entry in sorted((run["per_case"] or {}).items()):
        lambda_min = entry.get("lambda_min")
        exposure = entry.get("strain_exposure")
        if lambda_min:
            governs = (
                "buckling" if 1.0 / lambda_min > (exposure or 0.0) else "strain"
            )
        else:
            governs = "strain (buckling not run)" if exposure is None else "strain"
        rows.append(
            {
                "variant": run["variant"],
                "case": name,
                "disp_mm": entry.get("max_displacement"),
                "exposure": exposure,
                "lambda1": lambda_min,
                "buckling": (1.0 / lambda_min) if lambda_min else None,
                "governs": governs,
                "part": entry.get("part", ""),
            }
        )
    return rows


def _case_table(run):
    lines = [
        "",
        "**%s** — %s" % (run["variant"], ", ".join(run.get("cases", [])) or "no cases"),
        "",
        "| case | disp mm | strain exposure | lambda1 | buckling exposure |"
        " governs | hotspot part |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in _case_rows(run):
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s |"
            % (
                row["case"],
                "" if row["disp_mm"] is None else "%.2f" % row["disp_mm"],
                "" if row["exposure"] is None else "%.3g" % row["exposure"],
                "" if not row["lambda1"] else "%.4g" % row["lambda1"],
                "" if row["buckling"] is None else "%.3g" % row["buckling"],
                row["governs"],
                row["part"],
            )
        )
    return lines


def _buckling_table(runs):
    if not any(
        entry.get("lambda")
        for run in runs
        for entry in (run["per_case"] or {}).values()
    ):
        return [
            "",
            "No buckling solve in these runs (`--no-buckling`, or a run whose "
            "artifact predates lambda). Nothing here says the structure does "
            "not buckle.",
        ]
    lines = ["", "| variant | case | lambda per mode |", "|---|---|---|"]
    for run in runs:
        for name, entry in sorted((run["per_case"] or {}).items()):
            if entry.get("lambda"):
                lines.append(
                    "| %s | %s | %s |"
                    % (
                        run["variant"],
                        name,
                        ", ".join("%.4g" % factor for factor in entry["lambda"]),
                    )
                )
    return lines


def _hotspots(runs):
    """The worst few places, named by geometry part rather than by node."""
    scored = []
    for run in runs:
        for name, entry in (run["per_case"] or {}).items():
            if entry.get("strain_exposure"):
                scored.append(
                    (
                        entry["strain_exposure"],
                        run["variant"],
                        name,
                        entry.get("part", ""),
                        entry.get("point"),
                    )
                )
    if not scored:
        return ["", "No strain exposure was recorded."]
    lines = ["", "| exposure | variant | case | part | where |", "|---|---|---|---|---|"]
    for exposure, variant, name, part, point in sorted(scored, reverse=True)[:8]:
        where = "" if not point else "(%.1f, %.1f, %.1f)" % tuple(point[:3])
        lines.append(
            "| %.3g | %s | %s | %s | %s |"
            % (exposure, variant, name, part or "?", where)
        )
    return lines


def _ply_runs(plies):
    """`6x 0.085 mm +00` — consecutive identical plies compressed.

    The stacks repeat their angles by design, and a layup plan that lists
    twelve identical lines is a plan nobody reads.  The table's laminate
    column already names the material, so plies carry thickness and angle
    only.
    """
    groups = []
    for t, card in plies:
        angle = card.split("[")[-1].rstrip("]") if card else ""
        # Identical only when the thickness matches too: a schedule that
        # thins some plies of an angle must not read as one thick run.
        if groups and groups[-1][:2] == [t, angle]:
            groups[-1][2] += 1
        else:
            groups.append([t, angle, 1])
    return "; ".join(
        "%dx %g mm %s" % (count, t, angle) if count > 1 else "%g mm %s" % (t, angle)
        for t, angle, count in groups
    )


def _layup_table(runs):
    """Every part's layup, as the deck that produced the numbers wrote it."""
    lines = None
    for run in runs:
        layups = run.get("layups") or {}
        if not layups:
            continue
        rows = []
        for member, entry in sorted(layups.items()):
            description = (
                "%d plies, %.3f mm" % (len(entry["plies"]), entry["total_mm"])
                if entry["kind"] == "layered"
                else "smeared, %.3f mm" % entry["total_mm"]
            )
            rows.append(
                (
                    member,
                    entry["section"][: -len("_Section")],
                    description,
                    entry["plies"],
                )
            )
        if lines is None:
            lines = [
                "",
                "## Layup (as the deck writes it)",
                "",
                "What each part of the article carries, ply by ply — the stack "
                "the run's numbers were computed on.  A smeared row is one "
                "isotropic-equivalent layer, its material naming the laminate "
                "it stands for.",
                "",
                "| member | laminate | layup | plies |",
                "|---|---|---|---|",
            ]
        for member, laminate, description, plies in rows:
            lines.append(
                "| %s | %s | %s | %s |"
                % (member, laminate, description, _ply_runs(plies))
            )
    return lines or []


def _frequencies_table(runs):
    """The natural frequencies each run recorded, if it recorded any."""
    lines = None
    for run in runs:
        modes = run.get("frequencies") or []
        if not modes:
            continue
        if lines is None:
            lines = [
                "",
                "## Natural frequencies",
                "",
                "The **unloaded** article's: a `*FREQUENCY` step carries no "
                "load, so these are resonance numbers, not flutter ones.",
                "",
                "| variant | f in Hz, lowest modes |",
                "|---|---|",
            ]
        lines.append(
            "| %s | %s |"
            % (
                run["variant"],
                ", ".join(
                    ("imag" if mode.get("imaginary") else "%.2f" % mode["hz"])
                    for mode in modes
                ),
            )
        )
    return lines or []


def _geometry_name(runs):
    """A filename-safe name of the geometry the runs share.

    The arguments every run agrees on — the variant axis (`cutout`) is not one,
    one sweep spans variants — rendered as tokens, plus the builder digest,
    because the layup schedule lives in the builder and a report name that does
    not say which schedule produced its numbers is how two files with the same
    arguments but different plies get confused.
    """
    shared, builders = None, set()
    for run in runs:
        provenance = run.get("provenance") or {}
        arguments = provenance.get("geometry_arguments") or {}
        builders.add(provenance.get("builder"))
        if shared is None:
            shared = dict(arguments)
            continue
        shared = {
            key: value
            for key, value in shared.items()
            if key in arguments and arguments[key] == value
        }
    tokens = []
    for key in sorted(shared or {}):
        value = shared[key]
        if value is None:
            continue
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        tokens.append("%s%s" % (key, value))
    builders.discard(None)
    tokens.append(sorted(builders)[0][:8] if len(builders) == 1 else "mixed")
    return "-".join(tokens) or "geometry"


def _geometry_report_path(paths, summary):
    """Where the markdown goes when the caller did not name it: beside the runs
    it summarizes, named for the geometry they share."""
    directory = os.path.dirname(paths[0]) if paths else "."
    study = (summary["runs"][0].get("provenance") or {}).get("study", "sweep")
    return os.path.join(directory, "%s-%s.md" % (study, _geometry_name(summary["runs"])))


def write_markdown(path, summary):
    """The report a design decision gets read from."""
    runs = summary["runs"]
    lines = [
        "# Composite FEM sweep",
        "",
        "Generated %s from %d run artifact(s)." % (summary["generated"], len(runs)),
        "",
    ]
    lines += ["## What ran", ""] + _provenance_table(runs)
    lines += ["", "## Per load case", ""]
    for run in runs:
        lines += _case_table(run)
    lines += _layup_table(runs)
    lines += ["", "## Buckling", ""] + _buckling_table(runs)
    lines += _frequencies_table(runs)
    lines += ["", "## Hotspots", ""] + _hotspots(runs)
    lines += ["", "## Governing", ""]
    for run in runs:
        governing = run.get("governing")
        lines.append(
            "- **%s**: %s"
            % (
                run["variant"],
                (
                    "%s by %s, exposure factor %.3g%s"
                    % (
                        governing["case"],
                        governing["mechanism"],
                        governing["exposure"],
                        " in %s" % governing["part"]
                        if governing.get("part")
                        else "",
                    )
                )
                if governing
                else "the run did not reach a governing answer",
            )
        )
    lines += ["", "## How to read this", ""]
    lines += [
        "- Exposure factor is demand over capacity and fails above 1; the worst "
        "case governs.",
        "- `governs` says which of the two criteria is worse for that case. "
        "Buckling exposure is 1/lambda, the exposure form of a load multiplier.",
        "- Buckling hotspots are **not attributed to a part**: mode-shape "
        "attribution is unimplemented, so the cell says nothing rather than "
        "borrowing the static hotspot's part.",
        "- Tsai-Wu and Hashin maxima are computed across the whole result, so "
        "they have no honest place in a per-case table; see the run log.",
    ]
    if summary["notes"]:
        lines += ["", "## Gaps", ""] + ["- %s" % note for note in summary["notes"]]
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def write_json(path, summary):
    with open(path, "w") as handle:
        json.dump(summary, handle, indent=1, sort_keys=True)
    return path


_TSV_COLUMNS = ("variant", "case", "disp_mm", "exposure", "lambda1", "buckling",
                "governs", "part")


def _print_tsv(summary, sep):
    """The per-case table as plain columns, for awk and diff."""
    print(sep.join(_TSV_COLUMNS))
    for run in summary["runs"]:
        for row in _case_rows(run):
            print(sep.join("" if row[column] is None else str(row[column])
                           for column in _TSV_COLUMNS))
    for note in summary["notes"]:
        print(note)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifacts",
        nargs="*",
        help="run artifacts (or their logs, which name them) to summarize",
    )
    parser.add_argument("--tsv", action="store_true",
                        help="print the per-case table as tab-separated columns")
    parser.add_argument(
        "--markdown",
        metavar="PATH",
        nargs="?",
        const="",
        help="write the report a decision gets read from here; without a PATH "
        "it is named for the geometry the runs share, beside them",
    )
    parser.add_argument("--json-report", metavar="PATH",
                        help="write the whole report, provenance and all, here")
    args = parser.parse_args()
    if not args.artifacts:
        parser.error("name the run artifacts to summarize")
    if not (args.tsv or args.markdown is not None or args.json_report):
        parser.error("choose --tsv, --markdown and/or --json-report")

    summary = report(args.artifacts)
    if args.markdown is not None:
        path = args.markdown or _geometry_report_path(args.artifacts, summary)
        print("report: %s" % write_markdown(path, summary))
    if args.json_report:
        print("report: %s" % write_json(args.json_report, summary))
    if args.tsv:
        _print_tsv(summary, "\t")


if __name__ == "__main__":
    main()

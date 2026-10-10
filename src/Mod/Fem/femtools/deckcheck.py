# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Read a CalculiX input deck, and prove the loads in it are the ones asked for.

Two questions about a written deck are worth answering before the solver reads
it, and neither is answered by looking at the model:

* **Does every element carry exactly one section?**  An element with none
  solves with zero thickness, and an element claimed by two sections is
  written twice — both are silent in ccx, which returns plausible numbers.
* **Does the deck's own ``*CLOAD`` resultant equal the load case?**  The file
  ccx consumes is the ground truth; a load that never reached the writer, or a
  second ``*STEP`` that forgot ``OP=NEW`` and inherits the first case's loads,
  is invisible anywhere else.

Everything here reads text.  The one place a mesh is needed — turning the
``*CLOAD`` node ids into positions so a moment can be summed — the mesh is
passed in; nothing reaches for a document or an object name of its own.
"""

import re

import FreeCAD

ELEMENT_NODE_COUNTS = {
    "S3": 3, "S4": 4, "S6": 6, "S8": 8,
    "C3D4": 4, "C3D8": 8, "C3D10": 10, "C3D20": 20,
}

_MATERIAL_CARD = re.compile(r"^\*MATERIAL\b.*?NAME=([^,\s]+)", re.IGNORECASE)


def _attrs(line):
    """The ``KEY=VALUE`` pairs on a deck keyword line, keys upper-cased."""
    out = {}
    for token in line[1:].split(","):
        if "=" in token:
            key, value = token.split("=", 1)
            out[key.strip().upper()] = value.strip()
    return out


def _numbers(tokens):
    """The tokens that are integers."""
    return [token for token in tokens if token.lstrip("-").isdigit()]


def parse_inp(text):
    """A written deck as ``{elements, elsets, sections, section_elsets}``.

    ``elements`` is ``{element id: [node ids]}`` handling wrapped element
    lines via the ``*Element TYPE=`` node count.  ``elsets`` is
    ``{name: {element ids}}``.  ``sections`` is one entry per ``*SHELL
    SECTION`` block — its elset, whether it is a layered ``COMPOSITE`` stack or
    a single plain layer, its ply thicknesses and the material cards it names.
    ``section_elsets`` is the set of elsets a section references.

    Pure text; the caller decides what a section or element set *means* — the
    naming that maps a per-element elset back to its zone is a convention, not
    a property of the deck.
    """
    elements, elsets, sections, section_elsets = {}, {}, [], set()
    mode, open_elset, open_element, expected_nodes = None, None, None, None
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("*"):
            upper = line.upper()
            open_element = None
            open_elset = None
            section = None
            if upper.startswith("*ELEMENT"):
                mode = "elem"
                expected_nodes = None
                for part in line.split(","):
                    up = part.strip().upper()
                    if up.startswith("TYPE="):
                        expected_nodes = ELEMENT_NODE_COUNTS.get(
                            up.split("=", 1)[1].strip())
                    elif up.startswith("ELSET="):
                        open_elset = part.strip().split("=", 1)[1].strip()
                        elsets.setdefault(open_elset, set())
            elif upper.startswith("*ELSET"):
                mode = "elset"
                for part in line.split(","):
                    if part.strip().upper().startswith("ELSET="):
                        open_elset = part.strip().split("=", 1)[1].strip()
                        elsets.setdefault(open_elset, set())
            elif upper.startswith("*SHELL SECTION"):
                mode = "section"
                attrs = _attrs(line)
                section = {"elset": attrs.get("ELSET", ""),
                           "material": attrs.get("MATERIAL", ""),
                           "layered": "COMPOSITE" in upper,
                           "plies": [], "cards": []}
                sections.append(section)
                if section["elset"]:
                    section_elsets.add(section["elset"])
            else:
                mode = None
            continue
        if not line or mode is None:
            continue
        tokens = [token.strip() for token in line.split(",") if token.strip()]
        if mode == "elem":
            if not tokens or len(_numbers(tokens)) != len(tokens):
                continue
            values = [int(token) for token in tokens]
            complete = (open_element is not None and expected_nodes is not None
                        and len(elements[open_element[0]]) >= expected_nodes)
            if open_element is None or complete:
                open_element = values[:1]
                elements[open_element[0]] = []
                if open_elset is not None:
                    elsets[open_elset].add(open_element[0])
                values = values[1:]
            elements[open_element[0]].extend(values)
            if expected_nodes is None:
                open_element = None  # unknown type: one line per element
        elif mode == "elset":
            for value in _numbers(tokens):
                elsets[open_elset].add(int(value))
        elif mode == "section":
            fields = [field.strip() for field in line.split(",")]
            try:
                section["plies"].append(float(fields[0]))
            except ValueError:
                mode = None
                continue
            if len(fields) > 2 and fields[2]:
                section["cards"].append(fields[2])
    return {"elements": elements, "elsets": elsets,
            "sections": sections, "section_elsets": section_elsets}


def owned_by_element(deck):
    """``{element id: {elset names that claim it}}``."""
    owned = {}
    for name, element_ids in deck["elsets"].items():
        for element_id in element_ids:
            owned.setdefault(element_id, set()).add(name)
    return owned


def coverage_problems(deck):
    """Every meshed element carries exactly one section."""
    owned = owned_by_element(deck)
    section_elsets = deck["section_elsets"]
    claimed = {element_id: owners & section_elsets
               for element_id, owners in owned.items()}
    unowned = sorted(element_id for element_id in deck["elements"]
                     if not claimed.get(element_id))
    doubled = sorted(element_id for element_id, owners in claimed.items()
                     if len(owners) > 1)
    problems = []
    if unowned:
        problems.append("%d elements carry no section (ccx: zero thickness), "
                        "e.g. %s" % (len(unowned), unowned[:8]))
    if doubled:
        problems.append("%d elements belong to %d sections at once, e.g. %s: %s"
                        % (len(doubled), len(claimed[doubled[0]]),
                           doubled[0], ", ".join(sorted(claimed[doubled[0]]))))
    return problems


def material_problems(text):
    """Every material card name written twice, which ccx stops on silently.

    CalculiX stops the whole job on a duplicate name and says nothing beyond
    an exit code, so a deck that repeats a card has to fail here, where the
    sentence says which card and why.
    """
    counts = {}
    for line in text.splitlines():
        match = _MATERIAL_CARD.match(line.strip())
        if match:
            name = match.group(1).strip()
            counts[name] = counts.get(name, 0) + 1
    return ["material card %s appears %d times, a duplicate name: ccx stops "
            "the whole deck over one without saying which"
            % (name, counts[name])
            for name in sorted(counts) if counts[name] > 1]


def parse_load_blocks(path):
    """Split a deck into its ``*CLOAD`` blocks.

    Returns ``(synthetic_nodes, before_steps, steps)``.  ``synthetic_nodes``
    are the synthetic ``*NODE`` additions (a distributing-coupling reference
    node): they are not in the mesh but they carry load, so the resultant
    cannot be reconstructed without them.

    A ``*CLOAD`` written outside every ``*STEP`` belongs to step 1, which in a
    batch deck means every later step inherits it too — so a batch deck must
    have an empty ``before_steps``.  ``steps`` come back in deck order, which
    is the order ccx solves them and the order their results come back.  Each
    block records whether its ``*CLOAD`` cards asked for ``OP=NEW``: without it
    a step overrides only the entries it repeats and silently keeps the
    previous case's loads on everything else.
    """
    synthetic_nodes = {}
    before = {"op_new": False, "entries": []}
    steps = []
    block = before
    section = None
    with open(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                keyword = line.split(",")[0].strip().upper()
                if keyword == "*STEP":
                    block = {"op_new": False, "entries": []}
                    steps.append(block)
                elif keyword == "*CLOAD" and "OP=NEW" in line.upper().replace(" ", ""):
                    block["op_new"] = True
                section = keyword
                continue
            parts = [part.strip() for part in line.split(",")]
            if section == "*NODE" and len(parts) >= 4:
                synthetic_nodes[int(parts[0])] = FreeCAD.Vector(
                    float(parts[1]), float(parts[2]), float(parts[3]))
            elif section == "*CLOAD" and len(parts) >= 3:
                block["entries"].append(
                    (int(parts[0]), int(parts[1]), float(parts[2])))
    return synthetic_nodes, before["entries"], steps


def load_entries(path):
    """Every ``*CLOAD`` entry in the file in deck order, plus the synthetic
    ``*NODE`` additions — the single-numbering view of :func:`parse_load_blocks`."""
    synthetic_nodes, before, steps = parse_load_blocks(path)
    entries = list(before)
    for step in steps:
        entries.extend(step["entries"])
    return synthetic_nodes, entries


def verify_loads(path, femmesh, origin, label, cases, targets):
    """The written deck's load resultant must equal the load case exactly.

    ``targets`` is the study's own answer to "what load should be in the file",
    keyed by case name.  It is asked for rather than computed here because what
    a wrench *means* — which components exist, which sign convention, which
    point moments are referred to — belongs to the article being analysed, and
    a checker that guessed it would verify the wrong thing confidently.

    With one case, every ``*CLOAD`` line in the file is summed and compared
    against the target — the ground truth is the file ccx consumes, not the
    object properties.

    With a batch, the check is per ``*STEP`` block.  A block that forgot
    ``OP=NEW`` keeps the previous case's loads on every node it did not repeat,
    and a block that wrote nothing solves the previous case at all, so both
    must fail here rather than solve to a plausible-looking wrong answer.  Node
    counts are deliberately not compared between steps: the nodal spread of a
    wrench depends on the wrench, so two legitimate cases load different
    numbers of nodes while both deliver their resultant exactly.
    """
    synthetic_nodes, before, steps = parse_load_blocks(path)
    if len(cases) == 1:
        entries = list(before)
        for step in steps:
            entries.extend(step["entries"])
        check_resultant(entries, femmesh, synthetic_nodes, origin,
                        targets[cases[0]], path, "")
        return
    if len(steps) != len(cases):
        raise RuntimeError("%s: %d *STEP blocks for %d load cases — the "
                           "result mapping is undefined"
                           % (path, len(steps), len(cases)))
    if before:
        raise RuntimeError("%s: %d *CLOAD entries written outside any *STEP "
                           "apply to all %d steps — case %s would be "
                           "superposed on the rest"
                           % (path, len(before), len(cases), cases[0]))
    for index, (step, name) in enumerate(zip(steps, cases), start=1):
        scope = "case %s " % name
        if not step["entries"]:
            raise RuntimeError("%s: step %d (%s) wrote no *CLOAD at all, so it "
                               "would solve the previous case's load"
                               % (path, index, name))
        # Only a step that could inherit needs OP=NEW; the writer's own rule is
        # step_count > 1, so a one-case deck legitimately carries none.
        if index > 1 and not step["op_new"]:
            raise RuntimeError("%s: step %d (%s) wrote *CLOAD without OP=NEW, "
                               "so it keeps the previous step's loads on every "
                               "node it did not repeat"
                               % (path, index, name))
        check_resultant(step["entries"], femmesh, synthetic_nodes, origin,
                        targets[name], path, scope)


def check_resultant(entries, femmesh, synthetic_nodes, origin, target, path,
                    label):
    """Compare the resultant of some ``*CLOAD`` entries against one load case."""
    if not entries:
        raise RuntimeError("%s: no *CLOAD written — the load never reached "
                           "the solver input" % path)
    positions = cload_positions(entries, femmesh, synthetic_nodes, path)
    force_sum, moment_sum = resultant(entries, positions, origin)

    targets_f = (target["Fx"], target["Fy"], target["Fz"])
    targets_m = (target["Mx"], target["My"], target["Mz"])
    errors = []
    for index, name in ((0, "Fx"), (1, "Fy"), (2, "Fz")):
        error = abs(force_sum[index] - targets_f[index])
        if error > max(0.01 * abs(targets_f[index]), 1e-4):
            errors.append("%s: wrote %g, target %g"
                          % (name, force_sum[index], targets_f[index]))
    for index, name in ((0, "Mx"), (1, "My"), (2, "Mz")):
        got = (moment_sum.x, moment_sum.y, moment_sum.z)[index]
        error = abs(got - targets_m[index])
        if error > max(0.01 * abs(targets_m[index]), 1e-3):
            errors.append("%s: wrote %g, target %g"
                          % (name, got, targets_m[index]))
    if errors:
        raise RuntimeError("%s: %sapplied load resultant mismatch\n  %s"
                           % (path, label, "\n  ".join(errors)))


def cload_positions(entries, femmesh, synthetic_nodes, path):
    """Position of every node a ``*CLOAD`` entry names: the mesh first, then
    the synthetic reference node the writer appends for the coupling."""
    positions = {}
    mesh_nodes = femmesh.Nodes
    for node_id, dof, _value in entries:
        if dof > 3:
            raise RuntimeError("%s: unexpected rotational CLOAD dof %d "
                               "(writer promised forces + couples)"
                               % (path, dof))
        if node_id in positions:
            continue
        if node_id in mesh_nodes:
            point = mesh_nodes[node_id]
            positions[node_id] = (point if hasattr(point, "x")
                                  else FreeCAD.Vector(point[0], point[1], point[2]))
        elif node_id in synthetic_nodes:
            positions[node_id] = synthetic_nodes[node_id]
        else:
            raise RuntimeError("%s: CLOAD node %d not found in the mesh "
                               "or the inp *NODE additions" % (path, node_id))
    return positions


def resultant(entries, positions, origin):
    """Net force per DOF and net moment about ``origin`` of some load entries."""
    force_sum = [0.0, 0.0, 0.0]
    moment_sum = FreeCAD.Vector(0.0, 0.0, 0.0)
    for node_id, dof, value in entries:
        force_sum[dof - 1] += value
        load = FreeCAD.Vector(0.0, 0.0, 0.0)
        load[dof - 1] = value
        moment_sum = moment_sum + (positions[node_id] - origin).cross(load)
    return force_sum, moment_sum


def append_to_elsets(path, assignments):
    """Append each element id into its target elset's id block."""
    pending = {}
    for element_id, _, target in assignments:
        pending.setdefault(target, []).append(element_id)
    with open(path) as handle:
        lines = handle.readlines()
    out = []
    open_elset = None
    last_id_index = {}
    for raw in lines:
        line = raw.strip()
        if line.startswith("*"):
            open_elset = None
            if line.upper().startswith("*ELSET"):
                for part in line.split(","):
                    part = part.strip()
                    if part.upper().startswith("ELSET="):
                        open_elset = part.split("=", 1)[1].strip()
            out.append(raw)
            continue
        if open_elset in pending and line.strip(", ").replace(",", "").strip().isdigit():
            last_id_index[open_elset] = len(out)  # insert after this line
        out.append(raw)
    for elset, element_ids in pending.items():
        at = last_id_index.get(elset)
        if at is None:
            raise RuntimeError("elset %s has no id lines" % elset)
        for offset, element_id in enumerate(sorted(element_ids), start=1):
            out.insert(at + offset, "%d,\n" % element_id)
    with open(path, "w") as handle:
        handle.writelines(out)

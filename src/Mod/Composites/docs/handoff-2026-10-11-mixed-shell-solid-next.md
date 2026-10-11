# Handover — mixed shell+solid (multimesh), next session (2026-10-11)

> **Track A is closed.** The LS8e donation's last step (A2) landed — FreeCAD
> `c396c90ea8`, study `5692de7` — and both its gates were re-run clean
> (`propeller/test` 130 passed / 0 failed; lc03 disp 22.399093 mm, exposure
> 0.822963, λ₁ 0.7170082, mass 16288.826 g).  Track B is now the **only open
> track**, and it is the subject of this handover.

**Scope:** the mixed shell+solid FEM work in this workbench and in Fem.  No
LS8e study behaviour belongs here.

**Branch:** `/home/jmw/opt/FreeCAD` on **`fem-mixmesh`** (off `fem-unified`;
local and on origin; unmerged and unreviewed — its fate is the open item
`B9.3`).  Only `src/Mod/Composites` and `src/Mod/Fem` may be edited
(workbench policy).

**The single list, do not keep a second one:** every open item is in
`TODO-2026-10-11-outstanding-work.md` in this directory, with its blocker and
its exit.  The reasoning lives in `plan-mixed-shell-solid-fem.md` and
`docs/adr/0004-shell-solid-coupling-and-interface-dimension.md`; read those
rather than re-deriving anything below.

## Contents

1. [What is already done — do not re-open](#1-what-is-already-done--do-not-reopen)
2. [What is next, in order](#2-what-is-next-in-order)
3. [B6 — the E (edge-interface) family](#3-b6--the-e-edge-interface-family)
4. [B4.1 — `_shell_slave_face` picks the wrong side](#4-b41--_shell_slave_face-picks-the-wrong-side)
5. [Then — fixtures, a rebuild, and a proposal](#5-then--fixtures-a-rebuild-and-a-proposal)
6. [Deferred to the bottom by the owner](#6-deferred-to-the-bottom-by-the-owner)
7. [How to run and gate it](#7-how-to-run-and-gate-it)
8. [Standing rules](#8-standing-rules)

## 1. What is already done — do not re-open

- Mixed-plan **Stages 1–9**: the mixed path is on by default; the motivating
  laminate wing solves; plan §11.1, §11.2, §11.5, §11.6, §11.7, §11.12, §11.13
  are closed.
- **B9.1 / B9.1b / B9.4** — the compound-of-solids use-after-free, the stale
  edge-read cache, and the refusal of a support whose bodies do not touch
  (nextdrape `274341e` / `964dfcf` / `e708584`; FreeCAD `bf5129fc5b` /
  `6d9f0dc10d`).
- **B5.2** (the mixed suite solves one deck for real) and **B5.3** (`"Mesh
  generation failed"` is no longer treated as "the FEM stack is missing").
- **B2.2** — §8's admission rule names the risk (the deck must not depend on
  which entry point built the analysis), since `TestFemGui` is out of
  `__unit_test__`.
- **A1 / A2** — the whole LS8e donation tail, including the A2 helpers and the
  study CLI (`composites` commit `c396c90ea8`).

## 2. What is next, in order

The tracker's ordering, minus the closed items:

1. ~~**B6** (the E family) and **B4.1**~~ — the two real defects reachable
   without a rebuild; **both done 2026-10-11**.
2. **B3, B2.1, B5.1, B8** — the ones that need a fixture.
3. **B1** — the C++ view-provider change, last because it needs a rebuild.
4. **B7** — the proposal, now that B4.1 has landed; review before any code.

One-line reminders: **B3** is a write-time check for a tie whose shell slave
carries a `*CLOAD` node (its fixture must be Dhondt's two-shell-layer
arrangement — the mixed face families f1–f4 do not expose it, load/no-load
`.nam` files are byte-identical).  **B2.1** needs a mixed stiffener/bulkhead
case.  **B5.1** decides whether the offset and bag families get a
compared-pair displacement check, or the reason one cannot exist.  **B8** is a
per-skin laminate offset routed into `ShellThickness.Offset`; the **sign is
load-bearing**.  **B1** is `ViewProviderFemMesh.VisibleElementFaces` (a
read-only computed getter with no dimension filter).  Details in the tracker.

## 3. B6 — the E (edge-interface) family

> **DONE 2026-10-11 — see the tracker's B6.**  `e1`–`e3` write and solve.  The
> "what is missing" below was wrong on the code: the OCC edge → `S(3 + index)`
> mapping already existed in the edge masks, and the resolution was searching
> the wrong element table.  The text is retained as the original reasoning.

`e1`–`e3` are **refused loudly, not solved**.  ADR 0004 puts the family **in
scope** and selects the same mechanism as the face families (`*TIE`; a shell's
edge face S3–S6 against a solid face).  The blocker is FreeCAD's
reference→surface mapping: `meshsetsgetter.get_constraints_tie_faces` supplies
faces only.

**The path, traced 2026-10-11 — start from the code, not from this summary:**

- `get_constraints_tie_faces` (`meshsetsgetter.py:910`) calls `_get_elements`
  per reference and stores `(refs, surf, is_sub_el)` triples.
- `write_constraint_tie.py:81–100` writes `elem,S{fno}` when `is_sub_el` is
  true (a solid's face, resolved per element) and `elem,S{shell_side}` when it
  is false (a shell face, one side for every element).
- An **edge** reference reaches `_get_elements`, is resolved through the face
  table regardless, and yields a face index that came from an edge mask — which
  is why `checksanalysis._tie_references_that_are_not_faces` refuses it
  (`get_shape_dimension(...) != 2`).
- **What is missing:** the mapping OCC edge → element edge index →
  `S(3 + index)` per element along that edge.  CalculiX expands a shell into a
  solid whose faces 3–6 are its side faces — exactly the surface an E-shaped
  joint needs.  Its home is beside the existing shape lookups in
  `femtools/mixedcoupling.py` (§11.13 moved them there), so the getter and the
  writer share one definition.

*First-choice fix:* let an Edge selection on a shell yield its edge face;
`*EQUATION` stays the fallback.  *Exit:* `e1`–`e3` write and solve, and the
loud refusal narrows to a reference with no expressible surface.

## 4. B4.1 — `_shell_slave_face` picks the wrong side

> **DONE 2026-10-11 — see the tracker's B4.1.**  The tie names the expanded
> face nearest the master, from the slave's own section; `checksanalysis`
> refuses a tolerance below that distance.  The text below is the original
> reasoning.

`src/Mod/Fem/femsolver/calculix/write_constraint_tie.py:60–77` takes `S1`/`S2`
from the **first** non-suppressed `geos_shellthickness` offset in the analysis
and never consults the master.  With a sandwich's two opposite offsets one tie
names the **far** face — a whole thickness out, silent.  It is unexposed today
only because every fixture and example uses offset 0.

**Order if picked up:**

1. choose the slave face from the master's side;
2. derive the required tolerance in `checksanalysis` from geometry and **warn**
   when `tolerance < required`, naming faces, both numbers and the remedy;
3. only then set an offset in a fixture.

**Traced 2026-10-11:** the function takes only `ccxwriter`, so it cannot see
which shell the tie's slave is — even though its caller
`write_meshdata_constraint(f, femobj, tie_obj, ccxwriter)`
(`write_constraint_tie.py:79`) holds the tie's resolved faces and the tie
object.  Choosing by the master needs the **signed distance** from the slave
shell's reference surface to the master plane along the shell normal — §11.11's
`o`/`g` table — a geometry query the writer does not make today.  Today's rule
(`1 if Offset < 0 else 2`) is correct only for a master sitting **on** the
reference surface (`g = 0`).

**Not scheduled:** making the offset land an expansion node on the contact
plane (`o = g/t − 0.5`).  The requirement is **per tie pair, not per shell**, it
moves material through the thickness, and it can at most be *reported*.

## 5. Then — fixtures, a rebuild, and a proposal

- ~~**B3** `*CLOAD`-on-a-tie-slave hazard~~ — **done 2026-10-11** (write-time
  check, scoped to shell-to-shell ties; fixture `test_constraint_tie_shell.py`);
  ~~**B2.1** stiffener/bulkhead mixed coverage~~ — **done 2026-10-11** (a mixed
  bulkhead in a hollow hull, tied round its perimeter).  ~~**B5.1** compared-pair coverage~~ — **done 2026-10-11** (decided
  and recorded: no compared pair for the stand-off families, plus a
  non-zero-displacement assertion for all four).  ~~**B8** per-skin laminate
  offset~~ — **done 2026-10-11** (the feature had already landed; the
  stiffness check that pins the sign was added).
- **B1** the results-viewer dimension toggle (C++ + rebuild).
- **B9.2** delete `femsolver/settings.py::get_allow_mixed_elements` and its
  call sites **after one release has shipped** with the default on.
- **B9.3** decide the branch's fate (keep it the explicit working record, or
  open the PR).
- **B7** assign ties from the references the model already carries — a
  **proposal: review before any code**; it depended on B4.1 (per-shell slave
  lookup), now satisfied, and adds **B7.1**, an optional `SupportReference`
  (`App::PropertyLinkSubGlobal`) on `Composite::Shell` so a single-face skin can
  declare `(solid, faces)` — **landed 2026-10-11**.  The rule is **object
  identity** (`shell.Support`/`SupportReference` object), not a geometric
  pairing, so the wing and the plate keep their hand-written ties.  Six open
  questions for review, **no code for B7 itself yet**.

## 6. Deferred to the bottom by the owner

**B9.5 — the drape suite's two acceptance canaries are RED** (197 passed / 2
failed): `CoverageGeometry.BentPlateDiagnosticsPopulate` (`gapFraction` 0.5)
and `TexturePlan.BoundaryLinksLieOnTheDevelopedTrim` (cyl-closed 23, cubic 2,
web_band 52).  Both reproduce unchanged on pristine `aba05cc` — pre-existing,
not caused by the B9.1 work — and both are the documented
`BOUNDARY-LINK-BORN-OFF-EDGE` birth-law defect (rim cells refused and never
healed).  **The fix is the birth law — never the assertions and never the
thresholds.**  First step: the reject gate is named by the diagnostic
`LastRejectGate()`, already surfaced.  Deferred, not accepted.

## 7. How to run and gate it

Everything goes through the `freecad-dev` skill's scripts — never raw binaries:

- sync after **any** source edit: `~/.pi/agent/skills/freecad-dev/scripts/build-install-freecad.sh`
- Composites tests: `~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh <module>` (e.g. `test_drape_laminate_provider`, `test_mixed_coupling_numerical`)
- Fem app tests (pytest): `~/.pi/agent/skills/freecad-dev/scripts/run-fem-tests.sh <file.py>`

A change to `write_step_output.py` (as `EigenmodeElementOutput` was) ships in
the same full-suite gate as the mixed work.  Run only the modules the change
touches; do not run the whole suite "to see".

## 8. Standing rules

- **Never** relax a test threshold, widen a tolerance, or delete a test without
  asking the user first.  A failing test is a defect — fix the code or the
  algorithm, not the bar.
- **No retry-until-success.**  Nondeterminism is a bug to diagnose (an
  unordered iteration, a boolean short-circuit, a stale cache), never something
  to re-run past.
- **No environment variables** for run-time options; options are arguments.
- **Imports at the top** of the module, never inline.
- **Stay focused.**  A defect found off-task becomes a TODO, not a detour.
- Commit style: a lowercase declarative subject plus the reason.

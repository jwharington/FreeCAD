# Handover — mixed shell+solid (multimesh)

> **Updated 2026-10-11, end of the Track B session that took the tracker's
> fixtures list.**  Track A is closed (LS8e A2: FreeCAD `c396c90ea8`, study
> `5692de7`; `propeller/test` 130 passed, lc03 disp 22.399093 mm).  Since the
> first handover, **B6, B4.1, B8, B5.1, B7.1, B7, B3 and B2.1 all landed**, so this
> document now describes what is *left*, not what was next then.  The old
> per-item reasoning for B6/B4.1 is in the git history and in
> `plan-mixed-shell-solid-fem.md`; it is not repeated here.

**Scope:** the mixed shell+solid FEM work in this workbench and in Fem.  No
LS8e study behaviour belongs here.

**Branch:** `/home/jmw/opt/FreeCAD` on **`fem-mixmesh`** (off `fem-unified`;
local and on origin; unmerged and unreviewed — its fate is `B9.3`).  Only
`src/Mod/Composites` and `src/Mod/Fem` may be edited (workbench policy).

**The single list, do not keep a second one:** every open item is in
`TODO-2026-10-11-outstanding-work.md` in this directory, with its blocker and
its exit.  The reasoning lives in `plan-mixed-shell-solid-fem.md` and
`docs/adr/0004-shell-solid-coupling-and-interface-dimension.md`.

## Contents

1. [What is already done — do not re-open](#1-what-is-already-done--do-not-reopen)
2. [What is left, in order](#2-what-is-left-in-order)
3. [B1 — the results-viewer toggle (the one rebuild item)](#3-b1--the-results-viewer-toggle-the-one-rebuild-item)
4. [B7 — the tie-assignment pass (implemented)](#4-b7--the-tie-assignment-pass-implemented)
5. [B9.6 — a pre-existing RED test module](#5-b96--a-pre-existing-red-test-module)
6. [Deferred to the bottom by the owner](#6-deferred-to-the-bottom-by-the-owner)
7. [How to run and gate it](#7-how-to-run-and-gate-it)
8. [Standing rules](#8-standing-rules)

## 1. What is already done — do not re-open

Earlier work:

- Mixed-plan **Stages 1–9**: the mixed path is on by default; the motivating
  laminate wing solves; plan §11.1, §11.2, §11.5, §11.6, §11.7, §11.12, §11.13
  are closed.
- **B9.1 / B9.1b / B9.4** — the compound-of-solids use-after-free, the stale
  edge-read cache, and the refusal of a support whose bodies do not touch
  (nextdrape `274341e` / `964dfcf` / `e708584`; FreeCAD `bf5129fc5b` /
  `6d9f0dc10d`).
- **B5.2 / B5.3 / B2.2**, and **A1 / A2** (the whole LS8e donation tail).

This session (2026-10-11), each with its own tracker note:

- **B6 — the E (edge-interface) family.**  `e1`–`e3` write and solve.  The
  handover's "what is missing" was wrong on the code: the OCC edge →
  `S(3 + index)` mapping already existed in the edge masks
  (`calculixutils.define_masks`, `offset = 2` in 3D), and
  `get_subelements_by_references` was searching the wrong element table —
  `get_femelement_table` holds only the highest dimension, i.e. volumes in a
  mixed mesh.  `meshtools.get_elements_by_reference_dimension` now resolves a
  shell Edge against the dimension-2 table; the guard accepts it; the same
  table-selection bug in the **line-load** path was fixed too (a `*CLOAD` on a
  shell edge had been written empty).  Fix in `femmesh/meshtools.py`,
  `femmesh/meshsetsgetter.py`, `femtools/checksanalysis.py`.
- **B4.1 — `_shell_slave_face` picked the wrong side.**  The tie now names the
  expanded face **nearest the master**, from the **slave's own** section
  (`femutils.member_for_reference`), and `checksanalysis` **refuses** a
  tolerance below that distance.  Shared geometry in
  `femtools/mixedcoupling.py` (`shell_expansion_faces`,
  `tie_slave_side_and_tolerance`, `planar_face`).
- **B8 — per-skin laminate offset.**  The feature had already landed
  (`0542b6ba22`); the stale tracker note was rewritten, and the **exit** was
  added: the cantilever probe grows a mid-surface variant, and
  `test_the_section_offset_stiffens_the_skin` asserts the offsetted model is
  stiffer.  Measured: offsetted **6.422333e-02 mm**, mid-surface
  **9.179597e-02 mm** (1.43x), all-solid **6.416312e-02 mm** (0.09 %).
- **B5.1 — compared-pair coverage.**  Decided and recorded: no compared pair
  for the stand-off families (F3/F4), because any all-solid rebuild would hang
  on the comparison's own tie; instead every face family now asserts a
  **non-zero displacement** as well as `not_coupled == 0`.
- **B7.1 — `SupportReference` on `Composite::Shell`.**  An optional
  `App::PropertyLinkSubGlobal` holding `(solid, ["FaceN", ...])` so a skin can
  declare its interface on a solid's own object; `Support` untouched.  Three
  resolvers (`support_object`, `support_shape`, `support_placement`) in
  `CompositeShell.py`; `TexturePlan` uses them.  `getSubObject(list)` returns a
  **list** of shapes — the resolver unwraps it.
- **B7 — the tie-assignment pass.**  `Composites.fem.auto_tie.auto_tie`
  creates the ties a model declares (solid/`SupportReference` identity, derived
  tolerance, `AutoCouple` opt-out, empty pass returns `[]`).  New example
  `mixed_shell_solid_auto_tie` is the exit model; the wing and the plate keep
  their hand-written ties.  Two findings (the slave is the *shell*; the
  tolerance comes from the laminate total, not the section placeholder) and the
  follow-up are in §4 below.
- **B3 — the `*CLOAD`-on-a-tie-slave hazard.**  Reproduced in Dhondt's
  two-shell-layer fixture (`femtest/app/test_constraint_tie_shell.py`), then
  refused: `write_constraint_tie.write_meshdata_constraint` reports a tie whose
  two surfaces are **both shell faces** and whose slave carries a `*CLOAD`,
  naming the nodes and the remedy.  Scoped to shell-to-shell because the
  shell-to-solid f-family was measured **not** to collide.
- **B2.1 — a composite stiffener on a solid.**  New example
  `mixed_shell_solid_stiffener` (registered): a QI panel `Composite::Shell` on
  a solid spar + a real `StiffenerFP` on it + a `*TIE`; its web/foot shells get
  their own sections.  Verified by `test_mixed_shell_solid_stiffener.py`.  A
  plain-geometry mixed **bulkhead** (a plate in a hollow hull, four perimeter
  edge ties) is a second regression in `test_mixed_shell_solid.py`.

## 2. What is left, in order

The tracker's ordering, minus the closed items:

1. **B1** — the C++ view-provider change; the only item with a **rebuild**.
2. **B7's follow-up** — `checksanalysis._tie_tolerance_message` and
   `_shell_slave_face` still read the placeholder section thickness for a
   composite shell, so B4.1's refusal under-estimates the requirement for
   laminates (plan §12.1).
3. **B9.2** delete `femsolver/settings.py::get_allow_mixed_elements` and its
   call sites **after one release has shipped** with the default on.
4. **B9.3** decide the branch's fate (keep it the explicit working record, or
   open the PR).
5. **B9.6** — a pre-existing RED test module, found this session (below).
6. **B9.5** — deferred to the bottom by the owner (below).

## 3. B1 — the results-viewer toggle (the one rebuild item)

A mixed result displays, but the skin and the solid cannot be told apart: a skin
coincident with a solid face z-fights, and
`ViewProviderFemMesh.VisibleElementFaces` (`src/Mod/Fem/Gui/ViewProviderFemMeshPyImp.cpp`)
is a **read-only computed getter** with no dimension filter; `ColorMode` /
`ShowInner` / `MaxFacesShowInner` do not separate shells from solids.  *Exit:* a
toggle that hides one dimension, with the mixed wing and plate still
displaying.  It is the only item that needs a C++ build.

## 4. B7 — the tie-assignment pass (implemented)

**DONE 2026-10-11.**  `Composites.fem.auto_tie.auto_tie(analysis)` creates the
ties a model declares: it collects the bonded solids from the dimension-3
material references, collects the `Composite::Shell` objects whose
`SupportReference[0]` is one of them, and ties `(shell, "Face1")` to
`(solid, "FaceN")` with a derived tolerance.  Pairing is **object identity**;
the writer and `meshsetsgetter` are untouched.  Decisions: a headless helper
only (no command), a per-shell `AutoCouple` opt-out, the new
`mixed_shell_solid_auto_tie` example as the exit model, and an empty pass
returning `[]`.  The wing and the plate keep their hand-written ties.

Two findings, both load-bearing — full text in plan §12.1:

- the exported **slave** must name the *shell*, not the solid: a face whose
  object is a solid resolves to a volume sub-element and would reproduce the
  master surface;
- the tolerance must come from the **laminate's total thickness**, not the FEM
  section's placeholder `Thickness` (1.6 mm against 0.8 mm), and must *exceed*
  the face's distance because CalculiX's gate is strict.

**Follow-up (open):** `checksanalysis._tie_tolerance_message` and
`_shell_slave_face` still read the placeholder for a composite shell, so B4.1's
refusal under-estimates the requirement for laminates.  One face per shell in
this cut.

## 5. B9.6 — a pre-existing RED test module

`test_composite_shell` has **3 errors** in `TestCompositeShellOffset`, all in
`write_femelement_geometry.py:198`, which reads `ccxwriter.mesh_object.FemMesh`
for a composite section while the test's `_StubCcxWriter` never had a
`mesh_object`.  The guard landed in `a601dde52a` (2026-10-10), a day *after*
those tests (`0542b6ba22`), so it is **not** from this session's work.
*Exit:* either the stub grows a `mesh_object` + a real `ccx_elset`, or the guard
stops reading the writer when `elements` is not a set name — which side is wrong
is the open question.  The new B7.1 tests in the same module pass alongside it.

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
- Composites tests: `~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh <module>` (e.g. `test_mixed_coupling_numerical`, `test_composite_shell`, `test_mixed_shell_solid_stiffener`)
- Fem app tests (pytest): `~/.pi/agent/skills/freecad-dev/scripts/run-fem-tests.sh <file.py>` (e.g. `test_mixed_shell_solid.py`, `test_constraint_tie_shell.py`)
- run a committed example/CLI headlessly: `~/.pi/agent/skills/freecad-dev/scripts/run-script.sh <script.py> [args]`

**Run only the modules the change touches — and never the whole `femtest`
tree.**  A full-tree run on a 3000 s timeout OOM'd this machine and forced a
reboot; the tree is 32 modules and the session's changes were gated with
targeted one-module runs throughout.  State the modules and why before running.

The gates used this session, all green: `test_mixed_shell_solid.py` (Fem, 44),
`test_constraint_tie_shell.py` (Fem, 2), `test_mixed_coupling_numerical.py`
(Composites, 7), `test_mixed_shell_solid_stiffener.py` (Composites, 1).

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
- **"Done" means verified.**  Two of this session's tracker notes turned out to
  be stale about the code (B6's "missing mapping" already existed; B8 was
  implemented but unverified); read the code before trusting a note.
- Commit style: a lowercase declarative subject plus the reason.

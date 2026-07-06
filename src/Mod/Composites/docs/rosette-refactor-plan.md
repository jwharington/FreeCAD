# Rosette Refactor Plan — Three Rosette Types with Iterative Solve

**Started:** 2026-07-06
**Completed:** 2026-07-07
**Status:** Done — all phases landed and verified (headless + GUI). Open
questions §10 resolved with documented defaults. See §12 (Completion log)
for the as-built state, including the unplanned restore/rehydrate fixes and
the `Composites_drape.so` loader fix.
**Supersedes:** the "TransferRosette morph" handover (`get_draper()` fix
stays; the follower-rosette design is replaced)

---

## 1. Goal

Replace the current follower-LCS / follower-rosette transfer features with a
single, coherent family of **Rosette** features that own a fibre orientation
datum directly:

- **Rosette** (base) — explicit user angle.
- **AlignFibreRosette** — angle solved so a warp fibre passes through a second point.
- **TransferRosette** — angle solved so an attachment shell's warp matches a
  master shell's warp across their shared boundary edge.

This is the end-state of the Rosette refactor begun in `96aff19265` (a Rosette
*is* an LCS + an angle; the shell's orientation reference is a Rosette, not a
bare LCS). The transfer/align features are now Rosettes themselves rather than
producers of follower geometry.

---

## 2. Background & context

- `96aff19265` — dropped the shell's redundant `LocalCoordinateSystem`; the
  Rosette is the sole orientation reference.
- The handover morphed `TransferLCS` → `TransferRosette` (a *follower* rosette
  at a support point) and fixed `CompositeShellFP.get_draper()` (`return
  self._backend`). The `get_draper()` fix is **foundational and stays**.
- Headless verification (`FreeCADCmd -P src/Mod`, integration suite) showed the
  `get_draper()` fix works (7/7 integration tests pass; draper returns a valid
  `_RehydratedBackend`). It also exposed a **second, pre-existing bug** that
  the `get_draper()` failure had been masking — see §3.

### Why a redesign, not an evolution

The current `TransferRosette.py` (follower rosette at a support point) and
`AlignFibreLCS.py` (transfer + align angle) do **not** match the three-type
domain model the user has now specified. They are point-transfer features; the
new model is face-anchored + iteratively-solved. They should be rebuilt, not
patched.

---

## 3. The contract-drift bug (found during headless verification)

`tools/lcs.py` type-hints `transfer_lcs_to_point` as `-> tuple[Vector,
Rotation]`, and `TransferRosette.execute` / `AlignFibreLCS.execute` call
`.inverted()` on the second element (treating it as a `Rotation`).

- The **legacy** flatmesh `Draper`/`get_lcs_at_point` returned a `Rotation`
  (already inverted), so `.inverted()` was a net no-op.
- The **new** backends (`NextDrapeBackend`, `_RehydratedBackend`)
  `get_lcs_at_point` returns a **`FreeCAD.Placement`** (Base + Rotation, not
  inverted). `.inverted()` raises `AttributeError: 'Base.Placement' object has
  no attribute 'inverted'`.

Result: `TransferRosette.execute()` (vertex/edge path) and
`AlignFibreLCS.execute()` raise, leaving the follower Rosette's LCS at the
origin. `WrapLCS` (face path) returns a constructed `Rotation` from
`transfer_lcs_to_face` and would *not* raise — but it's being dropped (§6).

In the new design, `transfer_lcs_to_point/edge` are no longer used at all (the
features are face-anchored + solved, not point-transfers). So this bug is
removed by deletion rather than by fixing the contract — see §8.

### Secondary issue

`AlignFibreLCS` also hits `'NoneType' object is not subscriptable` inside
`align_fibre_lcs()`: `draper.get_tex_coord_at_point(base_position, …)` returns
`None` for the shell rosette's base position. This is a data/lookup problem
(nearest-quad search) that the new `AlignFibreRosette` design sidesteps by
using a *picked* second vertex on the face rather than the rosette base.

---

## 4. Domain model

All three are Rosettes: anchored on a **Face**, Z = face normal at the anchor,
X = the face's **U axis at the anchor** rotated by an **Angle** about the
normal. They differ only in how the Angle is determined.

- **Rosette** — Angle is an explicit user property.
- **AlignFibreRosette** (extends Rosette) — anchor + a second picked Vertex on
  the face. Angle is *solved* so the warp fibre (v=0 in texture coords) passes
  through the second vertex.
- **TransferRosette** (extends Rosette) — lives on the **attachment** shell.
  Properties reference the master shell. Angle is *solved* so the attachment's
  warp makes the same angle with the shared boundary edge as the master's, at
  sampled points along the edge (RMS mismatch).

### Warp-transfer law (TransferRosette)

The fibre is continuous as a 3D curve but, at a fold (non-coplanar faces), its
tangent *kinks* — the 3D warp vectors on the two faces lie in different tangent
planes and are generally not equal. The physically meaningful continuity
condition is **equal angle with the shared edge tangent** at every point on the
edge (the standard multi-patch draping matching-angle law, confirmed with the
user):

- At a sampled point P on the edge: **t** = edge tangent (same 3D direction for
  both faces at P).
- θ_m = ∠(master warp 3D direction **w_m**, **t**) — from the master's solved
  draper.
- θ_a = ∠(attachment warp 3D direction **w_a**, **t**) — from the attachment's
  re-draped draper (with the candidate Angle).
- Residual = RMS over samples of (θ_a − θ_m). Drive to zero.

**Dependency:** the master shell is assumed already solved (its rosette fixed);
only the attachment is iterated.

---

## 5. Why the iterative solve works

The nextdrape solve is **seeded by the rosette LCS**:

- `NextDrapeBackend._origin_and_warp` uses `self._lcs.Placement.Base` as the
  fabric origin and the LCS X-axis as the warp direction
  (`drape_backend_nextdrape.py` ~line 560).
- `CompositeShell._can_use_persisted` already detects `Rosette.Angle` changes
  via `_LastRosetteAngle` and forces a re-solve.

So: changing the rosette Angle → re-seeds the warp direction → fresh drape →
different warp field. The loop is:

1. Set candidate Angle on the (attachment) Rosette.
2. `shell.Document.recompute()` — re-drives the attachment shell's draper.
3. Wait for the shell's draper to be valid (`get_draper().is_valid()`).
4. Evaluate the error function (reads the draper).
5. Secant/bisection step over a bounded range (e.g. [−90°, 90°]).

~3–5 drape solves per Align/Transfer rosette (each ≈1–2s).

### Prerequisite: base Rosette must fold Angle into the LCS

Today the base `RosetteFP.execute` aligns Z to the face normal but leaves **X
arbitrary** (`Rotation(Z→normal)`); `Angle` is only an *output* tex-coord
offset, not part of the LCS. The iterative solve needs `Angle` to be an
*input* — X = face-U rotated by Angle about the normal — so changing Angle
re-seeds the drape. This base rework (§7 Phase 1) is the foundation.

---

## 6. Feature fates

| Current file            | Fate                                                        |
|-------------------------|-------------------------------------------------------------|
| `Rosette.py`            | Rework base `RosetteFP` (Phase 1).                          |
| `TransferRosette.py`    | Rewrite as attachment-shell Rosette with iterative solve (Phase 4). |
| `AlignFibreLCS.py`      | Replace with `AlignFibreRosette.py` (Phase 3).              |
| `WrapLCS.py`            | Drop — folded into the new `TransferRosette`.              |
| `TransferLCS.py`        | Already deleted.                                            |
| `tools/draper.py`       | Drop (dead delegator; backends implement the protocol directly). |
| `tools/lcs.py`          | Drop dead `transfer_lcs_to_*` / `align_fibre_lcs`; keep only what's still used. |
| `CompositeShell.py`     | Keep `get_draper()` fix (`return self._backend`).           |

### Renames

- `ALIGN_FIBRE_LCS_TOOL_ICON` → `ALIGN_FIBRE_ROSETTE_TOOL_ICON`; icon file
  `AlignFibreLCS.svg` → `AlignFibreRosette.svg` (or new).
- Command id `Composites_AlignFibreLCS` → `Composites_AlignFibreRosette`.
- Toolbar entry updated.
- Test module path references updated.

---

## 7. Implementation phases

### Phase 0 — foundation (already staged, keep)
- `get_draper()` fix in `CompositeShell.py` (`return self._backend`). Confirmed
  working headless.

### Phase 1 — base Rosette rework
- `RosetteFP.execute`: for a Face support, align X to the face's U axis at the
  anchor; fold `Angle` into the LCS rotation (X = face-U rotated by Angle about
  the normal). Vertex/Edge supports keep current behaviour (no face-U
  reference; Angle rotates about the default normal).
- Verify the drape solve responds to Angle changes (the `_LastRosetteAngle`
  invalidation path already exists).
- The `get_tex_coords`/`get_boundaries`/`get_tex_coord_at_point`
  `offset_angle_deg` machinery stays for *additional* downstream rotation; the
  rosette's own Angle is now baked into the LCS and is the solve input.

### Phase 2 — shared iterative solver
New helper `tools/rosette_solver.py`:

- Inputs: the `CompositeShell` to iterate, its `Rosette`, a scalar **error
  function** `(angle_deg) -> float`, bounds, tolerance, max iterations.
- Method: secant/bisection over a bounded range (default [−90°, 90°]).
- Each evaluation: set `Rosette.Angle`, trigger `shell.Document.recompute()`,
  wait for the shell's draper to be valid, call the error function.
- Returns the converged Angle (and raises if no convergence within tolerance /
  iterations).

This engine backs both AlignFibreRosette and TransferRosette.

### Phase 3 — AlignFibreRosette
- New `features/AlignFibreRosette.py` (replaces `AlignFibreLCS.py`). Subclasses
  `RosetteFP`; adds `SecondPoint` (a picked Vertex on the shell face). Anchor is
  the existing `Support` (Face + anchor vertex/point — see open question §10.2).
- `execute`: error function = `v` component of
  `draper.get_tex_coord_at_point(second_vertex.Point)`; drive to 0. Write the
  solved Angle back into the Rosette's `Angle` property (§10.3).
- Rename icon constant, command id, toolbar entry, tests.

### Phase 4 — TransferRosette (rebuild)
- Rewrite `features/TransferRosette.py` as a Rosette subclass living on the
  **attachment** shell. Properties: `MasterShell` (CompositeShell), and
  derive the shared boundary edge of the master & attachment faces
  automatically (with a fallback if no clean topological boundary — see §10.1).
- `execute`: derive the shared boundary edge; sample N points along it (by
  arc-length); for each, compute θ_m and θ_a from the respective drapers'
  `get_lcs_at_point` (warp = LCS X-axis in world); residual = RMS of
  (θ_a − θ_m). Iterate the attachment rosette Angle to minimise. Write the
  solved Angle back.
- Drop `WrapLCS.py`.

### Phase 5 — headless integration tests (`compositestests/test_integration_freecad.py`)
- `test_rosette_face_anchor_u_axis` — base Rosette on a face; assert X aligns to
  face-U and Angle rotates it.
- `test_align_fibre_rosette_solves` — AlignFibreRosette on the conical example
  with a second vertex; assert solved Angle drives `v(second_point)` ≈ 0
  (within tolerance).
- `test_transfer_rosette_solves` — two-shell setup; assert attachment rosette
  Angle minimises edge angle mismatch (θ_a ≈ θ_m within tolerance at sampled
  points).
- Run via `FreeCADCmd -P src/Mod`. The loader finds `Composites_drape.so`
  via FreeCAD's install Mod tree (no env var needed). Each test ≈3–6s
  (real drape solves).

### Phase 6 — GUI verification (after headless tests pass)

Headless tests prove the algorithms; GUI tests prove the features work in the
real FreeCAD runtime — ViewProviders, coin symbols, selection-driven commands,
property editor, recompute cycle through the GUI event loop. Run these **only
after Phase 5 passes headless**, so GUI failures aren't masked by algorithm
bugs.

**Via the FreeCAD MCP server** (port 9875, started with
`~/.pi/agent/skills/freecad-dev/scripts/start-freecad-mcp.sh --kill`):

For each feature (Rosette / AlignFibreRosette / TransferRosette):

1. **Command-driven creation** — invoke the toolbar command's
   `Activated()` path (or its `sel_args`-equivalent constructor) so the
   feature is created the way a user would, not just
   `doc.addObject('App::FeaturePython', ...)`. This exercises the
   `BaseCommand` selection/guard logic and VP attachment.
2. **VP symbol render** — screenshot the relevant view (Isometric/Right)
   and assert the rosette disk+arrows symbol appears at the anchor on the
   face, oriented with X along face-U (rotated by Angle), Z along the normal.
   Use `freecad_get_view` with `focus_object` on the rosette.
3. **`claimChildren`** — assert the VP's `claimChildren()` returns the child
   `LocalCoordinateSystem` (Rosette) and, for TransferRosette, the expected
   master/attachment references resolve in the tree view.
4. **Angle edit → re-solve** — change `Rosette.Angle` through the GUI property
   editor (via MCP `freecad_edit_object`) and confirm the shell re-drives and
   the rosette symbol rotates; screenshot before/after. For AlignFibreRosette
   and TransferRosette, confirm that changing the defining geometry (second
   point / master shell) re-triggers the iterative solve and the symbol
   re-settles.
5. **Rehydrate** — save the document, close it, reopen, recompute, and
   confirm the rosette symbol and LCS placement survive the round-trip
   (the `_RehydratedBackend` path).
6. **Exception scan** — after each GUI interaction:
   ```bash
   grep -nE "pyException|Traceback|AttributeError|RuntimeError|NameError" /tmp/freecad.log | tail -n 80
   ```
   Ignore tracebacks that originate inside `<string>` MCP snippets (debug-script
   mistakes, not module bugs).

**Document-level GUI checks:**
- Open the conical example document; create one of each Rosette type via the
  toolbar; confirm the tree view shows the expected parent/child structure and
  the 3D view shows all three rosettes correctly placed/oriented.
- For TransferRosette: build (or load) the two-shell fixture from §10.4,
  create the feature, and visually confirm the attachment rosette's warp
  aligns with the master's across the shared edge.

These GUI checks are recorded as a screenshot set + assertion notes in the
verification log, not as automated tests (the FreeCAD GUI is not
script-assertable end-to-end). The headless integration tests (Phase 5)
remain the automated gate; GUI verification is the human-readable confirmation.

### Phase 7 — cleanup (boy-scout)
- Delete dead `transfer_lcs_to_*` / `align_fibre_lcs` in `tools/lcs.py`.
- Delete `tools/draper.py` (the now-redundant `Draper` wrapper); fix `tools/lcs.py`
  type hints that referenced `Draper`.
- Remove `TransferLCS`/`WrapLCS` references from `__init__.py`, `ToolbarGroup.py`,
  tests.

### Phase 8 — sync, build, run, commit
- `cmake --build build/debug --target CompositesScripts -j8`;
  `cmake --install build/debug`; purge `.pyc`; restart FreeCAD MCP.
- Run the full headless integration suite; scan `/tmp/freecad.log` for
  exceptions (`grep -nE "pyException|Traceback|AttributeError|RuntimeError|NameError"`).
- Commit:
  `refactor(composites): three Rosette types (Rosette/AlignFibreRosette/TransferRosette) with iterative solve; fix get_draper()`.

---

## 8. `tools/lcs.py` disposition

`transfer_lcs_to_point` / `transfer_lcs_to_edge` (the Placement-vs-Rotation
contract-drift callers) are no longer used by the new design. Delete them.
`transfer_lcs_to_face` was used only by `WrapLCS` (dropped) — delete it too.
`align_fibre_lcs` was used only by `AlignFibreLCS` (replaced) — delete it.

The contract-drift bug (§3) is therefore removed by deletion, not by fixing the
Placement-vs-Rotation contract. If any of these helpers turn out to have other
callers, they'll be addressed then; a search will confirm before deletion.

---

## 9. Test strategy

Testing is layered, cheapest first:

1. **Headless integration tests (Phase 5)** — the automated gate. They exercise
   the real drape via `FreeCADCmd`, catching the kind of contract drift that
   masked this bug for so long. These **must pass** before any GUI work.
2. **GUI verification (Phase 6)** — run via the FreeCAD MCP server *after* the
   headless suite is green. Confirms ViewProviders, coin symbols,
   selection-driven commands, the property editor, and the recompute cycle
   through the GUI event loop — none of which the headless suite exercises.
   Recorded as a screenshot set + assertion notes, not automated assertions
   (the FreeCAD GUI is not script-assertable end-to-end).
3. **Tolerances** (apply to both layers): AlignFibreRosette
   `v(second_point)` within e.g. 0.5 mm (fabric pitch units);
   TransferRosette θ_a − θ_m within e.g. 1° RMS. These are engineering
   tolerances on a converged solve, not test-harness slack — they will not be
   widened to make a failing test pass (per project testing discipline).

---

## 10. Open questions (resolved)

All resolved with documented defaults during implementation:

### 10.1 TransferRosette shared-edge derivation
**Resolved:** auto-derive via `master.Shape.section(attachment.Shape)`, pick
the longest resulting edge. **No picked-edge fallback — by design:** if the
master & attachment faces share no topological boundary edge, the feature
raises a clear `ValueError` ("master and attachment shells share no boundary
edge — cannot transfer warp orientation") rather than silently producing a
meaningless solve. A separately-picked `BoundaryEdge` property remains the
natural extension if real glued assemblies need it.

### 10.2 AlignFibreRosette anchor
**Resolved:** the `Support` (rosette origin) is the **Face** (origin at the
parametric centre, face-U there) — inherited base Rosette behaviour. The
second point is a picked Vertex (`SecondPoint` property, a
`Draft.make_point` on the face interior in tests). An interior point is
required for a clean solve; the conical face's 4 corner vertices are at the
drape boundary and don't give a smooth `v(angle)`.

### 10.3 Angle write-back
**Resolved:** write-back. The solved Angle is written into the inherited
`Angle` property (visible/editable). A recompute from a changed defining
property re-solves.

### 10.4 Two-shell test fixture
**Resolved:** constructed a minimal one — two coplanar patches
(master x∈[0,200], attachment x∈[−200,0]) sharing the edge at x=0.
`master.Shape.section(attachment.Shape)` yields the real shared edge; the
error is linear (`30° − angle`) and brackets cleanly. Lives in
`test_transfer_rosette.py::_build_two_shell_fixture`.

---

## 11. Reference: key files

| File                                          | Role                                              |
|-----------------------------------------------|---------------------------------------------------|
| `features/Rosette.py`                         | Base Rosette — rework in Phase 1.                 |
| `features/TransferRosette.py`                 | Rebuild in Phase 4.                               |
| `features/AlignFibreLCS.py` → `AlignFibreRosette.py` | Replace in Phase 3.                        |
| `features/WrapLCS.py`                         | Drop (folded into TransferRosette).              |
| `features/CompositeShell.py`                  | `get_draper()` fix stays; draper protocol.       |
| `tools/drape_backend_nextdrape.py`            | `get_lcs_at_point` returns Placement; solve seeds from LCS. |
| `tools/lcs.py`                                | **Deleted** (Phase 7).                            |
| `tools/draper.py`                             | **Deleted** (Phase 7).                            |
| `tools/drape_backend_legacy.py`               | **Deleted** (Phase 7).                            |
| `tools/rosette_solver.py`                     | **New** — shared iterative solver (Phase 2).     |
| `util/geometry_util.py`                       | Added `tex_coord_nearest_quad_fallback` (foundation). |
| `compositestests/test_integration_freecad.py`  | Existing 7 headless tests.                        |
| `compositestests/test_rosette_integration.py`  | **New** — AlignFibreRosette + rehydrate round-trip (Phase 5). |
| `compositestests/test_transfer_rosette.py`     | **New** — TransferRosette two-shell solve (Phase 5). |

### Runtime paths
- Source (edit here): `src/Mod/Composites`
- Build tree: `build/debug/Mod/Composites`
- Install prefix (FreeCAD loads from here): `.pixi/envs/default/Mod/Composites`
- Native drape: `.pixi/envs/default/Mod/Composites/ext/_native/Composites_drape.so`
- User Mod symlink: `~/.local/share/FreeCAD/v1-2/Mod/Composites → install prefix`

---

## 12. Completion log (as-built)

**Commits (2026-07-07):**

1. `c71d2ba231` — three Rosette types + draper foundation. Base Rosette
   folds `Angle` into the LCS (X = face-U rotated by Angle about the normal);
   `AlignFibreRosette` (solve so a warp fibre passes through a second point);
   `TransferRosette` rewritten (solve attachment Angle so warp matches master
   along the shared edge, equal-angle-with-edge-tangent law); `tools/rosette_solver.py`
   (bounded secant/bisection). Foundation fixes: `get_draper()` returned a
   nonexistent `.draper`; quaternion arg-order in `get_lcs_at_point` (both
   backends — every warp/normal was garbage); `get_tex_coord_at_point`
   nearest-quad fallback. Dropped `AlignFibreLCS`/`WrapLCS`/`TransferLCS`.
2. `251697cdec` — Phase 7 cleanup: deleted `tools/draper.py`, `tools/lcs.py`,
   `tools/drape_backend_legacy.py`; simplified `TransferRosette._draper_basis_at`
   back to the pure `get_lcs_at_point` path (the duplicate nearest-quad
   workaround was for the now-fixed quaternion bug).
3. `b21f97cbaf` — restore/rehydrate round-trip fixes (unplanned). The
   save/close/reopen round-trip crashed FreeCAD (segfault in
   `App::LocalCoordinateSystem::execute`) because the iterative-solve
   features ran their solve from `onChanged` during document restore
   (re-entrant `doc.recompute()` corrupting the restore graph), and several
   `execute` paths read properties not yet registered during early restore.
   Fixes: skip the solve while `fp.Document.Restoring`; `_solving` guard
   initialised before `super().__init__` and accessed via `getattr`;
   `Rosette._frame_rotation` falls back to the identity frame (instead of
   raising) when `Support` transiently resolves to a `Part.Shape` during
   restore; `CompositeShell.execute` bails early during restore when the
   persisted-drape properties aren't registered yet; `_hide_lcs_view` and
   `fp.Rosette.Angle` reads guarded via `getattr`. Added a rehydrate
   round-trip assertion to `test_rosette_integration`.
4. `008f54a1d1` — `Composites_drape.so` loader fix (unplanned).
   `ext/_native/__init__.py` now falls back to FreeCAD's install Mod tree
   (`<getHomePath()>/Mod/Composites/ext/_native/`) and the user Mod tree when
   the `.so` isn't co-located with the imported package, so `FreeCADCmd` (with
   or without `-P src/Mod`) loads the drape solver with **no env var**.

**Verification:**
- Headless: 10 tests (7 existing + 3 new) green across multiple runs; the
  AlignFibreRosette solve was flaky (~20%) until the recompute-ordering fix
  in `rosette_solver._eval` (place the rosette LCS *before* re-driving the
  shell — FreeCAD's dependency ordering doesn't always execute the rosette
  before the shell reads its LCS as the drape seed).
- GUI (MCP): creation, VP symbol, `claimChildren`, Angle-edit re-solve all
  pass for the three Rosette types; AlignFibreRosette solves to 75.96°
  (v=−0.025 mm), TransferRosette to 30° (residual 0°); both round-trip
  cleanly through save/close/reopen.

**Known follow-ups (not blocking):**
- `FibreCompositeLamina.onDocumentRestored` raises `ArithmeticError: Not
  matching Unit!` during restore — pre-existing, unrelated to this refactor.
- TransferRosette raises a clear `ValueError` when master & attachment
  faces share no topological boundary edge — by design (no picked-edge
  fallback). See §10.1.

**Process lesson (recorded in the freecad-dev skill under "Memory hygiene")**
- FreeCAD processes are ~1–1.5 GB RSS each. Don't run `FreeCADCmd` loops
  alongside the GUI MCP instance, and cap loops at 3–5 runs (not 24). Always
  wrap `FreeCADCmd` in `timeout`. This caused an OOM crash mid-session.

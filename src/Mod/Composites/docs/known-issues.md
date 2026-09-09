# Known Issues — Composites Workbench

**Date:** 2026-07-15
**Status:** Open issues surfaced during the rosette/texture-plan example work
and the cylindrical-to-spherical seam demos. Each entry records the observed
behaviour, the diagnosis where known, the workaround currently in place, and
the suggested fix direction. Recently fixed defects are listed at the end for
context.

---

## 1. nextdrape boundary snapping drops quads (gaps in the weave) — FIXED in solver (nextdrape 93a6b79)

**Symptom:** `quality.failures` reports `gap_fraction > 0.05` and
`diagnostics.coverage_ratio` below 1.0 even though the drape's nodes span the
entire surface. Rendered shells show bare patches, typically along boundaries.

**Diagnosis:** The solver's boundary snapping duplicates a node row when it
snaps nodes onto a boundary edge (e.g. rows at `z = 0` *and* `z = 0.2`). The
degenerate quads between the doubled rows are then dropped, so nodes exist
everywhere but a fraction of the quads never form. On a 47 mm bend arc:

| pitch | nodes | coverage | gap_fraction |
|-------|-------|----------|--------------|
| 20 mm | 31    | 0.667    | 0.333        |
| 10 mm | 87    | 0.800    | 0.200        |
| 5 mm  | 272   | 1.000    | — (pass)     |

The effect is **grid-alignment dependent, not monotonic in pitch**: the
spherical cap in `cyl_sphere_seam` fails at 5/2.5/2.0/1.5 mm, passes at
1.0 mm, and the 30° bend passes at 2.5 mm but not 5 mm.

**Resolution (2026-07-15, nextdrape 93a6b79):** three solver changes —
quads pushed against not-yet-placed boundary proxy nodes are re-validated
once the snap fills the slot (`QuadBuilder::TryRevalidateQuad`); the
face-area budget accumulates each quad's real area instead of a flat
pitch²; and collapsed slivers (shortest edge < 15% pitch) are rejected
explicitly. Built-in `cyl` baseline at pitch 20: coverage 0.73 → 0.98;
the transfer bend example at pitch 2.0: 0.75 → 1.00. Fifteen pre-existing
drape test failures resolved. Remaining caveat: the spherical cap at
pitch 2.5 still shows a small seam-edge gap (0.887 → now higher, verify
per geometry); pitch tuning for very small arcs still applies.

## 2. Intermittent `solver_failure` at fine pitches — RESOLVED (nextdrape 93a6b79)

**Symptom:** identical geometry, seed and params occasionally return
`Drape status: solver_failure` — observed 2 failures in 10 solves at pitch
1.0 mm on the 30° bend, while the surrounding solves succeeded. A failure
mid-transfer-solve left the draper invalid and, before the hardening below,
leaked an `AssertionError` out of `TransferRosette._edge_angle_error`.

**Resolution (2026-07-15, nextdrape 93a6b79):** the failures were the old
count-based face budget at borderline capacity — at pitch 1.0 the quad
count sat almost exactly at the budget, so small geometry differences
between sessions flipped it. The area-weighted budget (issue 1) resolves
the borderline by construction. Verified: 6 fresh-process repeats of the
transfer example and 5 CLI repeats of the cyl baseline at pitch 1.0 —
all succeed with identical coverage. The `RosetteSolveError` hardening
in `TransferRosette._edge_angle_error` stays: a genuinely failed drape
must still surface as a loud feature `Invalid`, never an assertion.

## 3. No wrap-around stopping on closed surfaces — MITIGATED (nextdrape 5b4ef50)

**Symptom:** a drape seeded with the warp running circumferentially on a
closed cylinder spirals indefinitely. The `transfer_rosette` example's
original plate-⊥-cylinder arrangement produced a ply whose warp spanned
2340 mm around a 314 mm circumference (~7 wraps) while
`diagnostics.coverage_ratio` still reported **1.0** — the spiral's nodes
never exactly overlap, so coverage accounting cannot see it. The renderer
shows overlapping, patchy weave.

**Diagnosis:** the warp march follows a geodesic; on a cylinder a
circumferential geodesic is a closed circle with no natural terminus, and
the solver has no self-overlap or azimuthal bound detection.

**Mitigation (2026-07-15, nextdrape 5b4ef50):** the frontier's cell
processing now consults a per-face area accumulator (fed by every
attempted cell, including quads the builder rejects) and stops expanding
the face once accepted+attempted area reaches the surface area with
slack — the ply trims at the meeting line. Closed cylinder at pitch 20:
899 quads / 4.55 wraps → 303 quads / ~1 wrap; the valid fabric covers
the surface exactly once. Four pre-existing test failures resolved.

**Residual:** the march's quantized steps drift ~30 mm per revolution,
so the trim line lands mid-panel instead of closing exactly on the
start — coverage on a closed cylinder is ~0.85 with a seam-adjacent
uncovered strip (physically: a butt joint at the seam). A full fix
requires periodic-surface-aware lattice closing (wrap the face's
periodic parameter into the lattice so the last column connects to the
first); also the meeting-line nodes beyond the trim remain in the node
list as invalid entries.

## 4. `max_strain` quality flag polluted by boundary-snapped nodes — RESOLVED (verified 2026-07-15)

**Symptom:** a *flat plate* with the fabric at 30° reported
`max_strain = 0.283` (28%!) and failed the 2% quality threshold, although the
drape is geometrically exact — the texture-coordinate span matches the
rotated bounding box of the plate to the millimetre
(`100·cos30 + 80·sin30 = 126.6` measured 125.4) and geodesic marching gives
identical results. The strain spikes came from boundary-snapped nodes whose
positions disagree with their lattice positions along diagonally-crossed
boundaries.

**Resolution:** the boundary-aware strain of nextdrape 93a6b79 (edges
incident to `BoundarySnapped` nodes are trimmed cuts, excluded from the
strain; cells touching the trim report no shear) holds on the register's
exact repro: a 100×80 flat plate seeded at 30° with 85 boundary-snapped
nodes now reports `max_strain < 0.02`. The "CoverageGeometry sampling may
still need attention" concern from the 93a6b79 session is closed by
`CoverageGeometry.FlatPanelAngledSeedStrainClean` (nextdrape tests), which
pins the repro against regression. CoverageGeometry's own sampling was not
the pollution source.

Note: the nextdrape suite carries more pre-existing failures than the
2026-07-15 handoff recorded (BaselineShapes.TexturePlanReportLabels*,
TrimVisualizationAndExportStayInParity,
CylindricalArcHasRectangularTextureBoundary, PartLineOutlineTangent.*,
EquatorDiscriminator.*, plus the mould `splitNonPlanarShells` abort) —
verified present on a clean `3e97ba0` checkout by stash-bisect, unrelated
to the stiffener/solver work.

## 5. Fibre shader not re-attached on document restore — RESOLVED (2026-07-15)

**Symptom:** saving and reopening a document with draped composite shells
showed smooth grey surfaces — the drapes were valid (backends rebuild and
solve on recompute) but the Coin shader/injected drape geometry was gone.

**Root cause:** `CompositeShellFP.onDocumentRestored` swaps the
int-serialised ViewProvider proxy for a fresh instance, but the fresh
instance's `__init__` does not call `attach()` — so `drape_host` and the
mode switch were missing and `_inject_drape_geometry` silently bailed at
its `drape_host is None` guard. The post-restore recompute re-draped
correctly and then threw the result away. Secondary ordering hazard:
`updateData`/`load_shader` fired during restore before `attach` bound
`self.Object`, logging attribute errors.

**Fix:** `_inject_drape_geometry` re-attaches the proxy (idempotent
`attach`) when the drape host is missing, so the injection has its scene
node; `reload_shader`/`load_shader` no-op until `attach` has run.
Verified by the register's repro (seam and stiffener examples:
save → close → reopen → recompute; shader `_attached`, drape host
populated, weave rendered). Regression test:
`test_g7_persistence.test_seam_example_shells_reattach_shader_after_reload`
(GUI-gated, same harness as the G7 test).

## 6. `CompositeShell.Shape` does not track a moved support — RESOLVED (2026-07-15)

**Symptom:** the shell feature's `Shape` did not track a moved support.
`TransferRosette._shared_edge` compared the two shells' `Shape` snapshots:
two shells whose supports were 500 mm apart still "shared" an edge (both
snapshots frozen at the origin), so the transfer solve converged against
phantom geometry.

**Root cause (found 2026-07-15, deeper than "stale snapshot"):** the
execute-time mirror `fp.Shape = fp.Support.Shape` **silently drops the
support's placement** — a bare Shape assignment on a Part::FeaturePython
stores the geometry in its own coordinates and reads back with the
shell's own (identity) placement applied. Supports moved via
`Placement` therefore produced a shell `Shape` at the old position even
after a recompute; in-place geometry edits always looked correct, which
hid the bug. Verified with a minimal FeaturePython probe (assignment
loses the location; shape+placement sync preserves it).

**Fix:** `CompositeShellFP.execute` syncs `fp.Placement =
fp.Support.Placement` at both mirror sites (no-laminate fallback and the
full-solve branch), and geometry consumers read through
`util.geometry_util.live_support_shape(shell)` (the `_shape_of` rule,
now shared): `TransferRosette._shape_of` delegates to it, and
`tools/fibre.py`'s fibre-length analysis reads live support geometry.
Regression test: `test_composite_shell.test_live_support_shape_tracks_moved_support`.

## 7. Fallback drape seed is a naive bounding-box clamp

**Symptom:** a composite shell with **no rosette** seeds its drape by
projecting the support's centre of mass onto the surface via a
bounding-box-face clamp (`_project_point_to_surface` in
`drape_backend_nextdrape.py`). For closed surfaces the COM lies on the axis
and the projection degenerates: the seed lands off-surface and the solve
fails with `solver_failure`. This is why the original `transfer_rosette`
example's cylinder never rendered a weave.

**Workaround in place:** all examples wire a rosette (which is also the
compositing-correct modelling). The transferred-cylinder case additionally
documents that an attachment shell must drape from its transfer rosette.

**Fix direction:** replace the bbox clamp with a true nearest-point
projection (`shape.distToShape` / `Surface.projectPoint`), and fail loudly
when the projected seed is further than a tolerance from the surface.

## 8. GUI drape performance during transfer solving — RESOLVED (2026-07-15, frame solve)

**Symptom:** the transfer solve re-draped the attachment shell per
iteration (up to ~40 bisection iterations); builds stretched to minutes and
the solve outran MCP tool timeouts. Worse, the residual was step-quantised
— the attachment-side samples read the boundary-snapped rows of the
attachment lattice — so no root-finder could actually meet the residual
tolerance; the old bisection only *appeared* to converge via its bracket
tightness exit.

**Resolution:** `TransferRosetteFP._solve` is now a closed-form phase-1
frame solve. Both sides are read from rosette frames (master rosette vs the
transfer's own LCS), never from drape fields — consistent with the
documented zero-drape-deviation approximation (ADR-0001) rather than
contradicting it. The residual is exact-linear in the angle (slope −π/180
per degree), per-sample residuals fold mod π (undirected warp), and the
root is one step away; the angle wraps into the fabric's principal period
(wrap_angle) instead of clamping. Per-joint drape count dropped from ~40
per solve to ~2, and the whole stiffener/seam test suites went from
minutes to ~1 minute. `solve_rosette_angle` (still used by
AlignFibreRosette, whose residual is a texture coordinate) is now a
probe-seeded secant with the same wrap discipline.

## 9. Cosmetic — LCS/transfer touched warnings + DAG view error RESOLVED (2026-07-15); MCP screenshot segfault OPEN

**Resolved items:**

- **`Document.cpp(3003): ... still touched after recompute`** for rosette
  LCS datums and transfer rosettes: `RosetteFP.execute` now purges the
  LCS datum's touch after placing it (writing the placement touched the
  datum mid-sweep), and `TransferRosetteFP.resolve`/constructor purge the
  rosette's touch after a solve (the Angle write + LCS placement touch it
  inside the consumer's execute; the state is already consistent).
- **`not a dag exception in DAGView::Model::updateSlot()`** after example
  builds with transfer rosettes: the cycle was real — shell → SCL (its
  Laminate) → transfer (SCL MasterTransfer link) → shell (transfer
  AttachmentShell), and shell → transfer → shell for the foot's rosette.
  The solve-reference links are now `App::PropertyLinkHidden`
  (excluded from dependency calculation, still read normally):
  `TransferRosetteFP.MasterShell/AttachmentShell`,
  `AlignFibreRosetteFP.CompositeShell`, and
  `SeamCompositeLaminateFP.SeamRegion/MasterTransfer/AttachmentTransfer`.
  Freshness is pull-based (fingerprints + resolve()) and the flows
  recompute the SCL explicitly, so no touch propagation is needed.
  Verified: a full stiffener example build now produces **zero**
  touched/DAG warnings in the log.
- **Transient `no matrix material` assert on SCL construction**: wiring
  the last visible reference fired the SCL's onChanged recompute before
  the resin was assigned. Both flows now set `ResinMaterial` before the
  reference assignments.

**Remaining:** the MCP screenshot grab intermittently segfaults
(`QOpenGLFramebufferObject::hasOpenGLFramebufferObjects`) after heavy GUI
sessions, killing FreeCAD during automated viewing. Tooling issue, not
workbench code, but it disrupted verification repeatedly.

---

## Old cosmetic detail (superseded by the resolution above)

- `Document.cpp(3003): ... still touched after recompute` warnings for
  rosette LCS datums and transfer rosettes after every solve. Harmless but
  noisy; investigate why the datum re-marks itself touched.
- `not a dag exception in DAGView::Model::updateSlot()` in the GUI after
  example builds with transfer rosettes (link cycle
  shell→rosette→shell is tolerated by the recompute but trips the DAG view).
  Either make the links dependency-free or suppress the view error.
- The MCP screenshot grab intermittently segfaults
  (`QOpenGLFramebufferObject::hasOpenGLFramebufferObjects`) after heavy GUI
  sessions, killing FreeCAD during automated viewing. Tooling issue, not
  workbench code, but it disrupted verification repeatedly.

---

## Recently fixed (for context, 2026-07-15)

- **AlignFibreRosette solved silently or not at all** — solve failures kept
  the last bracket-probe angle while the feature reported Up-to-date. Now
  any solve failure restores the previous angle and `execute()` raises, so
  the feature shows `Invalid`.
- **TransferRosette never solved on construction** — the `_solving` guard
  suppressed `onChanged` during `__init__` and nothing re-triggered the
  solve afterwards; script-created transfers kept the default angle. The
  constructor now runs `_ensure_wired` + `_solve` directly, and mis-wiring
  (no shared boundary edge) raises `ValueError` at construction.
- **Drape cache ignored the rosette seed** — the cache key tracked shape
  fingerprint, rosette Angle and pitch but not *which* rosette; swapping
  rosettes at the same angle reused a wrongly-seeded drape. The key now
  includes the rosette object and its LCS placement.
- **Grey rosette display** — the native LCS datum glyph dominated the
  coloured rosette symbol; the view providers now hide the datum and the
  symbol is brightened (white circle, brighter axes, thicker lines).
- **Rosette/texture-plan examples** rewritten on the canonical
  `create_composite_feature_stack` builder; the combined rosettes example
  was replaced by three focused examples (`rosette`,
  `align_fibre_rosette`, `transfer_rosette`) plus `cyl_sphere_seam`.

## Recently fixed (2026-07-15, StiffenerCompositeShell session)

- **Build tree never received shader assets — weave rendered black in the
  GUI** — the `CompositesScripts` `file(GLOB_RECURSE)` that copies sources
  into `build/debug/Mod/Composites` listed `*.py *.svg *.ui *.xml *.qrc
  *.css *.FCMat` but not `*.glsl` or `*.png`, so `Grid_fragment_shader.glsl`
  / `Grid_vertex_shader.glsl` (loaded by `MeshGridShader.py` from its own
  directory) never reached the build tree the GUI FreeCAD loads from. The
  *install* glob did include `*.glsl`, so the pixi env (headless tests) was
  always fine and the gap stayed invisible to the suites. Both globs now
  include `*.glsl` and `*.png`. Diagnosed by stash-bisect: the pristine
  tree rendered identically black, exonerating the StiffenerCompositeShell
  diff.
- **Transfer solve re-solve storm** — `_solve_inputs_fingerprint` included
  the attachment shell's Rosette Angle, which for a transfer IS the
  transfer itself: every solve changed its own fingerprint, so each
  `resolve()` re-solved, re-touching dependents (the foot shell draped
  ~1000 times across a test module). The fingerprint now excludes the
  transfer's own Angle, and no-op Angle writes are skipped (same-value
  writes still touch dependents).

## #10 — Drape cache fast-path ignores support-shape validity

**Status:** OPEN (found during SeamCompositeLaminate GUI verification, 2026-07-15)

`CompositeShell._can_use_persisted` compares the support's shape
*fingerprint* against the cached one, but an *invalid* (empty-compound)
support re-assigned over a previously valid one can leave the cached
drape in place: the shell keeps rendering its weave from a solve that no
longer corresponds to any real geometry. Recovery is correct — restoring
valid geometry re-drapes and re-attaches the shader.

Repro: load the `seam_composite_laminate` example, set the seam shell's
support `Shape` to `Part.Compound()`, recompute — weave persists,
`grid_shader._attached` stays True.

Fix direction: the fast path should treat a null/empty support shape as
a cache miss and route through `_mark_failed` (loud breakage), never
silently reusing a solve for geometry that no longer exists.

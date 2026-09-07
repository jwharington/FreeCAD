# Known Issues — Composites Workbench

**Date:** 2026-07-15
**Status:** Open issues surfaced during the rosette/texture-plan example work
and the cylindrical-to-spherical seam demos. Each entry records the observed
behaviour, the diagnosis where known, the workaround currently in place, and
the suggested fix direction. Recently fixed defects are listed at the end for
context.

---

## 1. nextdrape boundary snapping drops quads (gaps in the weave)

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

**Workaround in place:** examples pin `DRAPE_PITCH` per geometry (2.5 mm
typical) with comments; the residual gap on the spherical cap (coverage
0.887) is visible and documented in the example docstring.

**Fix direction:** in the boundary-snapping step, move the original node
onto the boundary instead of duplicating it (or drop the *original* row
rather than keeping both), so no degenerate quads are created.

## 2. Intermittent `solver_failure` at fine pitches

**Symptom:** identical geometry, seed and params occasionally return
`Drape status: solver_failure` — observed 2 failures in 10 solves at pitch
1.0 mm on the 30° bend, while the surrounding solves succeeded. A failure
mid-transfer-solve left the draper invalid and, before the hardening below,
leaked an `AssertionError` out of `TransferRosette._edge_angle_error`.

**Workaround in place:** examples avoid the flaky pitches;
`TransferRosette._edge_angle_error` now converts an invalid draper into a
handled `RosetteSolveError` (loud feature `Invalid` state) instead of an
assertion leak.

**Fix direction:** find the nondeterminism in the C++ drape solve at fine
pitches (suspect an iteration/step budget interacting with mesh rounding).
Add a repeat-solve regression test at the failing pitch.

## 3. No wrap-around stopping on closed surfaces

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

**Workaround in place:** examples use open/bounded panels and rosette seeds
whose warp does not run circumferentially on closed surfaces.

**Fix direction:** detect lattice self-overlap during marching (a new node
nearer to an existing node than one pitch) and stop/trim the ply there.

## 4. `max_strain` quality flag polluted by boundary-snapped nodes

**Symptom:** a *flat plate* with the fabric at 30° reports
`max_strain = 0.283` (28%!) and fails the 2% quality threshold, although the
drape is geometrically exact — the texture-coordinate span matches the
rotated bounding box of the plate to the millimetre
(`100·cos30 + 80·sin30 = 126.6` measured 125.4) and geodesic marching gives
identical results. The strain spikes come from boundary-snapped nodes whose
positions disagree with their lattice positions along diagonally-crossed
boundaries.

**Consequence:** the quality flags are unreliable for fabrics laid at an
angle to the surface parametrisation — the common case for real layups.
Both rosette examples currently carry these flags (documented in their
docstrings).

**Fix direction:** compute strain *after* boundary snapping settles node
positions (compare against snapped neighbours, not the ideal lattice), or
exclude boundary-snapped nodes from the strain histogram.

## 5. Fibre shader not re-attached on document restore

**Symptom:** saving and reopening a document with draped composite shells
shows smooth grey surfaces — the drapes are valid (backends rebuild and
solve on recompute) but the Coin shader/injected drape geometry is gone.
The view provider restore path never re-runs the injection that
`_configure_shell_visuals` performs at build time.

**Repro:** build `cyl_sphere_seam`, `doc.saveAs(...)`, reopen, recompute.
Backends report valid; surfaces render untextured.

**Workaround in place:** none for the user; the examples are demonstrated
from fresh builds.

**Fix direction:** on `ViewProviderCompositeShell.attach` (or after the
first successful post-restore execute), re-run the shader attach + drape
geometry injection, guarded so it does not double-inject in the build path.

## 6. `CompositeShell.Shape` is a stale snapshot of the support

**Symptom:** the shell feature's `Shape` does not track a moved support.
`TransferRosette._shared_edge` compared the two shells' `Shape` snapshots:
two shells whose supports were 500 mm apart still "shared" an edge (both
snapshots frozen at the origin), so the transfer solve converged against
phantom geometry.

**Fixed for the transfer path** (`_shape_of` reads `Support.Shape`), but the
stale `Shape` property itself remains a trap for any other consumer that
reads `shell.Shape` expecting live geometry.

**Fix direction:** either refresh `Shape` from `Support.Shape` whenever the
support fingerprint changes in `execute()`, or deprecate `shell.Shape` in
favour of `shell.Support.Shape` for geometry queries.

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

## 8. GUI drape performance during transfer solving

**Symptom:** the transfer solve re-drapes the attachment shell per bisection
iteration (up to ~40 iterations). Headless this is seconds; in the GUI each
iteration also runs view-provider/shader updates, stretching builds to
minutes, and the solve outruns MCP tool timeouts.

**Workaround in place:** none; demonstrated builds complete if the client
waits.

**Fix direction:** batch the solve iterations without view updates (suspend
the VP during `_solve`, re-inject once at the end), and/or cache per-angle
drape results to skip re-meshing when only the seed rotates.

## 9. Cosmetic

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

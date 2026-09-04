# Stiffener Feature Design

**Date:** 2026-07-07  
**Status:** Draft  
**Related:** `features/Stiffener.py`, `tools/stiffener.py`, `features/VPCompositePart.py`

## Decided (via design grill)

- **Sweep path via cut plane (Design 2)**: the stiffener sweep path is the
  **intersection of an intersecting shape with the support face**, computed
  with a shape↔face intersection. No directional projection
  (`BRepProj_Projection`) is used. The annular-frame case is exact: a plane
  perpendicular to the cylinder/cone axis intersects in the clean ring.
- **Inputs (Design 2)**: `Support` + an **intersecting surface** (a
  `Part::Plane`, or any surface/face that can be intersected with the
  support) + `Profile`. There is **no plan sketch and no plan geometry** in
  Design 2 — the cut surface is the path source.
- **Sweep extent = the whole path** — the profile sweeps the entire
  intersection curve (full ring for a cylinder cut). No extent clipping.
- **Profile sketch convention (support-agnostic)**: the profile is a 2D
  sketch with **x** and **y** axes. At each path station (origin on the
  path = the cut line), the local frame is:
  - **t** = path tangent (lies in the cut plane)
  - **N** = cut-plane normal
  - **b** = in the cut plane, perpendicular to t
  A profile point `(x, y)` maps to `origin + x·N + y·b`:
  - sketch **x** extends along the **cut-plane normal N** (lateral / width)
  - sketch **y** rises along **b** (the in-plane perpendicular to the path
    tangent) — the stiffener **height**
  No assumption about support shape (cylinder/cone/plate/...) is made.
- **y = 0 is the stiffener base and always hugs the actual support surface.**
  `x=0,y=0` is the origin on the path. Any point with `y=0` (e.g. `x=10,y=0`)
  is a point on the **actual surface**, found by travelling `x` mm along the
  cut-plane normal and snapping back onto the surface (a snap, not a
  directional projection). So a line `x=0..10` at `y=0` is the **curve on the
  surface**, not a chord. The base row is surface-conformal for any support
  shape.
- **Frame travels along the path (not fixed).** At each path station the
  local frame is built from the **path tangent t**, the **cut-plane normal N**,
  and **b** = **t × N**. The frame moves as the origin sweeps the path; the
  cut-plane normal N is the reference for the profile's lateral axis (sketch
  x), avoiding the need for the curve's own Frenet normal.
- **Default handedness is pinned: `b = t × N`.** The profile triad is
  right-handed — `sketch x × sketch y = +t` (the direction of travel), which
  is equivalent to `b = t × N` and `N × b = t`. Consequence for the canonical
  ring case (cylinder/cone axis `+Z`, `Part::Plane` at `z0` with normal `+Z`,
  path traversed CCW): `t = (-sinθ, cosθ, 0)`, `N = (0, 0, 1)`, so
  `b = t × N = (cosθ, sinθ, 0)` — the profile's **+y stands off the
  convex/outward side** of the skin. `MirrorX` / `MirrorY` flip from there.
- **Path traversal direction is pinned** — the sign of `t` is part of the
  default handedness, not an incidental detail: the path starts at the
  **lexicographically smallest path vertex** and edge orientations follow the
  wire. Flipping `t` or `N` alone rotates or mirrors the section, so without
  this rule the pinned `b = t × N` would still be non-deterministic across
  recompute.
- **`MirrorX` / `MirrorY` remain** — each negates the corresponding sketch
  axis in the moving frame: **MirrorX** flips the profile's width direction
  (sketch x → cut-plane normal N), **MirrorY** flips the height direction
  (sketch y → in-plane b). Support-agnostic.
- **Face selection**: when the whole support object is selected (no specific
  face), the tool works on **all faces one by one** — one stiffener per
  face. When a specific face is selected, just that face.
- **Curved-panel / annular-frame stiffeners are essential scope** for
  `StiffenerFP` — not a "known failure" to ship around.
- **Profile topology is irrelevant to assembly.** Open or closed profile,
  branched or not — each profile edge is lofted along the whole path into a
  face and grouped into the open-shell compound. No topology-specific
  assembly logic.
- **Output is an open surface shell** — a compound of faces, not a closed
  solid. Each profile edge is lofted along the path into a face (e.g. the Z's
  bottom-flange/web/top-flange edges → three lofted faces), grouped into a
  compound. (This answers the old draft's "solid vs shell/compound" open
  question.)

## User interface

**Command:** `Composites_Stiffener`

**Inputs:**
- `Support` (`Part::Feature`) - support geometry (an object, a face, or a
  surface that a sweep path can be intersected from)
- `IntersectSurface` (`Part::Plane`, or any surface/face intersectable with
  the support) - the cut surface that produces the sweep path
- `Profile` (`Sketcher::SketchObject`) - the 2D stiffener cross-section
- `MirrorX`, `MirrorY` (`App::PropertyBool`) - flip the sketch x / y axis

**Behavior:**
- The sweep path = the intersection of `IntersectSurface` with the support
- The profile is swept along that path (each profile edge lofted to a face)
- The result is an open surface shell (compound of faces)

There is no `Plan` and no directional projection.

## Data model

- `StiffenerFP` remains a `Part::FeaturePython`; output stays a generic Part
  feature (usable outside composites).
- Properties: `Support`, `IntersectSurface`, `Profile`, `MirrorX`,
  `MirrorY`.

## Sweep geometry

See the "Decided (via design grill)" section at the top for the authoritative
frame and mapping rules (t / N / b frame with b = t × N, x → cut-plane normal,
y → in-plane perpendicular, y = 0 surface-conformal base, whole-path sweep,
open shell output).

### Frame at a path station
- **t** = path tangent (lies in the cut plane)
- **N** = cut-plane normal
- **b** = **t × N** — in the cut plane, perpendicular to t
- profile point `(x, y)` → `origin + x·N + y·b`
- right-handed triad: `sketch x × sketch y = +t`
- **t** follows the pinned traversal — start at the lexicographically smallest
  path vertex, edge orientations follow the wire

### Base row
- `y = 0` always hugs the actual support surface: `x,0` is the surface point
  found by travelling `x` mm along the cut-plane normal and snapping back
  onto the surface. `x=0,y=0` is the origin that follows the path.

## Mirror control

- `MirrorX` negates the sketch x axis (cut-plane normal direction)
- `MirrorY` negates the sketch y axis (in-plane height direction)
- Both mirror from the pinned default `b = t × N` — they are the only
  orientation controls.

## Output structure

- **Output type:** `Part::FeaturePython`
- **Result:** an open surface shell — a compound of faces (one lofted face
  per profile edge along the path). Not a closed solid.
- Auxiliary tool geometry stays internal; the public result is the face
  compound.

## Success criteria

1. **Correctness**: the stiffener is placed and swept as intended, including
   the annular-frame (ring) case on a cylinder/cone
2. **Robustness**: works reliably on valid support geometries; intersection
   producing no path is handled, not a crash
3. **Generality**: usable outside the composites domain
4. **Maintainability**: frame/sweep logic is understandable and testable
5. **Coverage**: core behavior is backed by tests

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cut-plane/support intersection fails or splits on complex surfaces | High | Validate support & surface; handle a no-result/partial path cleanly |
| Local frame becomes hard to reason about | Medium | Factor out frame construction + add tests |
| Output shape unstable across recompute | Medium | Keep output deterministic; pinned path traversal rule fixes the sign of t, hence b |
| Feature becomes too composite-specific | Medium | Preserve generic Part output |

## Implementation phases

#### Phase 1: Intersection path
- Compute the sweep path as `IntersectSurface` ∩ support
- Replace `generate_origin_wire` (projected wire) with the intersection path

#### Phase 2: Frame construction
- Build the moving (t, N, b) frame per station; map profile (x, y) per the
  agreed convention
- Surface-conformal y=0 base row (normal-offset + snap to surface)

#### Phase 3: Sweep to open shell
- Loft each profile edge along the path into a face; assemble the compound
- Preserve MirrorX / MirrorY

#### Phase 4: Testing
- Unit: frame construction, surface-conformal base, default handedness (ring
  `+y` = outward radial)
- Geometry: rect + Z on plate; rect + Z as a ring on cylinder/cone
- Integration: command execution; mirror; save/load
- Replace the current "known failure" curved tests with passing ring tests

## Related files

- `features/Stiffener.py` - feature definition
- `tools/stiffener.py` - geometry logic (to be reworked per this design)
- `features/VPCompositePart.py` - shared view-provider base

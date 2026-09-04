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
  face), every face the cut surface meets is swept. Curves that meet are joined
  into one path (this is what bends a path over a fold); curves that do not meet
  are swept as separate paths. When a specific face is selected, just that face.
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
  question.) Since then the shape has taken on the remainder of the cut
  support as a second child, with CompoundFilters picking the two apart —
  see Output structure.

## User interface

**Command:** `Composites_Stiffener`

**Inputs:**
- `Support` (`Part::Feature`) - the shell being stiffened: a face, a shell, or
  a compound of faces. A solid is rejected — the stiffener is laid on a shell.
- `IntersectSurface` (`Part::Plane`, or any surface/face intersectable with
  the support) - the cut surface that produces the sweep path
- `Profile` (`Sketcher::SketchObject`) - the 2D stiffener cross-section
- `MirrorX`, `MirrorY` (`App::PropertyBool`) - flip the sketch x / y axis

**Behavior:**
- The sweep path = the intersection of `IntersectSurface` with the support
- The profile is swept along that path (each profile edge lofted to a face)
- The feature's shape carries the stiffener and the remainder of the cut
  support; `Part::CompoundFilter` objects expose each part (see Output
  structure)
- **Visibility:** the two filters are visible; the feature itself, the
  intersecting surface and the profile stay hidden, and in the examples the
  pristine support yields to its remainder on screen
- **Example documents:** one example per document; curved supports are open
  shells — the lateral face alone, no end caps

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
- The row at abscissa `x` is **cut the same way the path is**: the intersecting
  surface moved `x` mm along its own normal, sectioned against the support. So
  `y = 0` is the surface curve, not a chord, and the row is an exact curve
  (a circle on a cylinder, a line on a plate) rather than a fitted one.
- Where the cut surface is bent it has no single normal, so rows are sampled
  along the path and snapped back onto the support instead.
- `x = 0, y = 0` is the origin that follows the path.

### Lifting by y
- The row is moved sideways by `y` along `b`, staying in its own plane: a rigid
  translation where the row is a single straight line, an exact planar offset
  otherwise.
- OCCT's offset expands or shrinks by area, which agrees with `b = t × N` for a
  closed curve but not necessarily for an open one, so the sign is read back
  from the result and flipped if it ran the wrong way.

### Orientation of travel
- Closed or curved paths: travel follows the right-hand rule about `N`, decided
  from the sign of the path's area vector.
- Straight (zero-area) paths have no winding sense, so travel uses positive
  axis order.

## Mirror control

- `MirrorX` negates the sketch x axis (cut-plane normal direction)
- `MirrorY` negates the sketch y axis (in-plane height direction)
- Both mirror from the pinned default `b = t × N` — they are the only
  orientation controls.

## Output structure

- **Output type:** `Part::FeaturePython`
- **Result:** the feature's shape carries the stiffener and the remainder of
  the cut support as its two children, and two `Part::CompoundFilter` objects
  pick them apart — one for the stiffener parts, one for the remainder. The
  filters recompute with the feature, so both parts stay current through any
  edit of the support, cut surface or profile. The feature itself is left
  hidden: it draws everything the two filters draw between them.
- **Support remainder:** a copy of the support with the stiffener cut away
  (boolean difference), one face per piece — a plate falls into the regions
  beside the stiffener, a cylinder into the bands above and below a ring.
  Each support face is cut on its own, which is also what an open support of
  several faces needs.

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
| Cut-plane/support intersection fails or splits on complex surfaces | High | Validate support & surface; handle a no-result/partial path cleanly; section an open multi-face support one face at a time |
| Local frame becomes hard to reason about | Medium | Factor out frame construction + add tests |
| Output shape unstable across recompute | Medium | Keep output deterministic; pinned path traversal rule fixes the sign of t, hence b |
| Feature becomes too composite-specific | Medium | Preserve generic Part output |
| Rows and loci fitted through sampled points drift (~1e-4 mm over a ring) | Medium | Rows come from an exact re-intersection, lifts from exact offsets; sampling is left to bent cut surfaces only |

## Known limitations

- Where the section **branches** — one face of the support running through
  another, say — the branches are swept as separate paths, since no single path
  can take both routes.
- A bent (non-planar) cut surface has no single `N`, so its rows and loci are
  sampled and fitted rather than exact.
- A `Part::Plane` cut surface is finite: sized to span the support it cuts a
  closed ring, sized shorter it deliberately cuts a partial ring (an open arc).
  Both are supported; the plane's extent is the control for the arc's extent.

## Implementation

The four phases below landed together in one change: the path was the part
worth pinning down first, but a path with nothing swept along it proves little,
so the frame, the sweep and the tests went in as one.

#### Phase 1: Intersection path — done
- `intersection_paths` sections the cut surface against the support; the
  projected wire and its plan sketch are gone, as is `Direction`
- A multi-face open support is sectioned face by face; pieces that meet are
  joined into one path, pieces that do not are swept separately

#### Phase 2: Frame construction — done
- `Station` carries `point, tangent, normal, height` with `height = t × N`
- Base rows come from re-sectioning the support with the cut surface moved
  along its normal; lifts are exact offsets read back against `b`

#### Phase 3: Sweep to open shell — done
- One lofted face per profile edge along the whole path; `MirrorX` /
  `MirrorY` negate the profile abscissa / ordinate before the mapping
- Support fragments are no longer glued into the result (leftover from the
  projected-sweep prototype, where they inflated every bounding box)

#### Phase 4: Testing — done
- Path level: closed ring vs partial arc, ring lies on the surface (curve, not
  chord), cone ring radius, default `b` outward, straight path on a plate,
  path over a fold between two faces, a path per piece of a split support,
  cut surface clear of the support
- Feature level: rect and Z sections on a plate, ring on a cylinder (radii to
  1e-6), Z ring on a cylinder and on a shell panel, oblique cut on a cone,
  mirror sides, no-path error state, save/load, the example build
- The former "known failure" curved tests are now passing ring tests

## Related files

- `features/Stiffener.py` - feature definition
- `tools/stiffener.py` - geometry logic
- `features/VPCompositePart.py` - shared view-provider base

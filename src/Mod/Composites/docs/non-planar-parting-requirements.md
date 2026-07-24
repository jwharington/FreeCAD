# Non-Planar Parting — Requirements (nextdrape, C++)

**Date:** 2026-07-24
**Status:** Requirements specification. Implementation is a separate, larger C++ effort in the `nextdrape` submodule; this document is the spec to approve and build against.
**Scope:** The parting-surface and mould-half construction that replaces the planar midpoint parting for twisted/cambered geometry in the Composites mould-analysis path.

## Why C++ in nextdrape

The general construction needs low-level BREP traversal — walking each source face, trimming it at the part line, and assembling a mould **shell half** from the per-face BREP halves. That traversal is not efficiently exposed at FreeCAD's Python level, and a Python implementation would be far too slow for the fast loop (`box`/`blade`/`loft`) and ultimately `propblade`. The work therefore belongs in C++ with direct OCCT access, alongside the existing nextdrape draping solver. The C++ helper exposes a pybind11 binding (mirroring `CompositesDrape`) consumed by `analyze_source_shape` in Python, which runs the withdrawal-clearance gate and the verdict.

## Inputs

- `source` — the BREP solid to be moulded.
- `draw_direction` `D` — a unit vector, **user-specified and authoritative** (the analysis no longer auto-ranks directions).
- `land_width` `W` — minimum parting-surface projection width (default **25 mm**).
- stock-block footprint — rectangular, the source bbox plus margin. **Both auto-derived and user-overridable**: auto by default (bbox + a margin parameter), with an optional explicit override of the block dimensions/footprint.

## Outputs

- `parting_surface` — a single continuous surface (the skirt; see below).
- `mould_half_upper` — the `+D` side solid, valid.
- `mould_half_lower` — the `-D` side solid, valid.
- diagnostics: the part-line curve(s); which source faces were tangent-surface degenerate cases (and the midpoint chosen for each); any self-intersection warnings from the outset path.

## The part line

The part line is the 3D curve on the source where the outward surface normal is perpendicular to the draw direction (`normal · D = 0`) — the silhouette / equator. It is generally non-planar for twisted geometry (its height along `D` varies around the part).

### Tangent-surface degenerate case

Where a source face is **locally tangential to the draw direction** — i.e. `normal · D = 0` holds *everywhere* on that face (a face that contains the `D` direction, such as the cylindrical side wall of a part drawn along its axis) — there is no unique part line on that face. The part line could lie higher or lower on the face. In that case, **choose the midpoint** of that face's extent along `D` as the part-line location. This midpoint choice must be reported in the diagnostics.

## The parting surface (the skirt)

The parting surface is projected outward from the part line; it is **not** transitioned to flat.

- At each point of the part line, project outward in the parting plane (the plane perpendicular to `D`), along the local outward normal of the part line, **preserving the `D`-height**. The parting surface is the ruled surface swept by these projection lines.
- The projection reaches **at least `W` (25 mm)** from the part line and **continues to the rectangular stock-block boundary** (which is ≥ `W` away).
- The surface carries the part line's `D`-height profile all the way to the block walls. It is **flat only where the part line's `D`-height is constant** (a planar part line). For twisted geometry, where the part line's height varies, the entire parting face out to the block edge is contoured — there is no flat land.

## Construction paths

Two construction paths, chosen by the part line's shape. The OCCT API references below are verified against the OCCT 8 reference (via OCCTSwift); items marked *(needs verification)* are flagged for the C++ author to confirm on real freeform geometry.

### Shared step: part-line extraction

- Compute the equator/part line on the source where the outward normal is perpendicular to `D` (`normal·D = 0`). OCCT API: **`Contap_Contour`** driven by an orthographic direction `D` (per-face: `contapContourDirection(D)`), or `shape.reflectLines(ViewDir=D)` over the whole shape — returns a compound of contour/outline curves lying on the surfaces.
- **Tangent-surface degenerate case:** where a whole face satisfies `normal·D = 0` (a face that contains the `D` direction, e.g. a cylindrical side wall along the axis), `Contap_Contour` yields no curve on that face — the part line is ambiguous there. Handle explicitly: choose the **iso-curve at the face's `D`-midpoint** (the midpoint of the face's parametric/domain extent along `D`). Report each such face and the chosen midpoint in diagnostics.
- The part line is generally a **non-planar 3D curve** for twisted geometry (its `D`-height varies around the part).

### Path 1 — convex part line, 3D outset (also the planning preview)

Where the part line is convex when projected along `D`, build the skirt by outsetting the part line in 3D, `D`-height-preserving:

1. Project the part line onto the plane `⊥ D` → a 2D curve.
2. 2D-outset that projected curve outward using **`BRepOffsetAPI_MakeOffset`** with the **`GeomAbs_Intersection`** join type (which is what handles self-intersection at corners). Note: `BRepOffsetAPI_MakeOffset` is **planar-only** (it constructs a `BRepBuilderAPI_MakeFace` internally and returns nothing for non-planar wires), which is why the projection step is required.
3. Re-lift each offset point back to 3D by re-attaching the `D`-height of the corresponding original part-line point. This correspondence is preserved **only because the part line is convex** (no self-intersection re-orders the topology); that is the limiting assumption of this path.
4. Build the skirt surface as a ruled surface between the part line (inner) and the lifted outer curve, via **`GeomFill` / `BRepFill`** (ruled surface from two curves). *(needs verification: the exact `GeomFill` variant for ruled-from-two-3D-curves on OCCT 8.)*
5. Continue the outset (or project the outer curve further) until the outer curve reaches the rectangular stock-block boundary (≥ `W`).

This path is **kept even after Path 2 exists**: for planning and diagnostics one often wants to *see the part line and the outset skirt* without generating the full mould half. Path 1 provides a cheap, inspectable preview independent of the full BREP shell-half build.

### Path 2 — general (non-convex / twisted), BREP shell-half

For non-convex / twisted part lines the 3D outset breaks (self-intersection re-orders topology and the `D`-height correspondence is lost), so construct the mould half directly from the source BREP:

1. Assemble the part line as a **compound of boundary curves, one set per source surface**, from the silhouette/projection lines and the points where each meets the body (the per-face output of the shared step above).
2. Split each source face along its part-line segment using **`BRepFeat_SplitShape::SplitByWire(wire, onFace)`** (or `LocOpe_Spliter` / `locOpeSplit` for a batch of wire/face pairs). *(needs verification: behaviour when the part-line wire only partially lies on the face, e.g. at face boundaries.)*
3. Keep the `+D` or `−D` half of each split face using side selection — `faceFromSurface(surface, wire, inside:)` (`BRepBuilderAPI_MakeFace` with inside/outside), or by selecting the split sub-faces whose centroid lies on the target side.
4. Extend each part-line boundary outward to the rectangular block edge **per face, along that face's own surface geometry** (rather than a global 3D outset), preserving `D`-height. This local-per-face outset is more robust than the global outset because each extension lives on a single surface where the outward direction is well-defined. *(needs verification: the OCCT API for extending a face's boundary curve along the surface to an external boundary — likely `BRepOffsetAPI_MakeOffset` per face after the face is made planar-locally, or `GeomAdaptor_Surface` + iso-curve extension.)*
5. Assemble the kept half-faces + the per-face outset extensions into a **closed shell** for the mould-interior surface; cap with the rectangular stock-block faces to form a valid solid.

This avoids fragile block-splitting booleans and is the general path for non-convex / twisted part lines.

### Which path when

- **Path 1 (convex outset)** is used for simple/convex shapes and as the part-line/skirt preview for planning (no mould-half generation).
- **Path 2 (BREP shell-half)** is used to actually generate the mould halves for twisted/cambered geometry (`blade`, `loft`). Both are implemented in C++ (nextdrape); Path 1 is the cheaper entry point and a preview mode.

## Mould halves

- Each half is one side of the mould interior (the shell half), extended by the skirt/land to the rectangular block, with the source cavity.
- Upper (`+D`) and lower (`-D`) halves mate on the parting surface.
- Both must be valid solids.

## Gate (validity)

Withdrawal clearance is the authoritative necessary test, already wired into the Python analysis verdict (`analyze_source_shape` → `_withdrawal_clearance_validity_check`). Each mould half must translate along `±D` without intersecting the source. **Validation criterion:** the construction must release `blade` and `loft` for at least one user-specified draw direction (WC = Pass). If it cannot, the model is reconsidered.

## Performance

C++ is the explicit reason for not doing this in Python. The construction must be fast enough for the fast loop and, ultimately, `propblade`. A Python-level BREP traversal was ruled out as too slow.

## Determinism and testability

- Deterministic for a given `(source, D, W)` triple.
- Headless-testable: the C++ binding returns the parting surface and both halves as shapes; the existing Python WC gate and the committed tests (`TestPlanarPartingInsufficiency`, the fast-loop test) verify behaviour.
- A new committed test will assert WC = Pass for `blade` and `loft` under at least one direction once the C++ helper lands (replacing the current negative-regression expectation that planar fails them).

## Integration and sequencing

- The Python side (`analyze_source_shape`) is already ready to consume a non-planar parting surface behind the WC gate once the C++ helper exists — the false-confidence seam is closed, and the verdict already reflects WC.
- Until the C++ helper lands, the planar model remains, with the committed negative regression documenting that planar fails `blade`/`loft` under every direction.
- This document is the spec; C++ implementation is a separate, larger effort to approve and schedule.

## Open questions

- How is the `D`-height-preserving outward direction defined precisely at part-line points where the local outward normal is ill-defined (inflections)?
- What is the default stock-block margin (the auto path), and is it a single value or scale-relative?
- How should the part-line/skirt preview (convex outset path, no mould generation) be exposed — a separate binding entry point, or a mode flag on the main one?

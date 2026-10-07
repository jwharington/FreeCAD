# Bulkhead section generation — design record

Status: **section and feature layers implemented and tested; the composite
wiring (Laminate → drape → stack model) is the deferred part.**
This records what was *measured* about the fixture, and it was written after the
measurement. `handoff-2026-10-07-bulkhead-tool.md` is the input specification;
where the two disagree, this file is the one that was checked against geometry.

Code: `tools/bulkhead_section.py` and `features/Bulkhead.py`. Measurement:
`compositestests/test_bulkhead_section.py` and `compositestests/test_bulkhead.py`
— run them with
`~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_bulkhead_section`.

## 1. What a bulkhead's section has to be

A bulkhead is a plate with flanges: a wall standing in the cutting plane,
joined to the panel along the section line where the cutting surface meets
the support, and gusseted into it by a foot lying on the skin on one side of
that wall. Its section is therefore *filled* — a region — bounded by the
section chain (one closed chain where the cutter crosses one face; a cut
across the band seam returns one chain per face, a compound and not one
stitched sheet), and its foot occupies exactly one `width` of skin behind the
plate — or ahead of it when `MirrorX` is set.

`tools/bulkhead_section.py` keeps the path layer and the band layer separate:
`section_chains` finds where `cut_surface` cuts `support`, `plate_of` fills
the region each chain bounds, and `member_slab` / `band_of` / `drape_cuts_of`
are one prism and its two reads — the band taken out of the support, and
what the support keeps around it.

## 2. The two premises that did not survive measuring

Both were written down as fact before anything had been run, and both were
wrong. They are kept here because the code is easier to trust if the reasoning
that replaced it is visible.

### 2.1 "`make_stiffener` can sweep a bulkhead's section"

It cannot, and that is why there is a section layer at all. `get_xsect`
(`tools/stiffener.py:254`) rebuilds every profile edge as a `Part.LineSegment`
between that edge's **endpoints**, and `_profile_coords` keys a profile's
vertices to six decimals. A profile's edges are joined end to end, so a
profile fed in as one closed chain of two edges comes back as two line segments
between the same two points — a degenerate sliver, not a section. A bulkhead's
section is bounded by curved chains, so it cannot travel through the profile
route, and R2's "reuse the foot construction" resolves as *reuse
`wire_composite_stiffener` and its helpers*, not as *call `make_stiffener`*.

### 2.2 "The hole test is blind to inner wires"

**False** — and worth correcting carefully, because the specification did not
actually say this, my own earlier summary of it did. §5.2 of the handover asks
only that the fill rule *keep* `IsInsideFace` and the mesh-continuity rules
intact; the "blind to inner wires" wording was mine.

`SurfaceNavigator::IsInsideFace`
(`src/3rdParty/nextdrape/src/drape/SurfaceNavigator.cpp:418`) **does** look at
holes. `BuildTrimCache` splits a face's trim boundary into an outer wire — the
one with the largest |signed area|, with a bisection fallback when that test
degenerates — and holes, and points strictly inside a hole are rejected by
`PointStrictlyInsidePolyline` with a *strict* inside test and no `tol`
inflation. The comment there records that an earlier version did treat boundary
rows as exterior and that this was fixed; `!IsInsideFace` at
`LatticeNodePlacer.cpp:1831` is a *healed* defect, not an open one.

What is true is narrower:

- a self-crossing outer wire **is** what loses coverage, because
  `PointStrictlyInsidePolyline` uses an even-odd crossing count and a
  self-crossing polyline produces two crossings near the crossing point; and
- `trimValid` stays false unless `anyPCurve` is set **and** the trims are
  non-empty, so a procedural BSpline skin built with `makeLoft` and never
  trimmed has no hole test to satisfy.

### 2.3 What the fixture actually does

Measured on the two-chain lofted skin (two BSpline faces, `makeShell` *and*
`makeCompound`), five cuts, headless:

| probe | chains | self-crossing | band faces w34/d12 | w90/d12 | w90/d120 |
|---|---|---|---|---|---|
| x=210 axial, mid forward band | 1, closed | no | 1 | 2 | 2 |
| x=420 axial, mid aft band | 1, closed | no | 1 | 2 | 2 |
| x=700 axial, clear of support | **0** | — | — | — | — |
| x=300 oblique `n=(1,.55,.35)`, through seam and both open ends | 3 edges, closed | no | 3 | 2 | 2 |
| x=210 steep `n=(1,.9,0)`, side 420 | 1, closed | no | 1 | 2 | 1 |

Four consequences, all of which are assertions in the test file rather than
prose here:

- **Multi-boundary does not arise on this fixture.** Every cut gives exactly one
  closed chain, and none of them self-crosses (checked by discretising each
  chain to 240 points and keying them to five decimals, so a genuine reversal
  survives rounding and one that merely doubles back on itself does not). If a
  future fixture produces two chains, the suite says so.
- **The seam-crossing case is real, and needs per-face faces.** x=300 crosses
  the band seam and comes back with **3** band faces against **1** for an axial
  mid-band cut. A compound of faces, not one stitched sheet — which is what
  rules out a one-call `Section::Once` for the member as a whole.
- **A band exists at a normal flange width.** An earlier draft recorded
  `band(34,12)` as *empty* on the strength of a probe that had crashed before
  printing; measured properly the band is there and has area.
- **A cut can miss the support entirely** (x=700, `distToShape` = 160), and that
  is a different answer from "there is no band to take out of", so the two are
  kept distinguishable in the API rather than collapsed into one empty list.

## 3. Where the prism reaches — and why there is no `depth`

The prism (`member_slab`) runs one-sided: from `width` behind the cutting
surface up to that surface itself, extruded along the surface normal.  There
is no second `depth` knob — it was a boolean-tool dimension that leaked into
the feature API, and while the slab straddled the surface the band's far
edge depended on that arbitrary number.  Now the band's far edge *is* the
section chain: `band_of` and `drape_cuts_of` share one prism, so band and
footprint can never overlap, and `flange_width` is the feature's only shape
parameter.
## 4. What the module exposes, and why each query is shaped that way

Seven functions, no placeholders (the last two compose the feature's Shape
from the first five; `chain_regions` answers the §1 question of *where* a
chain runs, not *what* to take, and is unused until the wiring task needs it):

| | | |
|---|---|---|
| `section_chains(support, cut)` | the chains where the cutter cuts the support | delegates to `stiffener._section_groups` |
| `chain_regions(support, chain)` | which support faces that chain runs along | `(face, boundary, interior)` per face |
| `plate_of(support, cut)` | the filled section, one face per closed chain | `Part.Face` per region |
| `member_slab(support, cut, w, mirror_x=False)` | the prism the band and footprint are taken out of | one solid, or `None` |
| `band_of(support, cut, w, mirror_x=False)` | the flange band, as faces | `support.common(slab)` |
| `drape_cuts_of(support, cut, w, mirror_x=False)` | what the panel keeps: skin minus prism | `face.cut(slab)` per face |
| `make_bulkhead(support, cut, w, mirror_x=False)` | `(plates, bands)` ready for a feature Shape | `plate_of` + `band_of`, loud on failure |

**The prism is one `width` deep and hugs one side of the plate.** A constant
`depth` measured along b = t × N (in the cutting plane, perpendicular to the
path) — or measured normal to the support — put the member's far edge on an
arbitrary second dimension and made the band depend on a number no designer
sets. Both readings are history, measured with the two-sided slab that has
since been replaced; what survives them is the *fact* that a band as wide as
the local chamber is a legitimate shape, and the one-sided prism keeps that
fact without the knob: `band_of`/`drape_cuts_of` take one `width` and one
`mirror_x`, `MirrorX` moves band and footprint together, and `flange_width`
is the feature's only shape parameter.

**`band_of` and `drape_cuts_of` are two views of one prism**, deliberately: the
band occupies exactly the patch the panel gives up, so the two can never both
claim one patch of material (F4). `band_of`'s faces are simultaneously the
member's own skin and the cutter subtracted from the panel — which is the only
way they can match exactly, the reason the member sews to the panel with no gap
and no overlap, and the reason the mesh stays continuous across the join.

**Empty is an answer, not a failure.** A cut that misses the support entirely
(x=700 above, `distToShape` = 160) and a support with no band to give are
different facts, and `member_slab` returns `None` for the second while
`section_chains` returns `[]` for the first. Only the feature layer knows
whether a member that never touches the panel is an error or the point — it may
be a bulkhead bridging an opening — so that judgement is left there rather than
made here.

**`chain_regions` answers in faces, not in chain lengths**, because
`wire_composite_stiffener` reaches: `calc_stack_model(…, width=sweep.web_height)`,
where `width` scales a pitch floor of `max(0.5·pitch, 1.0)` against a `DrapePitch`
clamped to 0.5–20 mm — one clamp away from disabling the foot drape rather than
merely coarsening it — and `validate_composite_wiring`, which drapes the foot
only while `0 < foot_width < 3·web_height`. A bulkhead has no second knob to
carry: its band is `width` deep by construction, so a wired bulkhead would
hand that machinery `FlangeWidth` itself, and the clamp question belongs to
the wiring task, not to this layer.

**`_same_curve` compares curves geometrically, not by `isSame`.** A sewn seam is
*one* edge whose `ancestorsOfType` lists both faces; an unsewn one is *two*
coincident copies, one per face, under different TShapes. `isSame` is exactly
true only when two edges share one underlying `TopoDS_Curve`, so it answers
"distinct" for a pair that is one curve for every purpose that matters here —
`BRepAlgoAPI_Splitter` keys crack detection on exactly that, and known-issue #14
is the same conflation one level down.

## 6. Traceability

Every claim in §2–§3 is either a fact about code in this repository, with a file
and line, or a measurement reproducible by `test_bulkhead_section.py`. Nothing
here is quoted from the input specification.

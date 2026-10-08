# Bulkhead design: the TrimTool gap (2026-02-10)

## Status: implemented (2026-10-08) — parts 1 and 2's core; part 3 stays a non-goal

`BulkheadFP.execute` now honours `TrimTool`: the plate and band faces are
cut by the tool before the feature's Shape and the member record are
built (so the draped shells are built from trimmed faces), the drape cut
surface stays on the uncut support, and a tool that removes a member
part entirely raises with `last_error` recording the trim — pinned by
`TestBulkheadTrim` in `test_bulkhead.py` (trim shrinks plate and band,
untrimmed control crosses the void, trimmed plate never bridges it,
`TrimTool` is live — clearing it restores the full member, whole-member
tools fail loudly). The shell builders' own `_apply_trim_tool` call now
doubles as a no-op re-cut. Part 2's evaluation order note stays
true at the core: the section chain is evaluated against the uncut
support, then the trim cuts the member — so the chain is a fact about
the plate-able stack, never about the cut deck. Part 3 (declaration →
material route) remains with the design tools; `execute()` stays
trim-agnostic to laminate wiring.

## What exists today

- `features/Bulkhead.py` — the Bulkhead FP. Declares a `TrimTool` property
  (line ~95) whose description promises the exact feature: *"Solid cutting the
  plate/band supports before their shells are built... Unset (the default), the
  plate spans the opening as before."*
- `features/StiffenerCompositeShell.py` — `_apply_trim_tool(fp, shape)`
  (line ~454): cuts a member's faces by `fp.TrimTool` before the CompositeShell
  is built. Rings use it (`stiffener.TrimTool = engine_box`).
- `tools/bulkhead_section.py` — `section_chains()`, `plate_of()`, `band_of()`,
  `make_bulkhead()`. `plate_of` correctly refuses to chord an open chain shut
  (closing in space would invent a plate edge the support does not have);
  `make_bulkhead` returns empty plates when the cut never closed, and
  `BulkheadFP.execute` **raises** — the loud-failure contract already holds at
  the core level. Silent plate-dropping exists only on the design-tool side
  (`sections_from_plan()` in the RTOA tree skips `plate=None` with a warning).
- `compositestests/test_bulkhead_section.py`, `test_bulkhead.py` — chain, band,
  smear and feature tests. TrimTool is pinned by `TestBulkheadTrim` in
  `test_bulkhead.py` (four cases: untrimmed control, trimmed member stops
  at the opening, live property, loud whole-member refusal).
- `compositeexamples/examples/bulkhead_section.py` — three sections:
  the section-layer member (un-mirrored and mirrored, footprint cut out of
  the skins), the same shape through the `BulkheadFP` feature, and
  `build_trimmed` — a `BayBox` void with `TrimTool` set, visually
  confirmed in the GUI (trimmed bulkhead red, opening through the plate
  ring).  The example attaches `ViewProviderBulkhead` to its feature
  objects the same way the command path does — a bare `addObject` example
  that skips that attach leaves `ViewObject.Proxy = None`: default part
  feature in the tree, no icon, cannot be enabled for display (that
  defect was seen in the GUI and fixed 2026-10-08).
- `compositeexamples/fixture_bulkhead.py` — the fixture family now also
  serves a **split deck** (`split_fixture`): both loft bands cut against
  half-space boxes either side of the vertical plane y = 0, so the
  support is four unconnected pieces — the situation a real bay has once
  the deck has been cut before the bulkhead is declared.  Pinned in
  `TestSplitSupport` and `TestBulkheadOnSplitSupport`: the section chain
  still closes across the separate pieces; band + footprint = the split
  support exactly (6 dp); the plate's region is unchanged (relative
  1e-6 — two independent boolean constructions of one region differ by
  reconstruction noise, measured 0.0023 mm2 of 21271); the feature
  computes a valid three-dimensional member.  **No product code needed
  changing** — the section machinery was already piece-agnostic; only
  fixture geometry and assertions were added.

## The foot element: cut from the support, absorbing its material

**Essential fact (owner, 2026-10-08), identical for stiffener and
bulkhead — there is no difference between them as far as this is
concerned, and the code has one construction for both.**

A member's foot element (the stiffener's foot, the bulkhead's band) is
**cut from the support's own surface** — `support.common(slab)` for
both (`_foot_bands` in the stiffener's sweep, `band_of` in the
bulkhead's section — one slab construction, two callers).  What the
panel keeps is the same cut's complement (`support.cut(slab)`), so
**foot + remainder = the support, exact by construction, never a
boolean approximation** — asserted at 6 dp in both suites, and the
remainder and foot share their boundary curve data exactly (measured;
that shared curve is what lets the seam machinery accept the joint).

**Material absorption follows, through the same machinery for both:**
the foot shell never runs its own drape solve — it **borrows the
panel's solved drape** (`DrapeSource = panel`; the panel drapes once,
on its uncut support, and its weave runs continuously into the foot).
The foot's stack is the **combined laminate** (the SCL, one flow,
`wire_composite_member`, `BULKHEAD_ROLES`/`STIFFENER_ROLES`): the
panel's directional plies **continue through the foot** — the material
the panel would have laid on that patch of its own surface is *inside*
the member — with the member's own plies on top
(`StackAttachmentOverMaster`; 4 plies on the bulkhead fixture: 2 panel
+ 2 plate).  The fabric on a foot is the panel's weave continued plus
the member's plies — never a fresh weave spliced at the joint.

## The gap (three parts) — closed as of 2026-10-08 above

### 1. `TrimTool` is a dead property on BulkheadFP
`BulkheadFP.execute()` calls
`make_bulkhead(support=fp.Support.Shape, cut_surface=..., ...)` and
`drape_cuts_of(fp.Support.Shape, ...)` — always the **raw, uncut support**.
`fp.TrimTool` is never read anywhere in `execute()`. Setting `fp.TrimTool =
<engine bay solid>` is a silent no-op: the plate spans the opening *and* the
drape rides uncut geometry — identical to `TrimTool` unset. A property that
does nothing is worse than no property: it reads as if the feature existed.
*Closed: execute applies the trim to the member faces before the Shape and
the member record; the test `test_trim_tool_trims_the_member_shells` pins
the shell shrink and `test_trim_that_removes_the_member_fails_loudly` pins
the loud contract.*

### 2. Evaluation order has no home
The correct order for a bay station is **evaluate the section chain against the
full (pre-cut) stack, then cut the resulting plate/band/drape by the bay
solid** — exactly the ring chain (`Rings → TrimTool → Cut`). At x +860 the
chain *closes* on the pre-cut stack (full perimeter ≈1440 mm) but is *open* on
the cut deck (its side segments lie inside the bay void). A prober that probes
the cut deck (as `probe_bulkhead_stations.py --stations 830,860,890` did)
structurally cannot answer "is a plate possible here": the chain there is a
fact about the cut, not about the plate-able stack. Once (1) is wired, the
feature itself answers the question at recompute; until then, probes must run
against the pre-cut stack — that is the design-tool-side note, not a core
change.

### 3. No declaration → material route for bulkheads
A new bulkhead has no station into the FEM assembly: no way to give it its own
mesh group (or join a keyed group) with its laminate card, and its ties must be
re-listed by hand even where `support_for()`-style derivation exists. The
design-tool side (RTOA `ls8e-design-tools/propeller/cad/`) must call the core
feature; the core side just needs to keep `execute()` trim-agnostic to laminate
wiring so one trimmed member can be wired like a ring.

## Required functionality (core only — keep it simple)

1. **Honour `TrimTool` in `BulkheadFP.execute()`** — mirror the stiffener:
   apply the existing `_apply_trim_tool(fp, ...)` to the plate and band faces
   after `make_bulkhead()` returns them and before `Part.makeCompound` /
   `StiffenerSweep` wiring. The drape cut surface stays **uncut** (it rides the
   uncut geometry and the trimmed shells borrow it — as the property
   description already promises). No new geometry kernels; the plate-at-+860
   case (chain closes pre-cut, trimmed by the bay box where the void opens it)
   is then expressible as one member declaration with `TrimTool=engine_box`.
2. **Keep the loud-failure contract** — "chain does not close on the support"
   remains a `ValueError`, never a silent skip; `plate_of`'s refuse-to-chord
   rule is correct and stays.
3. **Tests** (add to `compositestests/test_bulkhead_section.py`, one assert
   per test, boundary cases; do not touch existing thresholds):
   - `TrimTool` unset → plate spans a bay-like void (control, pins the no-op
     fix's boundary);
   - `TrimTool` set to a void solid → plate/band stop at the opening's edges
     (plate area reduced, no material bridges the void);
   - `TrimTool` that severs every closing chain → `execute()` raises
     (loud-failure contract);
   - recompute with `TrimTool` changed after first build → shape updates
     (property is live, not cached).

## Non-goals

No per-station hand-built trims, no bay-specific code in the core, no new
laminate-key machinery in the workbench (material routing lives in the design
tools; the core only needs `execute()` to not ignore `TrimTool`).

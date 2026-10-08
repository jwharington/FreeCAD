# Handover — a generic Bulkhead feature (2026-10-07)

> **Resolution (2026-10-08).** This feature is built and tested — the
> section layer, the feature layer, and the composite wiring are all
> green headless (`test_bulkhead_section`, `test_bulkhead`, plus the
> example suite; the composite flow is shared with the stiffener's).
> Every design fork in §4 is settled; the settlements are recorded
> inline under each fork and in `bulkhead-design.md`, which remains the
> measurement-checked record. Where this handover and that record
> disagree, the design record wins.

**Scope:** a new, purely generic capability for this workbench
(`src/Mod/Composites/…`). No consumer-specific behaviour belongs here or
in this document; whatever downstream scripts eventually call this tool
is a separate task, and nothing in a generic feature may assume a
particular article.

## Contents

1. [The idea in one paragraph](#1-the-idea-in-one-paragraph)
2. [The existing machinery this grows from](#2-the-existing-machinery-this-grows-from)
3. [What must be built — requirements](#3-what-must-be-built--requirements)
4. [Design forks to settle before building](#4-design-forks-to-settle-before-building)
5. [Constraints and lessons already paid for](#5-constraints-and-lessons-already-paid-for)
6. [Verification plan — one support shape, lofted from two ellipse chains](#6-verification-plan--one-support-shape-lofted-from-two-ellipse-chains)
7. [File and test map](#7-file-and-test-map)
8. [Out of scope](#8-out-of-scope)

## 1. The idea in one paragraph

A **bulkhead** is a member that follows the *support* and a *cutting
plane* the way a stiffener does, but its core is **filled**: where the
plane intersects the support, the result becomes a **filled face** — a
plate — and the **flange is then constructed in exactly the same way the
stiffener's foot is constructed**, off that face's boundary. So a
bulkhead = filled plate + foot-style flange, where today a stiffener =
open poly-line section (leg / web / leg) swept along the path, feet
folded onto the support at its ends. Everything the stiffener chain
already solved — composite mode (web shell, foot shell, transfer shells,
common drape, rosettes), `TrimTool` trimming, path extraction from a
support/section intersection — should be *reused or generalised*, not
reimplemented beside it.

Two vocabulary notes, because they keep causing bugs when blurred:

- **Path** — the curve where the cutting surface intersects the
  support; today `tools/stiffener.py:intersection_paths` builds it as a
  `Part.Wire` of the section edges (a chain of true section edges, not a
  point-polyline) that an *open* profile is then swept along. A plane
  that misses the support yields an empty wire list and
  `make_stiffener` raises — silence there is a failure, never a
  default.
- **Foot/flange** — the flat leg folded onto (coincident with) the
  support, built by the foot construction, whose boundary lies on the
  support. A bulkhead's plate boundary plays the role the profile's
  boundary plays for a stiffener: the flange hangs off that boundary
  with the same construction and the same width parameter. 34 mm is a
  *suggestion* — a hand-built starting value, not a requirement — so it
  lives in `flange_width` (or `flange_width/2` measured from either
  boundary), never as a literal.

## 2. The existing machinery this grows from

- `features/Stiffener.py` — `StiffenerFP(CompositePartFP)` and its
  property set (`Support`, `IntersectSurface`, `MirrorX/Y`, `Profile`,
  `Laminate`, `Rosette`, `TrimTool`, `SupportBase`). The `TrimTool`
  property embodies the "geometry-first trim" rule: support faces are
  cut **before** their shells are built; the drape rides the *uncut*
  sweep and trimmed shells borrow it.
- `features/StiffenerCompositeShell.py` — the composite wiring chain:
  `_Web`/`_Foot`/`_PanelFootTransfer`/`_StiffenerFootTransfer`/
  `_CombinedLaminate`/`_Foot_Support`; foot-band pitch warning (20 mm
  default pitch cannot drape a 15 mm flange; sub-millimetre pitch
  drapes nothing). `foot_contact_edge_support` exists because *where* a
  rosette is supported decides the solved angle, and it addresses the
  shell's `Shape.Edges[0]` — a positional element, not an identified
  seam. See §2.1 and F5.
- `features/SeamExtraction.py` (`SeamGeometryFP`, `SeamShellFP`),
  `features/SeamCompositeLaminate.py`, `features/TransferRosette.py`,
  `features/CompositeShell.py` — the **generic stack machinery**
  underneath the stiffener flow: shell class + drape backends
  (`get_boundaries`, `get_lcs`), the transfer-rosette warp-continuity
  solve, and the combined-stack derivation. These are feature-neutral
  and already stack-model aware (`SeamCompositeLaminateFP
  ._input_fingerprint` carries `StackModelType`, `get_model_layers`
  expands the model) — which is why R3 is a *routing* requirement, not
  new code.
- `tools/stiffener.py` — two layers, and they transfer differently.
  **Path layer** (reusable): `intersection_paths`/`_section_groups`/
  `_unique_edges`/`_edges_coincident` (coincident-edge dedupe),
  `generate_intersection_path`, `frames_along`. **Section layer**
  (profile-driven, does *not* transfer): `get_xsect`, `_loft_profile`,
  `_sideways`, `_row_groups`/`_row_for`/`_height_at`,
  `_base_edge_intervals` — all of which presuppose a profile sketch
  with a `y = 0` base row. `ProfileMirror` and `Station` stay useful.
- `docs/investigation-ring-stiffener-web-2026-09-10.html` — the ring
  drape investigation; its conclusions still bind this feature.
- `docs/adr/` and `docs/fem-shell-mesh-continuity.md` — mesh
  continuity rules a filled-face feature must not violate (a plate
  crossing/bridging a support is exactly where coincident-edge and
  section-dedupe bugs live).

A bulkhead is *not* a StiffenerFP with a different profile fed to it.
Two structural reasons, both observable in the current chain:

1. The stiffener's support trimming (`TrimTool`, and the re-pointing
   onto the stiffener remainder) exists to make members **stop at**
   openings. A plate that spans an opening needs the opposite: fill
   across it, keep the boundary consistent, and re-drape nothing.
2. A swept *open* poly-line section and a *filled* section are
   different generators, and only the first exists here. Whether the
   section is closed or open, how deep it stands, and whether flanges
   exist at one or both of its edges are exactly the knobs this feature
   must own as *parameters* — which is an argument for a dedicated
   feature, not for feeding a stiffener a hand-cut section from outside
   the workbench.

### 2.1 What `StiffenerCompositeShell` actually is, and what that costs

`wire_composite_stiffener(host, fp, sweep)` is **feature-agnostic in
shape but stiffener-shaped in naming**. It consumes a partitioned member
through a six-field record (`StiffenerSweep`):

| field | role it plays | bulkhead counterpart |
|---|---|---|
| `shell` | whole member, for the flow fingerprint | plate (+ flange) |
| `remainders` | → `_RemainderSupport` → `SCL.MasterSupport` | same |
| `foot_faces` | faces **lying on** the support → `_Foot` shell, `DrapeSource = panel` | flange band |
| `web_faces` | faces **rising off** the support → `_Web` shell, own drape solve | plate |
| `foot_width` | `_set_pitch(foot_shell, _scaled_pitch(foot_width))` — joint side | flange width (34 → 8.5) |
| `web_height` | `_set_pitch(web_shell, _scaled_pitch(web_height))` — member side | plate stand-off `d` |

(`_scaled_pitch(w) = clamp(w/4, 0.5, 20)`.)

Nothing in that table is about stiffeners; a bulkhead's plate/flange
pair maps onto it one-to-one, which is what R2 means by *reuse*.

Four costs, all discovered by reading the chain rather than assumed:

1. **Name coupling.** Every child object is resolved by string
   concatenation — `_FOOT_OBJECT_SUFFIXES`, `stiffener_claimed_children`,
   `teardown_composite_stiffener`, `ensure_stiffener_shells_visible`,
   `_hide_compound_filters` (`f"{fp.Name}Parts"`/`f"{fp.Name}Remainder"`).
   Reuse means the suffix set becomes an argument (R2), not a second
   module.
2. **`Edge1` is positional, not semantic.**
   `foot_contact_edge_support` addresses `Shape.Edges[0]` of the foot
   shell's support and `SeamShellFP._seam_support_sub` addresses
   `Shape.Faces[0]`. That element decides where the warp-continuity
   residual is measured (see R3/§5). A stiffener foot is a *strip*
   between two rows, so `Edge1` happens to lie on the contact line; a
   bulkhead's flange band has two boundaries (the plate's boundary and
   its outward offset) and — on §6's fixture — may be a compound of
   several faces, where `Edge1` belongs to neither boundary. A *seam
   identification rule* is a requirement here, not an optimisation:
   the seed is picked once, at build time, and nothing re-derives it
   (§5), so a positional guess stays wrong for the life of the file.
3. **Compound-level rosette/LCS placement.** `_build_web_shell` hangs
   one rosette on `Shape.Faces[0]` and `SeamGeometryFP._recenter_lcs`
   re-centres its LCS at the compound's **bounding-box centre**. Both
   are harmless for a connected strip; on a multi-loop or multi-face
   plate the bbox centre can fall in the gap between loops — a rosette
   floating in air, which is how R3's "silent wrong stack" and F1's
   hole test both get lost.
4. **`TrimTool`'s polarity is inverted.** It exists so a member *stops
   at* an opening; a bulkhead plate must *span* one (F4/§6-3).

## 3. What must be built — requirements

- **R1 — Filled intersection.** Given a support and a cutting plane
  (or, generally, a cutting surface), produce the **filled face**
  bounded by their intersection, as the member's core, plus the
  foot-style flange off that face's boundary (default width 34,
  parameterised). One or more closed boundary wires must be handled:
  a plane slicing a doubly curved shell can produce **several** closed
  boundary wires — multi-boundary fill (one face with holes vs one
  plate per loop) is a design fork (F1), not an accident to discover
  mid-run.
- **R2 — Foot-construction reuse.** The flange must be *built by the
  foot construction*, not by a parallel copy of it: the shell/transfer
  wiring, common drape (solved once on uncut geometry, then
  re-draped/restored as today), and `TrimTool`-style trimming of
  support faces before shell extraction must all accept the plate's
  boundary as their seam input. Concretely, that means one
  `wire_composite_member(host, fp, member, roles)` factored out of
  `features/StiffenerCompositeShell.py` — role suffixes and feature
  label as arguments, called by `StiffenerFP` and `BulkheadFP` alike —
  plus a *seam identification* rule replacing the positional `Edge1`
  (§2.1/§5). That extraction **is** this task (no-duplication rule);
  a copy-pasted foot builder is an automatic reject, and so is a
  `tools/bulkhead.py` that reimplements the path layer of §2.
- **R3 — Stack-model parity.** A linked `Laminate`/`Rosette` must
  solve in every `STACK_MODEL_TYPE` (Discrete/Smeared/SmearedCore/
  SmearedFabric) exactly like other shell features. Much of this is
  already paid for: `SeamCompositeLaminateFP._input_fingerprint`
  already hashes the stack model alongside the geometry, and
  `SeamGeometryFP.execute` already hashes shape + pitch + drape source
  + source pitch. So R3 is **a routing requirement** — get the
  bulkhead *through* that chain rather than beside it — and its teeth
  are these: (a) a plate that gets its own shell class or its own deck
  writer silently opts out of that protection, and (b) `DrapePitch` is
  derived from `foot_width`/`web_height`, so a plate whose stand-off
  differs from a stiffener's changes the pitch and therefore re-meshes
  (§5) — that is a study-affecting change, not a cosmetic one.
- **R4 — Deck hygiene.** Anything that names a `*ORIENTATION` card in a
  CalculiX write-out keeps names short (digest-style), and the whole
  class of over-long-name failure is avoidable **by construction**.
  *Provenance to check, not a finding:* the exit −11 attributed to
  69-char names in the FEM plan is **not** corroborated here — the
  stack-model audit (`docs/plan-stack-model-ccx-roundtrip.md`,
  Verification block) records names **within ccx's 80-char limit** and
  leaves the −11 cause *not settled*. Brevity stays the rule because it
  is free; do not design a length check around an unverified number —
  measure, then decide. A dedicated `BulkheadFP` is where to enforce
  brevity: name derived sections and orientation cards from a digest of
  (region, stack, angle), never from `label + region + stack`.
- **R5 — Recompute/restore parity.** Headless `make_bulkhead`-style
  creation + a `BulkheadFP` that survives save/close/reopen
  byte-identically. Two known traps: the `Extension type not set`
  class of restore failure comes from child objects (profiles, seeds)
  that don't rehydrate — so the plate's boundary wires must not become
  dangling document objects; and `SeamGeometryFP.execute`/`Composite
  ShellFP.execute` deliberately **bail out** while a restore is still
  in flight (null `Support.Shape`, or a `Rosette` whose properties are
  not registered yet). A plate that re-drapes must respect that bail
  out rather than raise inside it.
- **R6 — Tests before any consumer.** `compositestests/` first,
  generic fixtures only (see §6). Never weaken a threshold to make a
  test pass; a failing threshold is a bug report about the code or the
  algorithm, and the code gets fixed first.
- **R7 — Reachable from the Composites workbench, not just from
  Python.** The stiffener is a *tool*: command, toolbar/menu slot,
  icon, view provider, and a design record (`docs/stiffener-design.md`
  and `docs/stiffener_composite_shell.md`, both named from their
  module's docstring). A bulkhead is to be delivered the same way, so
  these belong to the feature rather than to dressing:
  1. `CompositeBulkheadCommand(BaseCommand)` in `features/Bulkhead.py`
     carrying `icon`/`menu_text`/`tool_tip`/`sel_args`/`type_id`/
     `instance_name`/`cls_fp`/`cls_vp`. `BaseCommand.Activated` calls
     `cls_fp(obj, **sel)`, so `BulkheadFP.__init__` must accept
     exactly the `sel_args` keys (the stiffener's are `support`,
     `cut_surface`, `profile`), and `IsActive` keys off `sel_args`
     too — the toolbar button's sensitivity *is* the selection filter.
  2. Registration in **two** places: `FreeCADGui.addCommand
     ("Composites_Bulkhead", …)` in `InitGui.py`, **and** the name
     inside `ToolbarGroup.get_command_groups()`'s
     `Composites_StructureTools` `cmdlist`. The toolbar, menu and
     context-menu lists reference *group* names, not command names, so
     registering the command alone leaves it reachable from nothing.
  3. A view provider subclassing `VPCompositePart`, plus
     `BulkheadFP.view_provider_class = ViewProviderBulkhead` — that
     class attribute is what both restore repairs key on (§5).
     `claimChildren` must list the bulkhead's children the way
     `stiffener_claimed_children` does, or the tree shows the plate and
     flange shells loose in the model, and R5's rehydration guarantee
     has nothing to hang on.
  4. `resources/icons/Bulkhead.svg` (generated with Inkscape) and an
     `…_TOOL_ICON` constant beside `STIFFENER_TOOL_ICON` in
     `__init__.py` — `GetResources` and `getIcon` both read that path,
     and `*.svg` is copied/installed by the CMake globs **and
     re-configured only on a CMake re-run**, so a new icon or module
     stays invisible to `build/debug` until CMake re-configures (no
     `CONFIGURE_DEPENDS`). Sync through the dev-skill script, never by
     hand.
  5. `docs/bulkhead-design.md`, written in the same idiom: each tool
     keeps its design record under `docs/` and names it from its
     module docstring (`tools/stiffener.py` → `docs/stiffener-design
     .md`; `features/StiffenerCompositeShell.py` →
     `docs/stiffener_composite_shell.md` + ADR-0002). Write a bulkhead's
     own §-for-§ rather than pasting a predecessor's: those records
     carry *solved geometry* and *measured-defect* inventories, and
     `§4`/`§5` of `stiffener_composite_shell.md` (Combination models;
     rosette analysis at the joint) and of `~/opt/plan-mixed-shell-
     solid-fem.md` (SEA-01..07, then the drape lessons — including its
     5.2, which records the `VPBase.setEdit` fix and says new tool
     smoke tests should run in GUI mode too, not only batch) are
     specific to what came before. The `5/1.2/5` and `4/1.2/4` sections
     and the hand-built `34` there are **stiffener sections** — a
     bulkhead's plate depth and flange width are new parameters (F2/F5),
     so do not read the `34` across as settled.
- **R8 — Verified in GUI mode as well as batch.** `compositestests/`
  runs headless under `FreeCADCmd` (`run-tests.sh`), where
  `GuiUp` is false and `FreeCADGui` may be a stub — so anything that
  only exists with a GUI (the command, the selection filter, the view
  provider, the task-panel / `setEdit` path, the toolbar and menu
  entries) is *untested* by the fast harness. `test_integration_
freecad.py` and `test_compositeexamples.py` already show the two
  acceptable shapes for that gap: stub `FreeCADGui`, or `skipTest`
  when `FreeCAD`/`GuiUp` is absent — and PartDesign, CAM, Part,
  Draft, Materials and Import each keep a `Test<Name>Gui.py` beside
  `InitGui.py`. `Composites/InitGui.py` already appends
  **`"TestCompositesGui"`** (and `__init__.py` appends
  `"TestCompositesApp"`) but **neither module exists anywhere in the
  tree** — the registration points at nothing. Give the bulkhead's
  GUI-path test a real home: either make that name true with a
  `TestCompositesGui.py` that drives the toolbar path, or gate a
  `compositestests/` module on `GuiUp` and keep the headless harness
  asserting the *result* rather than the interaction.

## 4. Design forks to settle before building

> **All settled 2026-10-08 — see each fork's resolution.**

- **F1 — multi-boundary fill.** Plane ∩ support may yield several
  closed wires (a plane crossing a saddle at two depths). Fill as one
  face with inner boundaries, or one plate per loop, or per-face shells
  with shared drape — whichever keeps `nextdrape`'s `IsInsideFace` hole
  test and the mesh-continuity rules intact. Decide with a
  double-curvature fixture, not by luck on a flat plate. Note that all
  three are *already expressible*: a `Composite::Shell`'s Shape is
  `Part.makeCompound(faces)` and `CompositeShellFP` keeps unsewn faces
  unsewn, so this fork is not about the shell chain — it is about
  where the **rosette and LCS land** (§2.1 cost 3) and whether the
  hole test still fires on a face with inner wires.
  *Resolution: one filled face per closed chain (`plate_of`); the
  fixture never produced a multi-boundary section, and open chains are
  skipped, not chorded shut.*
- **F2 — depth and flange measurement.** Is the plate depth d measured
  from the support (total stand-off including the flange legs, so a
  flange as wide as the suggested 34 eats into d) or beyond it (flange
  adds on top)? The
  answer is irrelevant to the generic tool *if* both are reachable from
  the parameters — keep them orthogonal: `depth`, `flange_width`,
  `flange_both_edges?`, `mirror`, `cut_surface`. Two things the code
  forces: `flange_width` is a *band width*, and both pitch scalars are
  derived from it (`_set_pitch`/`_scaled_pitch`, §2.1), so the two
  knobs are not as orthogonal as they look — say which one `d` includes.
  *Resolution: there is no `depth`. The one-sided prism made stand-off
  meaningless; `FlangeWidth` is the feature's only shape parameter and
  feeds both pitch scalars (34 mm → 8.5 mm drape pitch). `MirrorX`
  selects the side.*
- **F3 — one member or per-face segments.** Where the boundary crosses
  several support faces of different local thickness/normal, choose
  between one continuous plate (one `Composite::Shell`, per-face
  normals — a circle path already works this way) and segmented plates
  like the skin regions, with the coincident-edge dedupe (`_unique_
edges`) fed consistently either way. Two unknowns to settle **on §6's
  fixture**, not on paper: whether a band seam that falls *inside* the
  flange band (not on either of its edges) still reads as one seat
  (§2.1 cost 2), and whether a member whose boundary closes in void
  can be solved at all by the mechanism that assumes a seat.
  *Resolution: settled on the fixture — a seam-crossing chain reads as
  one closed chain and the band spanning it comes out multi-face; a
  cut clear of the support produces no chain and fails loudly. The
  member is one plate face per closed chain, no segmentation.*
- **F4 — re-drape interaction and trim polarity.** `TrimTool`'s purpose
  is to make members **stop at** openings; a plate that spans an
  opening needs the opposite (fill across it, keep the boundary
  consistent, re-drape nothing). Copying the property across inherits
  the wrong polarity — if the bulkhead needs trimming at all, it needs
  a different operation, and §6-3 is the test that says which.
  Whatever is chosen, the chain's "drape once on the uncut sweep" rule
  survives into this feature untouched.
- **F5 — flange *band* vs flange *solid*.** A foot band is taken **out
  of the support's own surface** (`support.common(band_slab)`), not
  lofted — that is what makes it coplanar with the panel, keeps weave
  exclusivity exact by construction, and leaves the seam shared with
  the panel so the mesh is continuous. A flange wide relative to the
  band's own curvature need not have a band to take: an offset as wide
  as the suggested 34 — a starting value, not a requirement — measured
  from the plate's boundary can run clean off the surface's edge, or
  cross the band seam into the neighbouring band. So the fork is *band vs
  constant-thickness offset solid* (`plate ∪ flange` closed into one
  shell), and it decides F1/F3 rather than following them. A solid
  keeps the plate's boundary *inside* the member — which is the
  geometry that `fem-shell-mesh-continuity.md` §2 warns about
  *Resolution: band, not solid — `band_of` is `support.common(slab)`,
  exactly the stiffener's `_foot_bands` construction. The wide-band
  edge cases are real and measured: a band wider than the local chamber
  still meets the support, and a band spanning a seam comes out
  multi-face (both pinned in `test_bulkhead_section`); a cut clear of
  the support yields no chain and the feature fails loudly.*
  (references must lie on geometry **in the mesh**), so the mesh
  consequence is part of the fork, not an afterthought.
  *Resolution: the bulkhead takes an optional `TrimTool` with the
  stiffener's polarity — the plate/band support faces are cut by the
  tool before their shells are built, so a bulkhead that must stop at
  an opening stops there; the drape itself is untouched (it rides the
  uncut geometry, and the trimmed shells borrow it), and a tool that
  removes the whole member fails loudly. Unset (the default), the
  plate spans the opening as this fork originally described. The band
  replaces the patch it occupies (F4's exclusivity: band + remainder =
  the support, exactly), and the joint is treated exactly as the
  stiffener's — the plate reads its boundary from the band's own wall
  edge (the stiffener's web-row construction), so the shared curve is
  identical rather than tolerance-matched, and the seam machinery
  accepts the joint: transfers solved, combined stack composed through
  `get_model` (4 plies on the fixture). The re-drape rule stands: the
  panel drapes once, on its uncut support; the footprint is recorded as
  the joint's master-side support.*

## 5. Constraints and lessons already paid for

- Verification against a solved deck goes through the project's frd
  reader (`importCcxFrdResults.importFrd`) and its result-mesh
  convention — result arrays are keyed by (element, integration point)
  against the *expanded* result mesh, and the frd node table numbers
  through-thickness points, not model nodes. A hand-written frd join
  silently plots wrong points and can peak a field where nothing
  physical peaks: one such parser disagreed with the solver's own
  reported maximum while appearing plausible. Trust the reader, not
  regexes.
- **A drape seed is addressed positionally today, and that is a
  standing hazard for a plate.** `foot_contact_edge_support` hands the
  transfer rosette `Shape.Edges[0]` (a boundary *edge* of the shell's
  own Shape, because its U direction is the contact line) and
  `SeamShellFP._seam_support_sub` hands it `Shape.Faces[0]`.
  `TransferRosetteFP` then measures the warp mismatch **at that one
  element** — its length midpoint, or its centre of mass — picked once,
  at build time. `TransferRosetteFP._solve_inputs_fingerprint`, which
  gates `resolve()`, hashes the two shells' shapes plus the rosette
  angles but **not the element address**, and `onChanged` re-solves
  only when the `Support`/`MasterShell`/`AttachmentShell` *links*
  change — re-slicing a same-named support changes neither. So the seed
  is never derived from the joint, only ever taken from element 0, and
  a plate whose boundary is a closed multi-loop wire makes that
  positional choice visible. The
  measured consequence of exactly this, quoted from
  `foot_contact_edge_support`'s own docstring: `atan2(0, 0)` → ±π and a
  solve slope of −0.0012 rad/deg instead of 0.0175 — plausible-looking
  and wrong. A plate with several boundary loops, or a plate whose
  flange band crosses the band seam, lands in the same class —
  identify the contact seam, and if any part of this chain is
  bypassed rather than reused, carry its cache key forward.
- Changing member geometry changes the mesh signature → re-mesh → the
  result set is a new baseline, not a comparison against the old one.
  Any study harness therefore treats "plate members present" as a
  study-affecting change, never a cosmetic one. Expect that to fire
  immediately here: `DrapePitch` is derived (`clamp(width/4, 0.5, 20)`
  off `foot_width`/`web_height`), so a bulkhead's plate and flange
  reach the draper at a pitch its 20 mm default does not describe —
  which is a
  re-mesh by construction, and (per `fem-shell-mesh-continuity.md` §2)
  a section referenced to geometry that is not in the mesh matches
  nothing. F5 is partly a choice about *which* geometry the references
  sit on.
- The workbench's **ViewProvider proxy is serialised as an `int`** (a
  memory address) on save, so after a reopen it is not a Python object
  and — in the module's own words — "icons, claimChildren and task
  panels break, and interacting with those objects in the tree grinds"
  (`CompositeBaseFP.onDocumentRestored`, and the `InitGui.py` repair
  pass that exists for the same reason). Both key on
  `view_provider_class`, which is why every feature declares it.
- **Batch and GUI are not the same path, and neither proves the
  other.** `BaseCommand.Activated` branches on `FreeCAD.GuiUp`: the
  GUI branch also builds the view provider, consults
  `VPCompositeBase.setEdit` (which returns False when `_taskPanel` is
  None, so an inherited-None VP must not be assumed to raise), puts
  the feature in the Composites container and clears the selection;
  the headless branch only does the container add. Headless runs may
  also run against a **stubbed** `FreeCADGui`
  (`compositestests/test_integration_freecad.py`), so a headless pass
  proves nothing about toolbar reachability and a GUI pass proves
  nothing about geometry. Compare *results* (shape, placement, stack
  names) across the two, never structure.
- No environment variables for run-time options (parameters/CLI
  flags only). Imports at module top, never inside functions. Shared
  machinery gets factored into a module both consumers import — a
  second copy of the foot builder is not allowed.
- `src/Mod/Composites/…` is the source of truth; `build/debug/…` is
  only what the app loads — sync via the dev skill's build-install
  script, purge `.pyc` for pure-Python changes, and put examples in
  `compositeexamples/examples/` (executed from the build copy).
- Test-running discipline (fail-fast, focused batches) per the
  `freecad-dev` skill scripts.

## 6. Verification plan — one support shape, lofted from two ellipse chains

> **Added 2026-10-08: a second support variant.** `split_fixture` cuts
> the same loft L/R by the vertical plane y = 0, so the deck is four
> unconnected pieces — the state a real bay has after the deck has been
> cut.  The bulkhead's section chain, band and feature all pass on it
> unchanged (no product code was modified); see `bulkhead-design.md`.

**One support shape for every test and every example:** a **loft
through two chains of elliptical sections** — three or four distinct
semi-axes per chain, the two chains meeting at a shared seam edge, the
whole thing left open-ended so a boundary wire can run off an end.
It is deliberately *not* a flat plate and not a constant-curvature
tube: a plane slicing it can
produce one or *several* closed boundary wires depending on where and
how it cuts, the surface normal and thickness direction vary along the
member, section-dedupe and coincident-edge problems live exactly on
that band seam and the open ends (where a boundary wire can run off
into void), and it is the same class of geometry — doubly curved,
variable normal — the feature must serve in anger. Examples in
`compositeexamples/` and the tests of §3-R6 build *this* shape, from
one helper, then drive bulkheads through it.

1. **Axial cut, single boundary** — a cutting plane roughly normal to
   the loft axis through mid-band: expect one closed boundary wire.
   Assert the plate fills as one face, the flange is built by the foot
   construction (width parameterised, edge count per F2), and record
   **which** F5 answer the implementation took — band out of the
   support's surface, or an offset solid — rather than asserting one as
   if F5 were settled. Assert too that the rosette's supported element
   is the **contact seam**, identified as such, and not `Edge1`/`Face1`
   by position (§5). Then drape solvability, all four stack models, and
   short deck names (R4).
2. **Oblique / second cut, multi-boundary** — tilt the plane (or add a
   second one) until the intersection yields two or more closed wires
   or lands on the band seam and open ends. This settles F1 (fill
   rule), F5 (band vs offset solid) and F3 (continuous member vs
   per-face segments) and — only if the chosen answers leave a face
   with inner wires — runs `nextdrape`'s `IsInsideFace` hole test on a
   doubly curved face; record which of those actually ran. Record *where* the band seam falls
   relative to the flange band — inside it, or on neither edge —
   because that answer, not a flat-plate guess, is what picks F1/F3/F5.
3. **Opening-bridging** — pre-cut an opening in one band so the
   member's boundary crosses it. F4 decides whether the plate *spans*
   the opening or is trimmed by it, so this level asserts whichever
   answer was chosen: if it spans, the fill must cross the opening and
   nothing may re-drape on the trimmed remainder. If a boundary that
   closes in void turns out to be unsolvable by the reused machinery,
   that is an F3/F5 finding to report and re-open — not a tolerance to
   widen and not an assertion to delete.
4. **Reopen test** — save, close, reopen: bulkhead + children restore
   identical (R5).
5. **GUI-path run** — the same shape, built the way a user builds it:
   select support + cutting surface — plus a section object *only if*
   F2's fork resolves to taking one as a selection, since R7's
   `sel_args` must mirror `BulkheadFP`'s constructor; if the section is
   a parameter, select the two objects and set the section in the
   dialog. Then invoke
   `Composites_Bulkhead` from the Structure group, then double-click
   the finished feature. Assert the button was *enabled* by that
   selection (that is what `sel_args`/`IsActive` are), that the view
   returns to model mode afterwards, and that the children are
   claimed in the tree (R7/R8). This one needs a GUI; the four above
   run headless.

Each level before the next; a red fixture means fix the code, per §3
R6. Tolerances and thresholds stay where they are — a red fixture is
the bug report, not the threshold.

## 7. File and test map

- `features/Stiffener.py` — the feature pattern to mirror
  (`features/Bulkhead.py`, `BulkheadFP`, `make_bulkhead`).
- `features/StiffenerCompositeShell.py` — foot/shell/transfer wiring to
  *share or generalise* (extract common pieces, don't fork them). Its
  interface is `StiffenerSweep`'s six fields (§2.1); the naming
  coupling, the positional `Edge1`, the compound-level rosette/LCS
  placement and the inverted `TrimTool` polarity listed there are what
  has to become parameterised before `BulkheadFP` can call it.
- `features/SeamExtraction.py` (`SeamGeometryFP`, `SeamShellFP`),
  `features/SeamCompositeLaminate.py`, `features/TransferRosette.py`,
  `features/CompositeShell.py` — the generic stack machinery *under*
  the stiffener flow (shell class, drape backends, transfer solve,
  combined stack). Feature-neutral and already stack-model aware:
  reuse as-is, and keep the fingerprint guards intact (R3, §5).
- `tools/stiffener.py` — the **path** layer to extend
  (`intersection_paths`, `generate_intersection_path`, `frames_along`,
  `_unique_edges`/`_edges_coincident`); a `tools/bulkhead.py` that
  duplicates *those* fails review. The **section** layer
  (`get_xsect`, `_loft_profile`, `_sideways`, `_row_groups`,
  `_base_edge_intervals`) is profile-shaped and does not transfer:
  `get_xsect` merges repeated vertices and rebuilds each edge as a
  straight `LineSegment`, `_loft_profile`/`_base_edge_intervals` tell
  foot from web by `BASE_ORDINATE_TOLERANCE` (the `y = 0` base row),
  and `_sideways`/`_row_groups` displace rows sideways at an abscissa.
  A filled plate has no base row to key on and no polyline to
  displace, so it needs a new generator beside them, not a call to
  them.
- `InitGui.py` (command registration, the toolbar/menu lists, the
  `_CompositeVpProxyRepair` document observer) + `features/Command.py`
  (`BaseCommand`: `sel_args`, `Activated`, `IsActive`) +
  `features/ToolbarGroup.py` (`get_command_groups`) +
  `features/VPCompositeBase.py`/`features/VPCompositePart.py` (view
  providers, `view_provider_class`, `claimChildren`/`setEdit`/
  `doubleClicked`) + `__init__.py` (`…_TOOL_ICON` paths) +
  `resources/icons/` (SVGs) — the GUI half of the feature, per R7/R8.
- `compositestests/test_ring_frames.py`, `test_ring_foot_split.py`,
  `test_drape_common_with_rings.py`, `test_stiffener_composite_shell.py`
  — closest fixtures to copy *patterns* from for new
  `test_bulkhead*.py`. Their support shape is already an ellipse-loft:
  `lofted_skin_face(sections)` in `compositestests/test_stiffener.py`
  lofts `(station_x, height, width)` ellipses and returns **one**
  BSpline face, and `standalone_station_plane(side, x, normal)` builds
  the centred cutting plane (§5's y-shift trap). §6's shape is two such
  lofts sharing a seam edge with open ends, so extend that helper
  rather than writing a second loft, and note that `SECTIONS` and
  `FRAME_SECTION = 34.0` in `test_ring_foot_split.py` are stiffener
  seat-band values — the source of the suggested 34, not a bulkhead
  precedent.
- `docs/investigation-ring-stiffener-web-2026-09-10.html`,
  `docs/fem-shell-mesh-continuity.md`, `docs/adr/` — read first; they
  constrain what "filled" and "bridging" may do to the mesh.

## 8. Out of scope

- Wiring into any downstream consumer script or product model — this
  document exists so the *generic* feature can be built and tested in
  isolation, on generic fixtures, first.
- Load-case derivation, strength criteria, or any study harness option;
  a consumer will need them, but that begins where this tool's tests
  go green.

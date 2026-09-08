# PRD: SeamCompositeLaminate

## Session onboarding

> **New session? Read this block, then skim §§2–6 before touching code.**

- **Status:** implementation **complete** — all five steps done including GUI verification (commits `59c9cf2771`, `36f9babcc1`, `324e870f7e`, `882df1f03e` + this commit). One new known-issue (#10, drape-cache fast path) recorded; not a regression from this feature.
- **What this is:** `SeamCompositeLaminate` (SCL) replaces the naive virtual laminate on the seam shell with a real combined layup (stack model, solved seam angles, loud failures). Design decisions are all resolved and recorded here + [ADR-0001](adr/0001-seam-angle-analysis-symmetric-transfers.md); terminology lives in [`../CONTEXT.md`](../CONTEXT.md).
- **Key non-obvious decisions** (violating these reintroduces fixed bugs): transfers are *solved*, never copied (§5.2); both sides transfer-solved symmetrically (§5.2); master→seam seeds the weave, attachment→seam is analysis-only (§5.2, ADR-0001); `Symmetry` pinned `Assymmetric` (§6.1); remainder carries the attachment's own laminate (§7); side weaves excluded inside the seam region (§6.3); rosette angle changes must re-solve the drape (§7 fingerprint row).
- **Environment:** edit sources in `src/Mod/Composites/`, run `build-install-freecad.sh` before tests (suites load from the pixi env, not build/debug); new `.py` files need `touch src/Mod/Composites/CMakeLists.txt`; headless VP is `None` — guard all ViewObject access; MCP restarts via `start-freecad-mcp.sh [--kill]`, wait after long example builds.
- **Progress log:** update the checkboxes in §10b as you go; record surprises inline in the step they affect.

| | |
|---|---|
| **Status** | **Implemented** — steps 1–5 complete, GUI-verified (see onboarding block + §10b) |
| **Date** | 2026-07-15 |
| **Related** | `seam-current-analysis.md`, `seam-nextdrape-integration.md`, `seam-nextdrape-implementation.md`, `stiffener-design.md`, `rosette-refactor-plan.md`, [ADR-0001](adr/0001-seam-angle-analysis-symmetric-transfers.md) (symmetric transfer solves), `../CONTEXT.md` (terminology) |
| **Scope** | Stack combination model only (phase 1). Interleave and taper are specified for direction but out of scope. |

## Table of contents

- [1. Problem statement](#1-problem-statement)
- [2. Terminology](#2-terminology)
- [3. Domain model](#3-domain-model)
- [4. Combination models](#4-combination-models)
- [5. Rosette analysis at the seam](#5-rosette-analysis-at-the-seam)
- [6. Feature design](#6-feature-design)
- [7. Relationship to existing components](#7-relationship-to-existing-components)
- [8. Acceptance criteria](#8-acceptance-criteria)
- [9. Test plan](#9-test-plan)
- [10. Out of scope / future phases](#10-out-of-scope--future-phases)
- [10b. Implementation order](#10b-implementation-order)
- [11. Open questions](#11-open-questions)

---

## 1. Problem statement

Where two composite shells are joined by an overlap seam, the seam region
carries the **combined layup** of both sides. Today the workbench can
extract the seam geometry (`SeamExtraction`) and transfer rosettes across
the shared edge (`TransferRosette`), but nothing models the seam region
*as a laminate*: its effective thickness, stacking sequence, per-ply
fibre angles, and equivalent shell section are unknown to downstream
consumers (FEM shell sections, BOM, coverage/texture plans).

`SeamCompositeLaminate` fills that gap: it is a
[`CompositeLaminate`](../features/CompositeLaminate.py) specialization
whose layers are derived from the two laminates meeting at a seam,
combined by an explicit model, with per-ply orientations taken from
rosette/drape analysis at the seam rather than nominal stack angles.

**Modelling-only scope.** The feature is a *derived analysis object*:
it computes the combined stiffness/section representation of A ⊕ B
over the seam region. It does **not** replace A's or B's laminates for
FEM section export, BOM, or manufacturing output over the seam — those
continue to be owned by the side shells. Nothing is trimmed, no plies
are reassigned between sides, and no geometry is cut or overridden.
It exists so downstream consumers that need the *effective* joint
stiffness (e.g. equivalent-section beam/shell models of the joint) can
reference one laminate that represents the combined layup.

## 2. Terminology

Aligned with `seam-nextdrape-integration.md` ("unified model"):

| Term | Meaning |
|---|---|
| **Master** | The shell that stays whole in seam extraction. Informally "A side". Canonical term. |
| **Attachment** | The shell trimmed by seam extraction. Informally "B side". Canonical term. |
| **Seam region (C)** | The overlap surface connecting A and B, produced by `SeamExtraction` (`Seam` output). |
| **Shared edge** | The common edge between the seam region and A (edge A-C), and between the seam region and B (edge B-C). |
| **Combined layup** | The effective laminate of A ⊕ B within the seam region, per the selected combination model. |
| **Effective offset angle** | Relative in-plane rotation between A's and B's rosette frames, evaluated at the seam. |

## 3. Domain model

```
CompositeShell (A)      SeamCompositeLaminate        CompositeShell (B)
  Support ── shared edge ── Seam region (C) ── shared edge ── Support
  Rosette ─┐                  │                                ┌─ Rosette
           ├── rosette analysis at seam ────────────────────────┘
           │                  ▼
           │        effective laminate (layers, angles, thickness)
           └──────────────────┴─────────────────────────────────┘
```

### 3.1 References (inputs)

| Property | Type | Constraint |
|---|---|---|
| `Master` | `App::PropertyLinkGlobal` | Must be a `CompositeShell` (`is_composite_shell`). |
| `Attachment` | `App::PropertyLinkGlobal` | Must be a `CompositeShell` (`is_composite_shell`). |
| `SeamRegion` | `App::PropertyLinkGlobal` | The seam shell (`SeamGeometryFP`, `Composite::Shell`) — kept as an explicit link even though SCL is that shell's `Laminate`; the transfer solves need the seam geometry and explicit links beat tree traversal. |

### 3.2 Structural invariants (validated loudly)

Following the workbench's loud-failure contract — a violated invariant
must leave the feature in an `Invalid`/error state with the reason
recorded, never silently degrade:

1. **Master and Attachment are CompositeShells** — anything else is a
   `TypeError`-class wiring error.
2. **Master shares a common geometric edge with the seam region**, and
   Attachment shares a common geometric edge with the seam region
   (edge-partnership via shape section, as in
   `TransferRosette._shared_edge` — geometric identity, not shared
   topological edges: the seam/remainder pair partitions the attachment
   surface, and the master-side boundary is the master–attachment
   intersection curve). An isolated seam or wrong pairing raises.
3. **The two shared edges are distinct** — A and B must touch the seam
   on opposite/overlapping boundaries, not the same edge.
4. **Both sides have a defined laminate** (non-empty layer list).
5. Geometry queries read the live `Support.Shape` of each shell — the
   `CompositeShell.Shape` snapshot is stale after support moves
   (known-issues #6).

### 3.3 Outputs

| Output | Source |
|---|---|
| Effective layer list (ordered, per-ply material + angle + thickness) | combination model §4, applied to seam-local ply angles §5 |
| `Thickness` | sum of combined plies |
| `StackOrientation` | same machinery as `LaminateFP` (name → display angle map) |
| Per-side seam angle report | rosette analysis §5 (exposed for inspection / task panel) |
| Combined section representation (effective stiffness) | existing `write_shell_section` / `get_materials` machinery, fed the combined layers — **exposed as a derived analysis output, not written as A/B's section** |

The combined outputs are *additive* to the model: A and B keep their
own laminates, sections, and BOM entries over the seam region. A
consumer wanting the joint's effective stiffness references the
`SeamCompositeLaminate` explicitly.

## 4. Combination models

`CombinationModel` enumeration on the feature. **Only `Stack` is in
scope for phase 1.**

### 4.1 Stack (phase 1 — required)

The plies of one side continue over the plies of the other; z-order is
explicit:

- `StackMasterOverAttachment` (**default** — listed first so it is the
  initial value): master's plies sit above the attachment's. Effective
  stack bottom→top: `B₁ … Bₘ, A₁ … Aₙ`. Matches the dominant physical
  story: the master's plies are laid across the seam boundary onto the
  attachment (which is why the master is untrimmed and the attachment
  is cut back).
- `StackAttachmentOverMaster`: mirror image: `A₁ … Aₙ, B₁ … Bₘ`.

Semantics:

- **Ply order within each side is preserved** as defined by that side's
  laminate (bottom→top on its own support).
- **Ply angles are not copied from the nominal stack** — each ply's
  angle in the seam region is its *draped* angle (§5).
- Effective thickness = `t_A + t_B`. Bending stiffness of the combined
  section is computed from the stacked geometry (neutral axis shifts);
  the plain `CompositeLaminate` section writer already handles
  arbitrary stacks once the combined layer list exists.
- Materialisation: the combined `Laminate` is built by cloning each
  side's laminae with `orientation = nominal + transfer_angle(side →
  seam)` — one rigid rotation per side (the stated phase-1
  approximation); thickness and material are untouched. Reference
  surface = the seam shell's support (attachment surface), matching
  the section writer convention elsewhere (no offset modelling in ccx
  output).
- Interlaminar definition: the attachment's top ply starts at the
  attachment's support surface; the master's bottom ply starts at the
  attachment's top-ply surface. No adhesive layer is inserted (a bond
  ply, if wanted, is a future property — see §10).

### 4.2 Interleaved (future)

Alternating plies taken from A and B (`A₁, B₁, A₂, B₂, …`) from the
bottom up, truncating at the shorter side and continuing with the
remainder of the longer side. Requires a deterministic interleave rule
for unequal stack depths and symmetry handling.

### 4.3 Taper (future)

Find the common laminae between A and B (matching material + nominal
angle, within tolerance) and retain them through the seam; the
differing plies run out along a taper profile parameter (run-out
length or ply-drop schedule). This is the scarf-like continuous
transition in `seam-nextdrape-integration.md`. Requires ply-drop
representation in the section writer (currently out of scope there).

## 5. Rosette analysis at the seam

The seam is where two drape solutions meet; ply angles must be
evaluated there, not assumed. Analysis inputs:

- **Side A's rosette** (the shell's `Rosette`, which seeds its drape)
- **Side B's rosette**
- The seam region's shared edges with A and B.

### 5.1 Effective offset angle

The effective offset angle is the in-plane rotation between the master's
and the attachment's fibre frames, measured across the seam:

```
effective_offset = attachment_angle_at_seam − master_angle_at_seam
```

with both angle sources per §5.2. It is a single scalar in phase 1,
evaluated at the transfer solve location; variation along a curved seam
is deferred (texture-plan-style map, future).

### 5.2 Per-lamina angles at the seam

The seam region is treated **symmetrically**: each side's fibre
direction at the seam is obtained by a *solved* transfer of that side's
rosette onto the seam region across their shared geometric edge
(existing `TransferRosette` mechanics: shared-edge detection +
edge-angle solve):

- `master_angle_at_seam`: solved transfer master → seam — this
  transfer rosette also **seeds the seam shell's own drape** (and its
  rendered weave), honouring the master's continuity across the seam
  boundary
- `attachment_angle_at_seam`: solved transfer attachment → seam —
  analysis-only; it translates the attachment's lamina directions into
  the seam's frame evaluated at the attachment's edge (rendered as a
  rosette symbol for inspection, but not seeding the weave)
- per-ply angle for side S's ply *i*:
  `θᵢ = θᵢ,nominal + transfer_angle(S → seam) + seam drape deviation`

The solve is required on both sides: either seam edge may be remote
from its part's rosette, and the drape distortion accumulated between
rosette and edge means a copied rosette angle (the current
`_wire_transfer_rosette_for` behaviour) can misrepresent the fibre
direction at the seam by many degrees. Evaluating either side's drape
"natively" over the seam region is not assumed — the seam is modelled
from both directions alike.

For phase 1, the seam-shell drape deviation from its support geometry
is treated as zero for both sides (developable overlap surface, common
case); the approximation is stated in the output report rather than
hidden.

### 5.3 Wiring rules (lessons already paid for)

- A rosette that drives a drape must be **the shell's own `Rosette`**
  link — the solver mutates its `Angle` and the drape cache is keyed on
  the rosette object. `SeamCompositeLaminate` must not invent side
  rosettes; it reads `SideA.Rosette` / `SideB.Rosette` and raises if
  either is unset.
- Solved angles restore previous values on failure and surface the
  error (`AlignFibreRosette` contract).
- Geometry queries go through `Support.Shape` (stale-snapshot rule,
  known-issues #6).

## 6. Feature design

New file `features/SeamCompositeLaminate.py`, `SeamCompositeLaminateFP`
subclassing `CompositeLaminateFP` for the data model (therefore
`LaminateFP` → the existing stack/section machinery is reused, not
reimplemented), with shell-class **rendering**: the seam region support
is drawn with the `CompositeShell` shader pipeline (see §6.3), so the
view provider composes the shell view-provider behaviour rather than
the plain laminate one.

### 6.1 Additional properties

| Property | Type | Notes |
|---|---|---|
| `Master` | `App::PropertyLinkGlobal` | CompositeShell |
| `Attachment` | `App::PropertyLinkGlobal` | CompositeShell |
| `SeamRegion` | `App::PropertyLinkGlobal` | surface shared edge with both sides |
| `CombinationModel` | `App::PropertyEnumeration` | `StackMasterOverAttachment` (default, listed first), `StackAttachmentOverMaster` (phase 1); `Interleaved`, `Taper` reserved |
| `EffectiveOffsetAngle` | `App::PropertyAngle` (ReadOnly) | §5.1 result |
| `SideAngleReport` | `App::PropertyMap` (ReadOnly) | per-side: rosette angle at seam, per-ply seam angles summary |

The inherited `Layers` property becomes **derived**: phase 1 does not
take user-selected laminae; `execute` composes the layer list from the
sides. Direct `Layers` editing is disabled (read-only status) to keep a
single source of truth.

The inherited `Symmetry` property is **pinned to `Assymmetric` and
hidden**: `LaminateFP` defaults to `Odd`, which mirrors the stack
(`layers + reversed(layers)[1:]`) — silently fabricating a copy of
every ply. The combined stack is a literal record of the physical
layup; symmetrisation is a design activity on the side laminates, not
a transformation of the seam record.

### 6.2 Execute contract

```
execute(obj):
  validate wiring (§3.2)                    → raise loudly on violation
  a_rosette, b_rosette = Master.Rosette, Attachment.Rosette
  master_angle = solve_transfer(master → seam)    # also seeds seam drape
  attach_angle = solve_transfer(attachment → seam)
  effective_offset = attach_angle − master_angle
  angles = {side: per-ply seam angles}      (§5.2)
  layers = combine(side stacks, angles, CombinationModel)   (§4.1)
  feed layers through CompositeLaminate model (thickness, section, BOM)
  on any solver failure: restore prior state, record error, mark Invalid
```

### 6.3 GUI

- No dedicated command initially: `SeamShellFP` creates and wires the
  SCL automatically as part of shell seam extraction (single creation
  path). A `Composites_SeamCompositeLaminate` command can wrap the same
  path later for hand-modelled seams.
- Task panel: combination model choice, side summary (laminate, thickness,
  seam angle report), effective offset angle.
- View provider inherits `ViewProviderCompositeShell`-class rendering:
  the seam region renders like any other `CompositeShell` — custom weave
  shader over its support surface, deferred-pass injection, drape
  visibility controls. Rendering follows the established shell
  conventions: weave injected via the shader path, rosette symbols
  re-raised above it, failures leave the shader detached (visible
  breakage, not a blank overlay).
- **Tree claiming:** every element the extraction creates — the seam
  shell, both solved transfer rosettes, the SeamCompositeLaminate, the
  remainder shell, and the internal supports — is claimed as a child of
  the extraction feature (`claimChildren` backed by the headless-testable
  `seam_claimed_children` helper); nothing it created floats at the top
  level of the document tree.
- **Weave exclusivity inside the seam region:** the seam region shows
  *only* the combined weave. The master's and attachment's weaves are
  not visible inside the seam region — that area belongs to the seam
  shell. This requires the render path to exclude the side shells'
  weave geometry within the seam boundary (trim the injected weave
  geometry along the seam edge — the existing cut-edge injection
  machinery is the first candidate). This decision makes the symmetric
  transfer analysis (§5.2) load-bearing: the side shells' drapes are
  not consulted inside the seam region, so the solved transfers are
  the *only* source of seam angles for both sides.

## 7. Relationship to existing components

| Component | Role in this feature |
|---|---|
| `SeamShellFP` / `SeamExtraction` | creates and wires the `SeamCompositeLaminate` (replacing `_build_virtual_laminate`); assigns it as the seam shell's `Laminate`; assigns the attachment's own laminate to the remainder shell — fixing the current bug where the remainder receives the combined master+attachment stack. Also wires both transfer rosettes (master→seam seeds the weave; attachment→seam analysis-only) via the existing rosette-wiring helper — now **solved**, not copied. `TransferRosette` self-solves per its existing constructor contract; SCL only reads the two solved angles. |
| Migration | on `_sync_virtual_inputs`, a seam shell whose `Laminate` is still a `VirtualLaminateFP` gets a fresh SCL; the orphaned virtual laminate is hidden. Old documents upgrade on the next seam recompute. |
| Seam-shell drape freshness | `SeamGeometryFP.execute` currently skips the drape solve when only the support *shape* fingerprint is unchanged. With solved transfers this is a live staleness bug (angle-only changes would leave a stale weave and stale combined stack). **Decision:** the fingerprint is extended to include the rosette angle and LCS placement, keeping the cheap skip for genuinely unchanged recomputes. |
| `CompositeShell` | A and B; owns rosette, drape solution, laminae |
| `TransferRosette` | mechanics reused for edge-angle solve; `SeamCompositeLaminate` reports the relative angle instead of seeding a shell |
| `CompositeLaminate` / `LaminateFP` | base class: model, section writer, BOM, `StackOrientation` — used here only to *represent* the combined stack, not to own A/B export |
| `TexturePlan` | downstream consumer of a laminate stack (offsets per ply), unchanged |
| Stiffener foot overlaps | primary use case: stiffener plies lapping onto a panel produce exactly this A+B-over-seam configuration |

## 8. Acceptance criteria

1. Given two `CompositeShell`s and their `SeamExtraction` seam surface
   (flat case, 0° fabric), `SeamCompositeLaminate` with
   `StackMasterOverAttachment` produces: combined thickness = tA + tB;
   layer count = nA + nB; order attachment-plies-below-master-plies;
   per-ply angles equal to each side's solved rosette angle at the seam.
2. Switching to `StackAttachmentOverMaster` reverses the two blocks
   without touching per-ply angles.
3. For a 30° offset-fabric example (as in `transfer_rosette.py`), the
   effective offset angle equals the solved transfer angle (± solver
   tolerance) and each ply's seam angle reflects its side's solved
   angle, not the nominal stack value.
4. Violating any §3.2 invariant (wrong type, missing shared edge,
   missing rosette, empty laminate) leaves the feature touched-and-error
   with a recorded message — never a silently wrong stack.
5. The combined section is obtainable via `write_shell_section` and
   produces a valid FEM laminate section (layer count, thicknesses,
   angles round-trip) — as an independent analysis output; A/B section
   export is untouched by the feature's existence.
6. Recompute after moving a side's support updates the seam angles
   (live-`Support.Shape` rule) — no stale geometry.

## 9. Test plan

Follow existing suites (`test_transfer_rosette_scenarios.py`,
`test_align_fibre_scenarios.py`) for structure and the scenario-pattern:
script-built fixtures, explicit VP attachment where needed, loud-failure
assertions.

1. **Stack ordering** — two 2-ply shells, assert combined layer list
   order and thickness for both `StackMasterOverAttachment` /
   `StackAttachmentOverMaster`.
2. **Offset fabric** — 30° fabric on both sides; assert both transfer
   solves (master→seam seeds the weave, attachment→seam analysis-only),
   per-ply seam angles, and `EffectiveOffsetAngle` as their difference.
3. **Wiring failures** — attachment a plain `Part::Feature`; seam not
   sharing an edge with it; a side without rosette; each asserts the
   loud-failure contract (error recorded, previous result not silently
   kept).
4. **Support move** — translate a side's support, recompute, assert
   angle report updates.
4b. **Remainder laminate** — after seam creation, the remainder shell's
   laminate is the attachment's own (not the combined stack).
4c. **Symmetry pinned** — SCL `Symmetry` is `Assymmetric` and hidden;
   combined layer list is not mirrored.
5. **Section round-trip** — combined section → ccx materials/shell
   section → assert layer table.
6. **Example** — `seam_composite_laminate.py` in
   `compositeexamples/examples/`: reuse the `transfer_rosette` bend
   geometry; build the seam, both shells, and the combined laminate;
   runner-contract return dict; one example per document.
7. **Rendering** — the seam region weaves with the custom shader
   (injected support-surface geometry, `_attached` true), rosette
   symbols render above it, and a forced shader failure leaves it
   visibly detached rather than silently blank (loud-failure contract
   applied to the render path). The side shells' weave geometry is
   excluded within the seam boundary (weave-exclusivity rule).

Drape-dependent assertions must hold at more than one drape pitch
(see multi-pitch finding: pitch-dependent regressions are a real
failure mode).

## 10. Out of scope / future phases

- `Interleaved` and `Taper` combination models (enumeration values
  reserved; selection raises "not implemented" loudly).
- Adhesive/bond ply insertion at the interface.
- Ply-drop representation in the section writer (needed for taper).
- Non-developable seam drape deviation (phase 1 uses the rosette
  transfer angle with a stated approximation).
- Multiple seams per side; T-joints with >2 sides.

## 10b. Implementation order

Status conventions: `[ ]` pending · `[~]` in progress · `[x]` done.
Check off sub-items as landed; note surprises inline.

### Step 1 — SCL feature file `[x]`

- [x] `features/SeamCompositeLaminate.py` — `SeamCompositeLaminateFP`
  (subclass `CompositeLaminateFP`; `Layers` derived read-only,
  `Symmetry` pinned `Assymmetric`+hidden, `CombinationModel` enum,
  angle/report outputs, loud-failure execute per §6.2)
- [x] `touch src/Mod/Composites/CMakeLists.txt` (CMake glob is
  configure-time)
- [x] tests: stack ordering (1), symmetry pinned (4c), section
  round-trip (5), wiring failures (3) in
  `compositestests/test_seam_composite_laminate.py` — green (10/10)

  Surprises recorded during implementation:
  - FreeCAD's `doc.recompute()` does **not** re-execute an object
    touched by a plain value change (enum/link-less properties) —
    reference changes must call `fp.recompute()` from `onChanged`,
    guarded to fully-wired states to avoid mid-setup poisoning.
    Non-dependency changes in tests need `enforceRecompute()`.
  - `ReadOnly` property status does not block Python assignment
    (GUI-only) — `Symmetry` is re-pinned defensively in `execute`
    (self-healing), and the test asserts healing, not assignment
    failure.
  - `is_comp_type`-style rosette checks pass `"App::FeaturePython"`
    but rosettes are `Part::FeaturePython` — SCL checks the proxy
    `Type` directly. (`is_transfer_rosette` likely has the same latent
    bug — follow-up.)
  - Taskpanel imports made lazy in `CompositeLaminate.py`,
    `FibreCompositeLamina.py`, `HomogeneousLamina.py` (MatGui is
    GUI-only; the module claims features import headless-safe).

### Step 2 — `SeamShellFP` wiring swap `[x]`

- [x] build SCL instead of `_build_virtual_laminate`; remainder gets
  the attachment's own laminate
- [x] wire both transfer rosettes (solved, not copied): master→seam via
  `TransferRosetteFP`, attachment→seam via new standalone
  `AnalysisTransferRosetteFP` (never hijacks the seam shell's Rosette)
- [x] migration path: old documents' `VirtualLaminateFP` hidden, SCL
  replaces it as the seam shell's Laminate
- [x] the seam shell's `DrapePitch` is scaled to the seam width
  (min(20, width/4)) — the 20 mm default exceeds a 10 mm strip and the
  drape fails at most seed angles
- [x] extraction reads live `Support.Shape`, not the draped shell's
  stale `.Shape` (known-issues #6 trap — draped shells made the
  extraction fail outright)
- [x] tests: remainder laminate (4b), offset fabric (2), support move
  (4), SCL-built-by-extraction — green (14/14)

  Surprises recorded during implementation:
  - `shape_fingerprint` was identity-based (`hashCode`): copied or
    re-wrapped identical shapes changed the fingerprint, so
    resolve-driven re-solves fired spuriously. Now content-based
    (bbox + counts + vertices + surface kinds).
  - `solve_rosette_angle._eval` drove the host drape via
    `doc.recompute()` — but a recompute nested inside another object's
    execute does not re-execute an object touched within the nested
    scope, freezing the draper at the bootstrap angle (residual
    flatlines; the solver returns bracket endpoints). The eval now
    calls `shell.Proxy.execute(shell)` directly — synchronous, no
    recompute-order dependency. This fixes the freeze for every solve
    caller.

### Step 3 — `SeamGeometryFP` fingerprint `[x]`

- [x] fingerprint extended with rosette angle + LCS placement (pulled
  forward: the transfer solves cannot iterate the drape without it)
- [x] test: drape freshness — angle-only change re-solves (covered by
  the offset-fabric and support-move scenarios, which exercise the
  solve→drape→angle chain end to end)

### Step 4 — render path: weave exclusivity `[x]`

- [x] **Approach changed by user decision:** no render-path clipping —
  the attachment shell is re-supported on the remainder geometry, so
  its weave covers only the remainder by construction; the master
  plate ends at the joint line. Each region of the joint (master /
  seam strip / remainder) shows exactly one weave.
- [x] pre-seam attachment geometry preserved in a hidden
  `AttachmentBase` property; all future extractions read it
  (idempotence tested). Init-order trap fixed: `Width`'s onChanged can
  drive the first extraction during `__init__` before later properties
  exist — `AttachmentBase` now registers before the inputs.
- [x] GUI verification via MCP: shader `_attached` ✓, rosette symbols
  above weave ✓, weave exclusivity ✓ (three weaves, continuous 30°
  fabric), recovery after geometry break/restore ✓. Forced-failure
  loudness is PARTIAL: the `_can_use_persisted` fast-path reuses the
  cached weave over an emptied support — recorded as known-issues #10
  (pre-existing fast-path behaviour, not introduced by this feature).

### Step 5 — example `[x]`

- [x] `compositeexamples/examples/seam_composite_laminate.py` —
  coplanar panels at 30° fabric (the extractor's edge-sharing input
  model, per `seam_extraction.py`); runner-contract return dict; one
  example per document
- [x] registered in `registry.py`; `test_compositeexamples` green
  (8/8 — the all-examples smoke test picks it up; the suite's total
  test count is unchanged because it iterates the registry)
- [x] verified headless: both transfers solve to ~30° (offset
  ≈ 0.002°), combined stack = 8 physical plies (4+4) at 30°, attachment
  re-supported on the remainder
- [x] GUI demo + screenshot check — example loads, solves, renders:
  four rosette symbols above three weaves, effective offset ≈ 0.002°,
  combined stack 8 plies at 30°

### 10b.1 Test landing order (tests map to §9 scenarios)

Tests are written per build step, not batched at the end — each step
lands with its verification. All suites run headless first
(script-built fixtures, scenario-suite pattern) and need
`build-install-freecad.sh` before running (tests load Python from the
pixi env, not build/debug).

| Step | Tests landing (§9 scenario) | New file |
|---|---|---|
| 1 | stack ordering (1), symmetry pinned (4c), section round-trip (5), wiring failures (3) | `compositestests/test_seam_composite_laminate.py` |
| 2 | remainder laminate (4b), offset fabric (2) — real solves wired by `SeamShellFP`, support move (4) | extends the same file |
| 3 | drape freshness — angle-only change re-solves (extends 4; regression for the fingerprint fix) | extends the same file |
| 4 | rendering (7) — GUI-only via MCP; shader `_attached`, rosette symbols above weave, weave exclusivity, forced-failure loudness. No headless assertion possible (VP is `None` headless) | GUI checklist, not a suite file |
| 5 | example registered in `compositeexamples/registry.py`; `test_compositeexamples` picks it up automatically (8→9 examples); multi-pitch clause applies to any drape-dependent assertion | registry + example |

The multi-pitch clause applies from step 2 onward: offset-fabric and
support-move assertions must pass at more than one drape pitch.

## 11. Open questions

1. **Resolved:** the seam region is a drapeable `CompositeShell`
   (`SeamGeometryFP`, created by `SeamShellFP`) — the
   `SeamCompositeLaminate` replaces the naive virtual laminate as its
   `Laminate`, and the seam shell owns geometry, rosette wiring, and
   shader rendering (see §6.3, Q1 decision). No plain-surface variant
   is pursued.
2. **Resolved (modelling-only):** the combined laminate does *not*
   replace A/B sections over the seam region for FEM export, BOM, or
   manufacturing. It is a standalone derived object representing the
   combined stiffness; consumers opt in by referencing it. No changes
   to `MouldAnalysis`, BOM, or side-shell section ownership.
3. **Resolved:** `Symmetry` is pinned to `Assymmetric` and hidden on
   the combined stack — the seam record is a literal representation;
   mirroring would fabricate plies (see §6.1).
4. **Open, future phase:** interfacial ply angle tolerance when
   matching "common laminae" (taper model): exact nominal match, or
   solved-angle tolerance window? Deliberately deferred until the
   taper model is designed.

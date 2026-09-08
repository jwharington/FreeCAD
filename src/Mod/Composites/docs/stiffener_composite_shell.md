# PRD: StiffenerCompositeShell — combined layup where a stiffener runs along its support

| | |
|---|---|
| **Status** | Draft |
| **Date** | 2026-07-15 |
| **Related** | `stiffener-design.md`, `seam_composite_laminate.md` (PRD), `adr/0001-seam-angle-analysis-symmetric-transfers.md`, `../CONTEXT.md` (terminology) |
| **Scope** | Phase 1: stack combination model only, discrete base-row foot. Interleave/taper reuse the seam PRD's reserved models. |

## Session onboarding

> **New session? Read this block, then skim §§2–6 before touching code.**

- **Status:** plan complete, **not started** — pick up at Implementation order step 1 (§12).
- **What this is:** the stiffener analogue of `SeamCompositeLaminate` (which
  this document assumes you have read — the domain decisions, the loud-failure
  contract, and the solved-transfer analysis carry over wholesale). The
  stiffener becomes a **StiffenerCompositeShell**: configured with its own
  `Laminate` + `Rosette` (standard Composite::Shell property names), and the
  lap joint where the stiffener runs along its support gets the combined
  stack as its material.
- **Key inherited decisions** (violating these reintroduces fixed bugs):
  transfers are *solved*, never copied; symmetric double transfer per ADR-0001;
  `Symmetry` pinned `Assymmetric`; loud failures with recorded `last_error`;
  modelling-only scope; pitch in the freshness fingerprint; visibility set
  *after* the creating recompute; tree claiming for everything the feature
  creates.
- **Environment:** same as the seam PRD onboarding block (pixi-env installs,
  CMakeLists touch for new files, headless VP guards, MCP restart procedure).

| | |
|---|---|
| **Status** | Draft — plan complete, implementation not started |

## Table of contents

- [1. Problem statement](#1-problem-statement)
- [2. Terminology](#2-terminology)
- [3. Domain model](#3-domain-model)
- [4. Combination models](#4-combination-models)
- [5. Rosette analysis at the stiffener joint](#5-rosette-analysis-at-the-stiffener-joint)
- [6. Feature design](#6-feature-design)
- [7. Relationship to existing components](#7-relationship-to-existing-components)
- [8. Acceptance criteria](#8-acceptance-criteria)
- [9. Test plan](#9-test-plan)
- [10. Out of scope / future phases](#10-out-of-scope--future-phases)
- [11. Open questions](#11-open-questions)
- [12. Implementation order](#12-implementation-order)

---

## 1. Problem statement

A stiffener is a composite laminate laid over a support panel: the two
overlap wherever the stiffener's base runs along the support. Today
(`features/Stiffener.py`, `tools/stiffener.py`) the stiffener is pure
geometry — profile swept along the intersect-surface path, lofted to an
open shell — with **no laminate and no rosette at all**. Neither the
stiffener's own layup nor the joint's effective layup exists in the model.

This PRD adds, in two steps that share one feature:

1. **Stiffener composite configuration** — the stiffener is configured with
   a `CompositeLaminate` and a rosette that define its own structure (the
   plies laid over the swept profile).
2. **Combined layup at the joint** — where the stiffener's base row runs
   along the support, the stiffener's plies and the support panel's plies
   form a lap joint. The combined stack (stiffener-over-panel or
   panel-over-stiffener) is computed exactly as `SeamCompositeLaminate`
   computes a seam joint's, and is **set as the composite material for the
   part of the stiffener that runs along the support** (the base-row faces).

**Modelling-only scope**, as for the seam: the combined laminate is a
derived analysis object representing the joint's effective stiffness. It
does not replace the panel's or the stiffener's laminates for FEM export,
BOM, or manufacturing; consumers reference it explicitly.

## 2. Terminology

Aligned with `../CONTEXT.md` and `stiffener-design.md`:

| Term | Meaning |
|---|---|
| **Support (panel)** | The shell being stiffened; stays whole. Canonical **Master** of the joint (informally "B side" — see §4.1 for the role inversion vs the seam). |
| **Stiffener** | The swept shell laid over the support. Canonical **Attachment**. |
| **Base row** | Profile row at `y = 0` — surface-conformal, hugging the support (`stiffener-design.md`). |
| **Foot strip** | The lofted face(s) generated from the profile's base edges — the part of the stiffener that runs along the support. The joint region. |
| **Web** | Every stiffener face above the base rows (`y > 0`). |
| **Stiffener rosette** | The rosette configuring the stiffener's own laminate frame. |
| **Combined laminate** | The effective stack of stiffener ⊕ panel over the foot strip, per the selected combination model. |

Naming: **`StiffenerCompositeShell`** is canonical (user-decided); the
stiffener's own laminate/rosette links use the standard Composite::Shell
property names `Laminate` / `Rosette` — no `Laminate`-style
invented names.

## 3. Domain model

```
Composite::Shell (support panel)     StiffenerCompositeShell        Composite::Shell (stiffener)
  Support ── base-row edges ── Foot strip (base-row faces) ── profile plies
  Rosette ─┐                        │                              ┌─ Stiffener rosette
           ├── symmetric solved transfers onto the foot strip ──────┘
           │                        ▼
           │        combined laminate (layers, angles, thickness)
           └────────────────────┴─────────────────────────────────┘
```

### 3.1 References (inputs)

| Property | Type | Constraint |
|---|---|---|
| `Support` | link | Composite::Shell with a laminate — the panel side of the joint. (The existing geometry inputs `IntersectSurface` / `Profile` / `MirrorX` / `MirrorY` are inherited unchanged from `StiffenerFP`.) |
| `Laminate` | link | `CompositeLaminate` defining the stiffener's own structure (standard Composite::Shell name). |
| `Rosette` | link | Rosette seeding the stiffener laminate's frame. |

### 3.2 Structural invariants (validated loudly)

All seam-PRD §3.2 invariants carry over (loud failure with recorded
`last_error`; live `Support.Shape` for geometry queries), specialised:

1. **Support is a Composite::Shell with a non-empty laminate.**
2. **`Laminate` is a laminate with a non-empty layer list**;
   `Rosette` is a rosette (proxy-type check — the `is_comp_type` TypeId
   trap documented in the seam implementation). Missing rosette is not a
   failure: the flow **auto-creates** it on the web shell (`Angle = 0`,
   web centroid) and never overwrites a user-linked one — the web face
   it must live on only exists after the first build, so requiring it up
   front would make every first build fail. A *linked non-rosette* is
   the loud failure.
3. **The foot strip exists** — the profile has at least one base edge
   (`y = 0`), so at least one foot face was lofted. A profile with no
   base edge (e.g. a fully lifted section) cannot form a joint and
   raises.
4. **The foot strip shares its boundary edges with the support panel**
   (geometric section, per the seam's shared-edge rule).
5. Geometry queries read live `Support.Shape`.

### 3.3 Outputs

| Output | Source |
|---|---|
| Foot shell child (Composite::Shell on the base-row faces) | §6 — renders the combined weave, carries the combined laminate |
| Effective layer list | combination model §4, seam-local ply angles §5 |
| `Thickness` / `StackOrientation` | existing `LaminateFP` machinery |
| Per-side seam angle report + `EffectiveOffsetAngle` | §5 |
| Combined section (`write_shell_section` / materials) | derived analysis output — additive, never replacing either side's export |

### 3.4 Modes (decided, Q3)

Exactly **two modes**, determined by one question — *is `Laminate`
linked?*

- **Geometry-only** (no `Laminate`): today's behaviour — swept shell,
  remainder, filters; no children beyond that, no weave. A legitimate
  mode (`stiffener-design.md`'s generality requirement), not a
  degradation.
- **Full composite** (`Laminate` linked): web/foot split, both shells,
  combined laminate — and this requires the support to be a
  `Composite::Shell` **with a laminate**; if it isn't, loud failure
  (the joint genuinely cannot be computed).

No middle mode ("stiffener laminate, dumb panel"): it would need
conditional partition logic and serve a speculative case. Partial
wiring fails loudly, per the contract.

## 4. Combination models

The generic stack machinery is reused unchanged; the enum labels are
stiffener-specific for clarity, with the mapping noted:

| Label | Meaning | Generic mapping |
|---|---|---|
| `StackStiffenerOverSupport` (**default**) | stiffener plies above panel plies: bottom→top `P₁…Pₘ, S₁…Sₙ` | `StackAttachmentOverMaster` |
| `StackSupportOverStiffener` | mirror image | `StackMasterOverAttachment` |
| `Interleaved`, `Taper` | reserved, raise loudly | as in the seam PRD |

**The default is inverted relative to the seam feature, deliberately.**
In the seam, the master's plies are laid across the joint (so
master-over-attachment was the physical default). Here the *stiffener's*
plies are laid onto the panel — the physical story is
stiffener-over-support. Keeping the canonical roles (panel = Master by
the "stays whole" rule) while inverting the default stack keeps the
model honest; the enum labels say the physical truth instead of the
role names.

Ply angles are never copied from the nominal stacks: each ply's angle in
the foot strip is its nominal angle plus its side's solved transfer
angle (§5). Interlaminar definition, thickness `t_S + t_P`, and the
no-adhesive rule match the seam PRD §4.1. Reference surface = the foot
strip (coincident with the panel surface), matching the ccx section
writer's no-offset convention.

## 5. Rosette analysis at the stiffener joint

Identical machinery and rules to the seam PRD §5 / ADR-0001, restated
for this geometry:

- **Two solved transfers onto the foot strip**, one per side:
  - `panel_angle_at_foot`: solved transfer support → foot — **seeds the
    foot strip's drape** (and its rendered weave), honouring the panel's
    continuity across the base-row edge.
  - `stiffener_angle_at_foot`: solved transfer stiffener → foot —
    analysis-only; translates the stiffener's lamina directions into the
    foot frame at the stiffener's base edge.
- `effective_offset = stiffener_angle_at_foot − panel_angle_at_foot`,
  single scalar in phase 1, evaluated at the transfer solve location.
- Per-ply angle: `θᵢ = θᵢ,nominal + transfer_angle(side → foot)`, with
  the phase-1 zero-drape-deviation approximation **stated in the output
  report**.
- The solve is required on both sides: either joint edge may be remote
  from its part's rosette, and the stiffener's frame is measured in its
  own profile plane while the foot face lies in the panel plane — the
  fold between them makes copied angles wrong, not just imprecise.
- Wiring rules carried over: a rosette that drives a drape must be the
  shell's own `Rosette` link; solved angles restore prior state on
  failure; geometry queries go through live `Support.Shape`.

## 6. Feature design

The stiffener feature gains composite configuration; the joint gets its
own child shell, exactly as the seam flow gives the seam strip a child
shell.

### 6.1 Properties added to `StiffenerFP`

| Property | Type | Notes |
|---|---|---|
| `Laminate` | `App::PropertyLinkGlobal` | the stiffener's own CompositeLaminate |
| `Rosette` | `App::PropertyLinkGlobal` | the stiffener's frame |
| `FootLaminate` | `App::PropertyLinkGlobal` (ReadOnly-ish, derived) | the `StiffenerCompositeShell` child — combined material for the foot strip |

`StiffenerCompositeShellFP` reuses `SeamCompositeLaminateFP`'s machinery
(validation, combination, angle outputs, loud failures) with
stiffener-side wiring; whether it subclasses directly or the shared parts
are factored out is an implementation choice — the *contract* is
identical (see open questions).

### 6.2 Region split: web shell + foot shell (decided, Q1)

The swept stiffener shell is **partitioned into two Composite::Shell
children**, using the face provenance `make_stiffener` already computes
(loci keys, `surface_rows`):

- **Web shell** — faces above the base rows; Laminate =
  `Laminate`; drape seeded by `Rosette`.
- **Foot shell** — the base-row faces; Laminate = the combined
  `StiffenerCompositeShell`; drape seeded by the solved panel→foot
  transfer.

The fold edge between the two carries the symmetric solved transfers
(ADR-0001): ply continuity across the fold is captured by the transfer
solve, exactly as the seam models continuity across its edge. Weave
exclusivity falls out by construction — three weaves (panel remainder /
foot strip / web), no coincident-weave z-fighting. The stiffener
shell's own shape carries all faces (geometry unchanged, CompoundFilter
parts intact); the *weave render* is partitioned across the two
children.

### 6.2 The foot shell child

- A `Composite::Shell` (`Composite::Shell` type, `SeamGeometryFP`-style
  fingerprint skip extended with pitch + seed, per the seam
  implementation) whose **Support is the foot strip** — the stiffener's
  base-row face(s) — and whose **Laminate is the combined laminate**.
- Base-row face identification: `make_stiffener` already returns
  `surface_rows` (the loci with `key[1] == 0.0`) alongside the lofted
  faces; the foot faces are the lofts whose generating profile edge lies
  at `y = 0` (provenance available in `tools/stiffener.py`'s loci keys —
  no new geometric matching needed).
- `DrapePitch` scaled to the foot width, per the seam lesson (a 20 mm
  default pitch cannot drape a 15 mm flange).
- Visible by default, visibility set *after* the creating recompute.
- The web faces keep the stiffener's own laminate (they are rendered by
  the stiffener shell itself; the foot faces are **excluded from the
  stiffener shell's weave** — the foot shell renders them instead).

### 6.3 Tree claiming, weave exclusivity, GUI

- **Tree claiming:** every element the stiffener feature creates (foot
  shell, foot laminate, transfers, foot support) is claimed via
  `claimChildren` backed by a headless-testable helper, as in the seam
  flow.
- **Weave exclusivity on the panel:** the foot strip is coincident with
  the panel surface — without exclusivity, the panel's weave and the
  foot's combined weave z-fight. The existing **support remainder**
  (which `make_stiffener` already produces — the panel with the
  stiffener cut away) is the mechanism: the panel shell is re-supported
  on the remainder, so the panel's weave is exclusive of the footprint
  by construction, identically to the seam's weave exclusivity. The
  pre-seam panel geometry is preserved in a hidden `SupportBase`
  property driving future recomputes (idempotence).
- **Command:** `Composites_Stiffener` selection order unchanged
  (support, cut surface, profile); the laminate and rosette are linked
  via the property editor (or the task panel, later).
- **Rendering:** the foot shell renders the combined weave via the
  standard shader pipeline; rosette symbols raised above it; failures
  leave the shader detached.

## 7. Relationship to existing components

| Component | Role in this feature |
|---|---|
| `StiffenerFP` / `tools/stiffener.py` | host feature + geometry; gains laminate/rosette properties; `surface_rows` provenance identifies foot faces |
| `SeamCompositeLaminateFP` | reused machinery: validation, combination models, angle outputs, loud failures |
| `TransferRosetteFP` / `AnalysisTransferRosetteFP` | the two solved transfers onto the foot strip (ADR-0001) |
| `SeamGeometryFP` pattern | the foot shell child: fingerprint freshness (pitch + seed), pitch scaling, visibility-after-recompute |
| Support remainder (`make_stiffener`) | weave exclusivity: the panel is re-supported on it |
| `TexturePlan` | downstream consumer of a laminate stack, unchanged |
| FEM / BOM | modelling-only: side sections untouched; the combined section is an opt-in analysis output |

## 8. Acceptance criteria

1. Z-stiffener on a plate (0° fabric): the foot shell exists over the
   base-row face; combined thickness `t_stiffener + t_panel`; layer
   count `n_stiffener + n_panel`; order per `StackStiffenerOverSupport`;
   per-ply angles equal each side's solved transfer angle at the joint.
2. Switching to `StackSupportOverStiffener` reverses the two blocks
   without touching per-ply angles.
3. 30° offset fabric on both sides: both transfer solves present
   (panel→foot seeds the foot weave; stiffener→foot analysis-only);
   `EffectiveOffsetAngle` equals their difference; per-ply seam angles
   reflect the solved angles, not nominal values.
4. A profile with no base edge raises loudly (no joint is possible).
5. Violating any §3.2 invariant leaves the feature touched-and-error with
   a recorded message — never a silently wrong stack.
6. The combined section round-trips through `write_shell_section` as an
   independent analysis output; panel/stiffener section export is
   untouched.
7. Recompute after moving the support or the cut surface updates the
   foot strip and the angles (live-`Support.Shape` rule, extraction
   idempotence via the captured base geometry).
8. The foot weave is exclusive: the panel's weave does not render under
   the foot strip (support-remainder re-support).

## 9. Test plan

Follow the seam suites' scenario pattern (script-built fixtures, headless
first, loud-failure assertions, `build-install-freecad.sh` before
running). Tests land with the build step that makes them runnable (§12).

1. **Foot identification** — Z and L profiles: the foot faces are
   exactly the base-row lofts (`y = 0` provenance).
2. **Stack ordering** — both combination models; combined thickness and
   layer order.
3. **Offset fabric** — 30° both sides; both solves; effective offset as
   their difference.
4. **Wiring failures** — support without laminate; missing stiffener
   rosette; profile without base edge; each asserts the loud-failure
   contract.
5. **Support move / cut-surface move** — foot strip and angles update;
   extraction idempotent via the captured base geometry.
6. **Weave exclusivity** — the panel shell is re-supported on the
   support remainder; idempotent across recomputes.
7. **Section round-trip** — combined section via `write_shell_section`.
8. **Symmetry pinned** — combined layer list is never mirrored.
9. **Example** — `stiffener_composite_shell.py`: Z-stiffener on a plate
   with 30° fabric both sides; runner contract; registered in the
   registry; GUI demo + screenshot check.
10. **Rendering (GUI-only)** — foot shader `_attached`, rosette symbols
    above the weaves, weave exclusivity visible, forced-failure
    loudness.

Drape-dependent assertions hold at more than one drape pitch
(multi-pitch clause), including a pitch-change re-drape on the foot
shell (the DrapePitch fix must cover the foot shell's fingerprint).

## 10. Out of scope / future phases

- `Interleaved` and `Taper` combination models (reserved; raise loudly).
- Adhesive/bond ply at the interface; ply-drop sections (taper).
- Non-developable foot drape deviation (phase-1 stated approximation).
- Multiple stiffeners sharing one panel: each stiffener re-supports the
  panel on its own remainder; composing several stiffeners on one panel
  (sequential remainders) is expected to work but is not a phase-1
  acceptance criterion.
- Blade/T stiffeners with base rows on **both** sides of the web
  (double lap joint): phase 1 handles profiles whose base edges all lie
  on the same support face; two-sided contact is a future phase.
- Curved-profile (non-planar cut surface) foot strips: supported by the
  sweep, but the foot-strip drape analysis inherits the phase-1
  approximation.

## 11. Open questions

1. **Resolved (inheritance):** symmetric double transfer, solved-not-
   copied, master→foot seeds the weave — per ADR-0001. The seam PRD's
   §5.2 rationale (remote rosettes, distortion between rosette and edge)
   applies identically here.
2. **Default stack direction:** `StackStiffenerOverSupport` (stiffener
   plies over panel plies) is proposed as the physical default — the
   layup story of a stiffener is that its plies are laid onto the panel.
   Confirm.
3. **`StiffenerCompositeShellFP` subclassing vs factoring:** reuse
   `SeamCompositeLaminateFP` directly with stiffener wiring, or factor
   the shared machinery (combination, angles, outputs) into a common
   base and keep two thin subclasses? Recommendation: factor minimally —
   shared base `SeamCombinedLaminateFP`, two thin subclasses — so the
   validation invariants (§3.2) can differ cleanly.
4. **The attachment rosette vs the stiffener rosette on the remainder:**
   the panel keeps its own rosette (it drapes the remainder); the
   stiffener keeps `Rosette`. No copies — per the
   remainder-rosette lesson from the seam implementation.
5. **Open, future phase:** interfacial ply tolerance for taper matching;
   two-sided base contact (blade stiffeners).

## 12. Implementation order

Status conventions: `[ ]` pending · `[~]` in progress · `[x]` done.

### Step 1 — stiffener composite configuration `[ ]`

- [ ] `StiffenerFP` gains `Laminate` + `Rosette`
  links; the stiffener shell's plies render from its own laminate
  (weave on the swept shell requires the shell to become a drapeable
  `Composite::Shell` or to carry the shader directly — design decision
  during implementation, leaning on `SeamGeometryFP`)
- [ ] `touch src/Mod/Composites/CMakeLists.txt` for any new file
- [ ] tests: laminate wiring, loud failures on missing links — green

### Step 2 — foot strip + combined laminate `[ ]`

- [ ] base-row face identification via `surface_rows` provenance
- [ ] foot shell child (fingerprint freshness incl. pitch, pitch
  scaling to foot width, visibility after recompute, tree claiming)
- [ ] `StiffenerCompositeShell` built and wired (both solved transfers,
  combination models, angle outputs)
- [ ] tests: foot identification (1), stack ordering (2), offset fabric
  (3), wiring failures (4), section round-trip (7), symmetry pinned
  (8) — green

### Step 3 — weave exclusivity `[ ]`

- [ ] panel re-supported on the support remainder (`SupportBase`
  captured; idempotence tested)
- [ ] tests: re-support + idempotence (6), support/cut-surface move (5)
  — green

### Step 4 — example + GUI `[ ]`

- [ ] `stiffener_composite_shell.py` example; registry; suite green
- [ ] GUI verification via MCP: shader attached, rosettes above weaves,
  weave exclusivity, pitch re-drape, forced-failure loudness (§9.10)

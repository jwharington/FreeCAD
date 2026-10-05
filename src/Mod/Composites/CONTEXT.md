# Composites Workbench — Composite Draping & Laminate Modelling

The bounded context for FreeCAD's Composites module: draping simulation
of fabric over mould surfaces (nextdrape solver), rosette-based fibre
orientation, laminate/layup modelling, seams, and stiffeners.

## Language

### Geometry & mould

**Support**:
The surface a feature is built on (face or compound).
_Avoid_: mould surface, substrate

**CompositeShell**:
A drapeable shell feature: Support + Laminate + Rosette, rendered with
the weave shader.
_Avoid_: panel, shell feature

### Seam joint

**Master**:
The shell that stays whole during seam extraction; informally "A side".
_Avoid_: base, parent, A side (in code and properties)

**Attachment**:
The second side of a lap joint (informally "B side"); in seam
extraction it is the shell trimmed into seam region + remainder.
_Avoid_: flange, secondary, B side (in code and properties)

**Seam region**:
The strip of the attachment surface inside the overlap, bounded by the
parting line and the master–attachment intersection; owned by a
drapeable seam shell (`SeamGeometryFP`).
_Avoid_: overlap zone, seam surface, lap region

**Remainder**:
The rest of the attachment surface after the seam region is cut away.
_Avoid_: leftover, offcut

**Seam extraction**:
The operation partitioning the attachment into seam region + remainder
along the parting line offset by the seam width.
_Avoid_: seam split, overlap trim

### Stiffener joint

**Base row**:
The stiffener profile row at `y = 0` — surface-conformal, hugging the
support.
_Avoid_: bottom edge, base line

**Foot strip**:
The stiffener's base-row faces — the part of the stiffener that runs
along the support, where the lap joint lives. Optional: a profile with
no base extent (no bonding flange) has no foot strip, and the stiffener
degrades to web-only.
_Avoid_: flange (profile-specific), footprint

**Web**:
Every stiffener face above the base rows.
_Avoid_: spine, vertical part

**Web shell / Foot shell**:
The two Composite::Shell children the stiffener is split into — the web
shell carries the stiffener's own laminate, the foot shell the combined
stiffener⊕panel laminate.
_Avoid_: stiffener parts (ambiguous with the CompoundFilter parts)

### Layup & orientation

**Rosette**:
A seeded fibre-orientation frame on a shell; the drape solver mutates
its angle.
_Avoid_: seed, CS

**TransferRosette**:
A rosette whose angle is solved for warp continuity across a shared
geometric edge between two shells.
_Avoid_: edge rosette

**SeamCompositeLaminate**:
The laminate representing the effective combined layup of master ⊕
attachment over the seam region, combined by an explicit model
(stack / interleave / taper). Replaces the naive virtual laminate.
_Avoid_: virtual laminate, seam laminate

### Quasi-isotropic

**Quasi-isotropic (QI) laminate**:
A stack with equal numbers of plies at evenly spaced orientations whose
in-plane response is rotation-invariant; it presents as an isotropic
material and needs no fibre-orientation machinery.
_Avoid_: isotropic laminate (the material is not isotropic — only the
effective response), balanced laminate (necessary, not sufficient).

**Isotropic presentation**:
The collapse of a validated QI laminate into one equivalent isotropic
material, declared on the laminate and computed once — no orientation
field, no per-element lookup downstream. The workbench guarantees the
in-plane (membrane) response only; what the solver does with the
equivalent material is the solver's domain.
_Avoid_: smearing, homogenisation.

**Approximate isotropic presentation**:
A deliberate, separately-declared fallback for *nearly* balanced stacks:
the anisotropy residual is budgeted (small fraction of in-plane
stiffness), recorded visibly, and presented as isotropic anyway.
_Avoid_: quasi-isotropic (a near-QI stack is not QI), advisory mode.

**Drape-dependent operation**:
An operation consuming the drape solution (texture plan, align-fibre
rosette, weave rendering, FEM orientation lookup); undefined on a QI
shell and blocked at command entry.
_Avoid_: draped operation, solver operation.

### Structural verification

Two quantities are near 1, dimensionless, and exact reciprocals of each
other. They are not the same number and they are not interchangeable, and
they fail in opposite directions. Never call one by the other's name.

**Stress exposure factor (SE)**:
Demand over capacity at a point — the failure model's own value at the
applied load. For maximum strain it is the largest ratio of a ply strain
to its design strain. **SE > 1 fails**; the governing value is the
**maximum** over plies, nodes and load cases.
_Avoid_: load multiplier, R, λ, utilisation, "exposure" standing alone
(which of the two is meant is the whole question), safety factor.

**Load multiplier (R)**:
The factor the applied load is scaled by until the first capacity is
reached. **R < 1 fails**; the governing value is the **minimum** over
plies, nodes and load cases. For a load-homogeneous model R = 1/SE
exactly; for a model with linear terms (Tsai-Wu) R comes from a search
and is the reciprocal of nothing.
_Avoid_: exposure, stress exposure factor, exposure factor, margin
(margin is R − 1), safety factor.

**Buckling factor (λ)**:
Already a load multiplier: the eigenvalue *is* the factor on the applied
load at which the structure bifurcates. It sits on the R side of the
line; its exposure form is 1/λ.
_Avoid_: buckling exposure, critical load factor (reads as a capacity),
buckling utilisation.

**Design strain**:
The capacity a failure model compares against — `sxxt`, `sxxc`, `sxy` in
`femresult.failuremodels.default_options`. A strain divided by one is an
SE.
_Avoid_: allowable strain, limit strain.

## Relationships

- A **Seam extraction** consumes a **Master** and an **Attachment**,
  producing a **Seam region** (seam shell) and a **Remainder**.
- The **Seam region** and the **Remainder** partition the
  **Attachment**.
- The **Seam region** carries the **SeamCompositeLaminate** (created by
  the seam extraction); the **Remainder** carries the **Attachment**'s
  own laminate.
- A **SeamCompositeLaminate** combines the laminates of **Master** and
  **Attachment** over the **Seam region**; it models combined stiffness
  only — it does not replace either side's laminate for export.
- A **CompositeShell** is rendered with the weave shader; rosette
  symbols render above the weave.
- For a load-homogeneous failure model (`maximum_strain`,
  `maximum_stress`) SE and R are exact reciprocals, so the same
  decision can be reported either way: governing multiplier
  `min(R_strength, λ)`, governing exposure `max(SE, 1/λ)`.
- **One report line, one side of the reciprocal.** A λ written next to an
  SE is a multiplier beside a demand/capacity ratio, and the smaller
  number stops meaning anything. Convert first — `1/λ` to join SE, `1/SE`
  to join λ — and label which is which.
- Strength yields an R only as 1/SE; buckling yields λ directly. Both
  come from the same applied load vector for the two to be combined at
  all, which is why load delivery is verified per step, not per deck.

## Flagged ambiguities

- **"SeamCompositeShell" / "StiffenerCompositeShell" naming**: resolved —
  the seam feature family is canonically **SeamCompositeLaminate**
  (combined laminate, carried by a seam shell); the stiffener analogue
  (PRD `docs/stiffener_composite_shell.md`) is canonically
  **StiffenerCompositeShell**, configured with the standard
  Composite::Shell property names `Laminate` / `Rosette`. Do not invent
  `StiffenerLaminate`-style property names.

- **"A side / B side" vs "Master / Attachment"**: resolved — same
  concepts. **Master/Attachment is canonical** (properties, code,
  docs); "A/B" is informal prose shorthand. Note the roles are a
  convention per joint, not a fact: for a generic lap joint either
  panel can play master, and the choice decides which surface hosts
  the seam region.
- **"seam"** was used to mean both the seam *region* (a surface/shell)
  and the seam *operation*. Resolved: **seam region** is the geometry;
  **seam extraction** is the operation.
- **"exposure" used for a load multiplier**: resolved — **exposure means
  demand/capacity, nothing else**. Two FreeCAD names return or hold R, the
  multiplier, and are misnomers to be read as such: `femresult.failuremodels
  .calc_stress_exposure_factor`, whose own docstring says "load scale factor
  R", and `femresult.resulttools.add_stress_exposure_factor` with the
  `StressExposureFactor` field it writes — a field whose value of 0.723
  reads as an exposure of 0.723 when the exposure is 1.383. Renaming them is
  a separate change, API and GUI both, not a licence to reuse the word for
  R. The LS8e runner once had the same fault in a dict key (`exposure_min`,
  holding R); it now reports `strain_exposure_max` and `load_multiplier`,
  and a summarizer column holds whichever its source line stated.

- **"utilisation"** is informal for SE, not a third quantity — but the
  same word also labels what `evaluate_failure_criteria` returns
  (tsai_wu, hashin), and those models are *not* load-homogeneous, so they
  have no SE↔R reciprocal. Name which model a number came from.
- **"QICompositeShell"** was raised as a feature type for quasi-isotropic
  shells. Resolved: **no new feature class** — QI is a property of a
  **Laminate**; a QI shell is any shell (Composite::Shell, stiffener
  web, seam/foot shell) whose laminate has the isotropic declaration.
  "QICompositeShell" is informal shorthand only.

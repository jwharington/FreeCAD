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
The shell that is trimmed by seam extraction; informally "B side".
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
along the support, where the lap joint lives.
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

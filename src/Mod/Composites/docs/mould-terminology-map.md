# Mould Terminology Map

**Date:** 2026-07-07  
**Status:** Draft  
**Related research:** `composite-moulds.md`, `multipart-mould-cad.md`

## Why this map exists

The mould work uses a few overlapping terms that need to stay consistent across the UI, helper functions, and the mould-analysis docs. The research notes on composite moulds and multipart mould CAD point to the same core ideas:
- split / parting directions
- parting curves or split lines
- parting surfaces
- mould halves or multipart tooling
- machinability / stock allowances / alignment features

## Terms

| Term | Meaning | Notes |
|---|---|---|
| **PartLine** | The curve where the mould halves meet the source surface | This is the boundary curve implied by split-line / parting-line research terminology. |
| **Parting surface** | The geometric surface extended from the PartLine | This is the object currently represented by the `PartPlane` feature conceptually. |
| **PartPlane** | The theoretical slice that extends outward from the PartLine | The current feature name remains for compatibility, but the intent is parting-surface generation. |
| **Mould** | The split tooling volume around the source shape | In this workbench, the mould is a machining stock / toolpath volume, not a finished part. |
| **Draw direction** | Candidate direction used to decide how the part is split | Matches the research language around parting directions and visibility. |
| **Mould half** | One side of the split mould | Two halves for now; multipart tooling later if needed. |
| **Overlap / stock / clearance** | Extra volume added around the source shape | Needed for real mould machining and toolpath generation. |

## Relationship between terms

1. The **draw direction** is selected or hinted.
2. That direction determines the **PartLine** around the source surface.
3. The PartLine is extended into a **parting surface**.
4. The parting surface is used to generate the split **mould**.
5. The mould is output as two **mould halves** with clearance / stock.

## Research grounding

The research outputs support this structure:
- composite mould practice is centered on parting lines, split lines, flanges, stock, and alignment features
- multipart mould CAD papers treat parting surfaces as first-class geometry
- general mould CAD literature uses draw direction, visibility, pockets, and parting surfaces as the core decomposition model

That means the workbench should keep **PartLine** and **parting surface** concepts visible in documentation, even if some existing command names stay stable for compatibility.

## Compatibility note

The current command and object names do not need to change immediately. The documentation should treat them as follows:
- `Composites_PartPlane` → conceptually a **parting surface** tool
- `Composites_Mould` → split mould generation
- `Composites_MouldAnalysis` → analysis / selection of the best split and parting surface

## Suggested usage in docs

Use these phrases consistently:
- “parting line” or “PartLine” for the boundary curve
- “parting surface” for the generated split surface
- “mould halves” for the split tooling result
- “draw direction” for candidate split direction

Avoid mixing these with unrelated uses of “plane” unless the discussion is about the theoretical slice that extends the line into a surface.

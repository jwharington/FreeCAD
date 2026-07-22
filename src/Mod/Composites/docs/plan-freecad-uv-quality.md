# Plan: FreeCAD Integration — UV Quality (Superseded)

**Date:** 2026-07-15
**Status:** SUPERSEDED. The work this plan scoped is complete; the plan's
specific design (`soft_clamp`, edge-aware UV continuity) was **not** the path
taken and is obsolete. See `plan-priority1-master.md` for what was actually
delivered.

## What this plan proposed vs what happened

- **Edge UV clamping (`soft_clamp`)** — proposed; **not implemented**. The
  requirement was corrected during execution: out-of-grid points need
  *extrapolation* (UV as-if-grid-extended), not clamping. The fix lives in
  `nextdrape/src/KDTreeLocator.cpp` (`evaluateQuad` — bounding rejection
  removed, bilinear basis extrapolates). See G2 in the master plan.
- **Edge-aware quad selection / UV discontinuity reduction** — proposed;
  **not implemented**. UV continuity is handled by the bilinear basis in the
  same `evaluateQuad`.
- **Shader attachment / rendering target selection / transparency model** —
  these *were* implemented (shader renders on the SupportSurface, native
  shape hidden via 'Grid' display mode, BLEND transparency for per-fragment
  alpha). Captured in the master plan's "Shader overlay" section.

For the delivered state, read `plan-priority1-master.md`.

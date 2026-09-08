# Stiffener composite regions: web/foot shell split with weave-exclusive rendering

A composite stiffener is one swept shell (profile edges lofted along the
path), but it carries **two** materials: the stiffener's own laminate on
the faces above the base rows (web), and the combined stiffener⊕panel
stack on the base-row faces (foot) — the lap joint where the stiffener
runs along its support. The swept shell is therefore **partitioned into
two Composite::Shell children** — web shell and foot shell — each with
its own laminate, drape seed, and weave. The fold edge between them
carries the symmetric solved transfers (ADR-0001), which is how ply
continuity across the fold is modelled.

Render ownership follows the split: in composite mode the three weave
shells — panel (re-supported on the support remainder), foot, and web —
render everything between them, and the stiffener's `CompoundFilter`
objects ("Parts", "Remainder") are **hidden**. In geometry-only mode (no
stiffener laminate) the filters render as before and no weave shells
exist.

## Why not one shell with two laminates (considered alternatives)

One stiffener shell draping the whole folded profile was rejected: a
Composite::Shell links exactly one laminate, and the combined stack is
only valid on the foot — the web sits above the panel with no panel
plies under it, so the stack is not spatially uniform. Rendering both
the stiffener's own weave and the combined weave over the coincident
base faces is the exact coincident-weave z-fighting the seam flow
eliminated by splitting surfaces. Keeping the CompoundFilters visible
under the weaves re-introduces the same fight for the same reason.

The filter hiding is the deliberate half of this decision: the filters'
native faces are geometrically identical to the weave shells' supports,
so in composite mode they must not draw at all — the same reason the
seam flow hides its remainder shell. Do not "fix" the hidden filters by
making them visible; in composite mode every visible surface is a weave.

## Related boundary decisions

- **Modes:** geometry-only (no `Laminate` — the documented generic Part
  behaviour of `stiffener-design.md`) or full composite. No middle mode:
  partial wiring fails loudly, because a lap joint against a panel
  without a laminate is genuinely uncomputable.
- **The foot strip is optional:** a profile edited to remove its bonding
  flange (no base edge with extent) degrades gracefully — foot shell and
  transfers dropped, web weave persists — and the joint returns when a
  base edge does. Never raise on a missing foot; raise on a broken
  wiring.

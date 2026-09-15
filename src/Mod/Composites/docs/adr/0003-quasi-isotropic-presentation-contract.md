# Quasi-isotropic laminate presentation contract

A quasi-isotropic (QI) laminate — equal plies at evenly spaced angles —
is isotropic in-plane, so it needs no draping, rosette, or per-element
orientation machinery. We decided that QI presentation is a
**declared, then verified** property of the **Laminate** (two boolean
tiers: exact `IsotropicEquivalent`, enforced to round-off; and
`ApproximateIsotropicEquivalent` for deliberately near-balanced stacks,
admitted only within a coarse residual budget and recorded visibly) —
never inferred from the stack, and never exported as pseudo-isotropic
without passing validation. The workbench's contract **ends at the
exported material**: it validates in-plane isotropy and hands the FEM
solver a plain isotropic material; bending, transverse shear, and
through-thickness behaviour of that equivalent plate are the solver's
domain, so no D-matrix checks exist in the QI path.

## Considered options

- **Bending-residual warnings on the declaration** (rejected): the D
  matrix never leaves the workbench in the QI path, so checking it buys
  nothing; the solver derives bending from the equivalent constants.
- **Advisory tolerance on the exact tier** (rejected): near-misses would
  become invisible systematic errors across the whole solve; an
  approximation must be a named, quantified declaration instead.
- **A dedicated `QICompositeShell` feature class** (rejected): QI is a
  laminate property; shells, stiffener webs, and seam/foot shells all
  inherit it, and a new class would fork every consumer that dispatches
  on `Composite::Shell` — including FEM export, which must stay a
  zero-per-element-query path.
- **Numeric-only admission of any stack that passes the membrane check**
  (deferred, not abandoned): phase 1 additionally rejects core plies —
  a foam-core QI sandwich *is* in-plane isotropic, but its bending is
  dominated by core shear, far from the monolithic isotropic plate the
  export advertises; sandwich presentation deserves its own decision
  with its own export shape.

## Consequences

- QI shell FEM export performs no per-element orientation queries and
  writes `*ELASTIC, TYPE=ISO` + a single-layer section.
- Drape-dependent operations (texture plan, align-fibre rosette) are
  blocked at command entry on isotropic shells; rendering degrades to
  plain colour.
- QI composes through the seam/stiffener combination machinery:
  isotropic ⊕ isotropic = isotropic; any draped side keeps today's
  orientation machinery exactly.
- The declaration flags override `StackModelType` for FEM layer
  generation; ply-level stress recovery is not available on a QI shell
  (accepted trade — the discrete stack record stays on the laminate).

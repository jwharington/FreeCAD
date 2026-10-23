# Feature request: step/soft-step functions in Assembly force laws

**Date:** 2026-10-16 · **Raised by:** the LS8e pylon design work
**Where the MbD force law lives:** `src/Mod/Assembly/App/AssemblyUtils.cpp`
(`getForceFunction` — a raw-string passthrough of the force object's
`TensionFunc`/`TwistFunc`/`ForceX`.. properties) →
`src/3rdParty/OndselMbD/FreeCADMbD/SymbolicParser.cpp` (`intrinsic()`,
~line 359) → `RampStepFunction` / `PiecewiseFunction` / etc.

## The finding (measured, LS8e pylon restraint cable)

We needed a tension-only law for a restraint cable (zero below a taut
anchor distance, stiff ramp above). Two facts, both measured on a real
mechanism (the LS8e pylon, 114-frame sweep, joint reactions checked
against a slack-element baseline):

1. **The step facility already exists in the solver.** OndselMbD's
   SymbolicParser registers `rampstep`, `piecewise`, `spline`,
   `transitions`, and `integral` as intrinsics, and `TensionFunc` is
   passed RAW into that parser. A law written as

       rampstep(rIJ(self), <taut>d, 0d, <taut+50>d, 2500d)

   (RampStepFunction::arguments order: var, x0, y0, x1, y1 — a smooth
   ramp from y0 at x0 to y1 at x1) solves and was verified in-run against
   a slack-element baseline: drift 0.00 N on every joint over the full
   sweep, with the cable slack until the taut length.  It works TODAY,
   through the raw-string passthrough, and is documented nowhere.

2. **Conditionals silently mis-evaluate.** A ternary form
   (`ramp > 0d ? ramp : 0d`) parses and *solves* — but applies the
   tension branch with the condition false: an always-false law
   (`rIJ > 900d ? 1000d : 0d`) still tensioned the cable.  The same
   mis-evaluation reproduced in every run.  Nothing warns; the loads
   simply come out wrong.

## The requests

1. **Document the OndselMbD force-law intrinsics** (`rampstep`,
   `piecewise`, `spline`, `transitions`, `integral`, and the `d`-suffixed
   numeric-literal convention) for Assembly force properties, with the
   argument orders (`RampStepFunction::arguments`: var, x0, y0, x1, y1).
   They are reachable from any `TensionFunc`/`ForceX`/`TorqueX` string
   today and users cannot discover them.
2. **Reject conditionals loudly in force-law strings** — either evaluate
   them correctly or fail the parse at assignment time.  A force law that
   silently mis-evaluates is a correctness hazard: it produced plausible
   solve output with wrong loads.
3. **(Optional) expose the intrinsics in the Assembly ForceObject UI**
   (autocomplete/tooltip on `TensionFunc` etc.), so the step facility is
   discoverable rather than source-diving.

## What we would use it for

Tension-only cables (restraint ties, hold-open tethers) and any
load-vs-position law with a break point — gas struts with end stops,
bump stops, and detent springs.  The LS8e pylon restraint cable
(MIL-W-83420 3.2 mm, taut at full extension, ramping 50 N/mm beyond)
is the driving case; its in-run verification (slack baseline vs law
solve, 0.00 N drift) is the pattern we recommend requiring for any
conditional-capable extension.

## Correction (2026-10-23, measured)

`rampstep` does not evaluate in `TensionFunc` at all — it silently yields
0. On the same saved model, one solve each at the last frame:

| TensionFunc | Joint002 | Joint004 |
|---|---|---|
| `0d` (baseline) | 196.3 N | 1361.4 N |
| `2000d` (constant) | 4786.2 N | 6591.9 N |
| `rampstep(rIJ(self), 0d, 0d, 1d, 2000d)` (must engage at any distance) | 196.3 N | 1361.4 N |

The must-engage rampstep is bit-identical to the zero baseline, while a
constant on the same force moves the loads 4.4/5.2 kN — so the force
element and `rIJ(self)` work and the intrinsic itself is dead. The
"verified, 0.00 N drift" claim in the section above was a vacuous pass:
the cable was slack in both solves, so identical peaks proved nothing
about the law. Constants and linear-in-`rIJ` expressions are the only
observed-working forms. The verification pattern we recommend should
therefore include a must-engage probe (a law that has to be nonzero at
the test pose) before any law is trusted.

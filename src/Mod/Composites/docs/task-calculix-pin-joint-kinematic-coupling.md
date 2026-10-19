# Task: CalculiX support for a real pin joint (6-DOF reference node, kinematic coupling, torsional spring)

**Repo:** `~/opt/FreeCAD` (branch `fem-mixmesh`).
**Consuming study:** the LS8e propeller, `~/Desktop/Projects/RTOA/LS8e/Design/ls8e-design-tools/propeller`
(`cad/propeller/build.py`, the `BladeRootFixed` block in `_build_fem`).

## Why: the boundary condition is currently a weld, and it hides the answer

The propeller's blade root hinges on a brass tube: bore `r = 5 mm`, outer `r = 8 mm`, axis along
`y`, 52 mm long. It is a **pin joint** and, per the owner, **completely free to swing** — zero
restraint about the pin axis.

Today it is modelled with `Fem::ConstraintFixed` over the **whole bore surface**. Fixing x and z
at every node of a cylinder also blocks *circumferential* sliding, so the weld silently removes
the free rotation as well — and it manufactures a strain concentration in the brass. Measured:
brass strain exposure **3.25** (and 16.2 at a coarser mesh, i.e. it worsens with refinement,
which is the clamp's signature, not a material's). Refining the mesh cannot fix it.

What is needed instead:

- a **reference node on the pin axis**, kinematically coupled to the bore (`*COUPLING` +
  `*KINEMATIC`) so the reaction is distributed instead of welded node-by-node;
- that node carrying **rotational DOF**, so rotation about the axis can be *left free*;
- a **soft torsional spring** about the pin axis to remove the otherwise singular rigid-body
  rotation, stiff enough to keep the matrix non-singular and soft enough to be structurally
  irrelevant.

**A free pivot is only admissible if the net moment about the pin axis is zero**, and on this
blade it is not (the pressure's side force is `-103 N` acting out to `r ~ 600 mm`, so of order
tens of N·m). So the spring is not a fudge: it is what lets the solve proceed while exposing
whether the configuration is in equilibrium. **The acceptance test is that the spring's reaction
moment comes out ≈ 0.**

## What exists today (verified in this tree, do not re-derive)

| thing | status |
| --- | --- |
| `*COUPLING` / `*KINEMATIC` writer under `femsolver/calculix/` | **absent** |
| `*SPRINGA` / `*ELEMENT, TYPE=SPRING` in the CalculiX writers | **absent** |
| spring **objects** in FreeCAD FEM | **exist, for Elmer** — `femsolver/elmer/equations/deformation_writer.py`, `elasticity_writer.py`, `femexamples/equation_deformation_spring_elmer.py` |
| `femsolver/calculix/` constraint writers | `write_constraint_*` per constraint type; follow that pattern |
| `*NODE` block | written with **3 DOF** throughout, which is the blocker below |

**The blocker is the DOF count.** A kinematic coupling needs its reference node to carry
rotational DOF; the deck writes 3. So the work is:

1. a way to declare a reference node with 6 DOF in the `*NODE`/`*NODE FILE` output;
2. a constraint object + writer emitting `*COUPLING, REF NODE=<n>, SURFACE=<bore>, CONSTRAINT
   NAME=<c>` and `*KINEMATIC` (use `*DISTRIBUTING` as a mode parameter — the study may want it);
3. a spring on that node's rotational DOF about the pin axis (`*ELEMENT, TYPE=SPRINGA` with a
   two-node element, or an `*EQUATION`/`*MPC` form — pick whichever CalculiX accepts for a
   rotational DOF and say which in the commit message);
4. exposure through the GUI properties the way every other constraint is (an object in
   `femobjects/`, registered in `ObjectsFem.py`, and a `write_constraint_*` in `femsolver/calculix/`).

Reuse the Elmer spring work for the object/property shape; do not invent a second convention.
Do **not** write a new solver; this is writer support only.

## Acceptance tests (all must pass)

1. **A small synthetic case**, not the propeller: a cylinder or plate with a bore, pin-jointed,
   punched through with a load whose moment about the pin is known. Assert the spring's reaction
   moment equals the applied moment analytically. That is the test that the coupling distributes
   correctly and the free rotation is genuinely free.
2. **Rigid-body mode is removed**: with the spring set very soft the solve must complete (no
   singular matrix), and with the spring removed it must fail — proving the spring is doing only
   the job intended.
3. **The deck round-trips**: `*COUPLING`/`*KINEMATIC`/spring cards are present, ccx parses them,
   and a re-import of the frd does not lose the constraint.
4. **The DOF change does not disturb existing models**: the full Fem test suite, plus one deck
   that writes no 6-DOF node, must be byte-identical.
5. **On the propeller** (in the consuming repo, read-only from here):
   `cad/PropellerFem.py --solve --blade-geometry smooth --zones --mesh-max 12.5 --stack Discrete
   --blade ls8-18e-mki-propeller-takeoff-fem.json`, then `cad/check-strain-exposure.py DECK FRD`.
   Success is **two** things: the brass row drops from 3.25 to something small, **and every
   laminate/core row is unchanged** (the coupling must not alter the structure's numbers). If the
   laminate rows move, the coupling is wrong.

## Guardrails

- **Do not touch the propeller repo.** Read it for context only; its files are the consumer.
- **Do not reimplement the mass/load checkers** or anything else in that repo.
- Build and test through `build-install-freecad.sh` and the repo's test targets; **never copy
  files into `build/` or `.pixi/` by hand**.
- Commit incrementally, and put the measured numbers in the commit messages.
- **If the reference-moment test cannot be made to pass, stop and report it** with the numbers.
  A pin that is free in rotation is only valid if its moment balances; if it does not, the joint
  or the load case is wrong and a constraint cannot paper over it.
- Record in `docs/` what CalculiX card form you settled on and why, because the next person will
  need to know whether it was `*SPRINGA`, `*EQUATION` or an `*MPC`, and what its limits are.

## Context the study needs afterwards (not this task)

Once this lands, `build.py`'s `BladeRootFixed` becomes: reference node on the pin axis at mid
length, coupled kinematically to `_bearing_bore_faces(bearing)`, fixed in 5 DOF, free in rotation
about the pin axis, with the spring on that DOF. The propeller's
`cad/HANDOVER-2026-10-19-load-cases-and-why-thickness-stops-working.md` records why the weld had
to go; the study also still needs a **moment-about-the-pin** report in `check-deck-loads.py`
(every face's pressure and the shells' mass are already there) to say whether the side force's
moment is as large as estimated.

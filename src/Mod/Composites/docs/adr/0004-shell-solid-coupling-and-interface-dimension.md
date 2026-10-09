# A mixed shell+solid model is coupled by `*TIE`, never by shared nodes

A model that contains both shell (2D) and solid (3D) elements couples the two
parts through calculated multiple point constraints — `*TIE` between a shell
surface and a solid surface — and **never** by making the two parts share
nodes. The choice of which interface a coupling applies to is made by the
*measure of the interface*, not by the element types involved.

| Interface | Family | Coupling |
|---|---|---|
| face (measure 2) | F | `*TIE`, shell face → solid face |
| edge (measure 1) | E | `*TIE`, shell **edge face** (S3-S6) → solid face |

Both are the same mechanism. There is no second mechanism, and no fallback to
an `*EQUATION` writer unless a later case cannot be expressed as a surface.

## Why shared nodes are excluded (Trap A, and a hinge only for an edge)

The reason is not that a shared node makes a weak joint. It is that a shell
sharing a solid's nodes is **dropped from the deck before CalculiX sees it**.

`FemMesh::getFacesOnly` classifies a face as a shell only when its node ids are
**not** a subset of any volume's. A face-interface shell lies *on* the solid's
face, so its nodes are by construction a subset of the solid's, and the shell
vanishes from the written mesh. Silently: no error, no warning, no shell. That
is Trap A, measured (plan §9.9), and it holds whatever CalculiX would have done
with the coupling.

The hinge question is a separate one, and the common reading of the manual
overstates it. The S8/S8R section says:

> *"Beam and shell elements are always connected in a stiff way if they share
> common nodes. This, however, does not apply to plane stress, plane strain and
> axisymmetric elements."*
>
> *"For an internal hinge between 1D or 2D elements the nodes must be doubled and
> connected with MPC's. The connection between 3D elements and all other elements
> (1D or 2D) is always hinged."*

Read literally, the second sentence would make every shared-node 3D-to-2D
connection a hinge. **CalculiX's own test suite says otherwise, and what decides
it is the measure of the interface, not the element types:**

| Reference case | Interface | Connection cards | Its own objective |
|---|---|---|---|
| `solidshell1` | shared **line** | none — shared nodes | *"hinged connection shell-solid"* |
| `solidshell2` | shared **face patch** | none — shared nodes | *"fixed connection shell-solid"* |

Both are CalculiX reference cases. A shared face patch is therefore **not** a
hinge, and for the face (F) family the case against shared nodes rests on Trap A
alone.

For the edge (E) family the hinge is real: a shell meeting a solid along an edge
shares only that line's nodes — `solidshell1`'s configuration, which CalculiX
itself calls hinged. Trap A does not apply there (the shell's remaining nodes
are off the solid), so the hinge is the reason, and `*TIE` — which carried full
moment at a root edge, within 1.7 % of clamped — is what the coupling is for.

The measured hinge reports nothing: ~2.5e12 magnification in tip deflection
against a fully clamped root, with no error and no warning from CalculiX. A
model coupled that way converges, produces a `.dat`, and is wrong. That silence
is why this decision is written down rather than left to preference.

The merge route is consequently node-disjoint **by construction**.

## Why an edge interface is in scope

The earlier position was that an edge interface could not be coupled at all,
because `*TIE` was believed to be face-only and no `*EQUATION` writer exists in
the tree. Measurement overturned that. A hand-written deck tying a shell's root
**edge face** (S3) to a solid face (S5) carried full moment: the tied root
deflected within **1.7 %** of a root fixed in DOF 1-6 (0.003422 against
0.003366, with the analytic `PL³/3EI` at 0.00381).

So CalculiX is not the blocker. The blocker is FreeCAD's reference→surface
mapping: `meshsetsgetter.get_constraints_tie_faces` supplies
`TieSlaveFaces`/`TieMasterFaces` from faces only, and `write_constraint_tie.py`
writes `elem,S{n}` from a face index. No path turns a selected **Edge** on a
shell into its edge face.

Consequence: the first-choice fix for the E family is to teach reference
resolution to yield a shell edge face (S3-S6) for `*TIE`. That is strictly less
work than adding an `*EQUATION` writer, and it is the option to attempt first.
Until it lands, an E-shaped connection must fail **loudly** — see below.

## Considered alternatives

- **Conformal shared-node coupling.** Rejected. It hides the shell from
  `getFacesOnly` (Trap A), and for an edge interface the connection is hinged by
  design. That a shared *face patch* is not a hinge (`solidshell2`) does not
  save it: the shell is gone from the deck before the coupling matters.
- **Add a `*EQUATION` writer** to couple the shell edge nodes' rotations to the
  relative displacement of the adjacent solid nodes. Correct and general, and
  the classic CalculiX remedy, but now a *fallback*: measurement shows `*TIE`
  already does the job, so this is more work for the same result and is only
  needed if some reference shape cannot be expressed as a surface.
- **Declare the E family out of scope permanently.** Rejected. It was a
  reasonable position while the coupling was believed impossible; it is not
  reasonable now that a deck proving otherwise exists.
- **Merge only the interface nodes.** Not an option at any cost — it re-exposes
  Trap A per face, and for an edge interface it is the hinge above.

## What this obliges the implementation to do

1. Coupling is written as `*TIE` from a shell surface to a solid surface, with a
   position tolerance sized to the mesh, on node-disjoint parts.
2. Element ids must remain unique across dimensions while the shell stays
   node-disjoint from the solid. A merged mesh that accidentally merged
   coincident nodes would silently lose the shell; the merge helper must not do
   it, and a test must assert the shell survives.
3. **A connection that cannot be expressed as a surface must raise.** Since a
   hinge is silent — no error, no warning, a converging answer that is wrong —
   the failure has to be manufactured by the writer, not left to CalculiX. This
   is not defensive coding; it is the only signal available.
4. Result checks must not rely on CalculiX diagnostics to catch a hinge. A
   numerical comparison against an independently built solid model is the only
   detector, which is why the plan's end-to-end case carries one with a
   tolerance stated before the run.

## Related decision: composite sections constrain the element type

A composite `*SHELL SECTION` is accepted only for **S8R and S6** shell elements;
an `S4` composite deck is rejected outright by CalculiX (`Element 2 is not a
S8R nor a S6 shell element`). Measured, not inferred.

This is a separate condition from "the shell elements were written into the
deck" — a linear face mesh is structurally valid in a mixed model but cannot
carry a laminated section. Any code path that treats the two as one condition
will produce a deck that is well-formed and unusable. The shell side of a mixed
model must therefore be S8R or S6 whenever its section is composite, and that
must be asserted rather than assumed.

# FEM meshing of unsewn composite shells — continuity and section matching

**Date:** 2026-09-29 · **Status:** verified against the implementation
(code references below) during the fuselage FEM work.

Multi-face composite assemblies (a draped skin lofted in pieces, a
stiffener ring swept as three strips) are typically **unsewn**: adjacent
faces meet through geometrically coincident but *distinct* topological
edges. `CompositeShell` deliberately does not sew —
`CompositeShellFP` sets `fp.Shape = fp.Support.Shape` verbatim. This is
harmless for draping (the drape works on a lattice) and it is also
harmless for FEM **provided two facts about the FreeCAD FEM pipeline are
known**. Both were verified in the source; neither is folklore.

## 1. Mesh continuity: `CoherenceMesh` merges the junction nodes

Gmsh meshes each face of a compound independently, so unsewn junctions
produce duplicate boundary nodes — a cracked shell model. FreeCAD's Gmsh
mesher removes them by default:

* `FemMeshGmsh` property `CoherenceMesh` **defaults to True**
  (`femobjects/mesh_gmsh.py`, "Removes all duplicate mesh vertices").
* With it on, `femmesh/gmshtools.py` writes `Geometry.Tolerance` (from
  `GeometryTolerance`, default `1e-06`) into the generated `.geo` and
  runs **`Coherence Mesh;`** after meshing — gmsh merges coincident mesh
  vertices, so faces meeting only through coincident edges share one set
  of nodes in the solved model.

Caveat: the merge only succeeds within `GeometryTolerance`. If two
junction curves were *meant* to be continuous but deviate by more than
the tolerance (a blend built without exact continuity, a seam the sweep
left open), the merge silently fails and the crack returns. The fix is
the geometry, never the tolerance. Recommend asserting connectivity
after meshing an unsewn assembly — e.g. check that the nodes on each
junction curve are unique rather than duplicated — so a missed merge
fails loudly instead of producing a plausible-looking but cracked
result.

`sewShape()` (Part) is *not* required for this and should not be added
"for safety": if the mesh relies on `CoherenceMesh`, sewing is redundant
work, and if the assert above fires the underlying geometry is what
needs fixing.

## 2. Section and constraint matching: geometric proximity, not topology

At export time, FEM assigns shell sections (and constraint elements) to
mesh elements through the referenced geometry:

* `FemMesh::getNodesByFace` (`src/Mod/Fem/App/FemMesh.cpp`) selects every
  mesh node lying **on the referenced face's surface, within that
  face's tolerance** — proximity-based, not topological identity.
* `meshtools.get_femelements_by_femnodes_std` then assigns an element
  when **all** of its nodes are in that node set.

Consequence for trimmed geometry: when a mesh is made on geometry that
has been cut or trimmed (e.g. an engine-box cutout through frame rings)
while the section references point at the **uncut** CompositeShells,
matching still works — a trim only removes material, so every node of
every surviving element lies on the uncut surface, and every element
matches its section. There is no strip of sectionless elements at the
cut boundary.

The converse failure is the one to watch: references must lie on
geometry that is actually **in the mesh**. A section referenced to
faces that are not part of the meshed shape matches zero elements —
the export then writes no (or a default) section for them. This was the
defect in the original fuselage FEM scaffolding: the mesh was the
frame-ring compound (no skin in it) while thickness and material
referenced the skin shell.

## Summary for future FEM work on composite assemblies

| Question | Answer |
|---|---|
| Do unsewn shells crack the mesh? | No — `CoherenceMesh=True` (default) merges the duplicate nodes |
| Is sewing (`sewShape`) needed? | No; assert connectivity instead, and fix geometry if the assert fires |
| Do trimmed faces match sections referenced to uncut shells? | Yes — matching is proximity-based (`getNodesByFace`) |
| What actually breaks matching? | Referencing geometry that is not part of the meshed shape |
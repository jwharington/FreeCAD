# `FemMesh::getFacesOnly` — a quadratic mesh query that costs more than the solve

**Date:** 2026-10-09 · **Status:** measured, cause identified, fix applied and
verified. Written up because the cost is invisible from the deck, the tests, or
the GUI — it only shows as wall time, and it was first mis-attributed twice.

## The finding

Writing the CalculiX input for a mixed shell-and-solid model spent **83 % of the
entire runtime inside one C++ call**: `FemMesh::getFacesOnly()`
(`src/Mod/Fem/App/FemMesh.cpp:841`). On the mixed wing (core + two skins,
~35.4 k nodes, ~1.8 k volumes) that single call ran for roughly six minutes.

It is reached from the deck writer, not from meshing:

```
write_inp_file               (femtools/ccxtools.py:389)
└─ get_mesh_sets             (femmesh/meshsetsgetter.py:270)
   └─ get_element_sets_material_and_femelement_geometry   (:1083)
      └─ get_element_geometry2D_elements                  (:957)
         └─ get_femelement_faces_table  (femmesh/meshtools.py:207)
            └─ FemMesh::getFacesOnly()  ← 83 % of all samples
```

`get_femelement_faces_table` reads `femmesh.FacesOnly` on line 207, which is the
only statement there that costs anything.

## Why it is quadratic

For every **face**, the code loops over every **volume**, and for each such pair
it rebuilds containers from scratch (`FemMesh.cpp:863-905`):

1. `getElementNodes(aVol->GetID())` → a fresh `std::list<int>`;
2. `std::set<int> aVolNodes(vnodes.begin(), vnodes.end())` → a fresh red-black
   tree of that volume's nodes;
3. `std::set_intersection(...)` into a `std::vector<int>`;
4. `std::set<int> intersection_nodes` → **another** fresh tree, built from that
   vector, purely to compare against the face's set.

So with *F* faces and *V* volumes the volume node sets are rebuilt *F* times —
`O(F·V)` allocations, not `O(F·V)` comparisons. The author's own note at
`FemMesh.cpp:854` says as much:

> *"This means it is iterated over a lot of volumes many times, this is quite
> expensive! TODO make this faster"*

The predicate is a **membership** test, not a geometric one: a face "belongs to
a volume" when its node ids are a subset of that volume's. That is the test
Trap A depends on (see `plan-mixed-shell-solid-fem.md`, §8.3), so it must be
preserved exactly — a face that is a subset but not a boundary face is still
"not faces-only" by this definition.

`FemMesh::getEdgesOnly()` (`:910`) has the identical structure over edges ×
faces and was fixed the same way.

## How it was measured

Two tools, because the two halves need different instruments.

1. **Stage wall time** — `compositestests/inspect_wing_pipeline_cost.py`
   (`run-script.sh`). It separates the stages that fail differently: geometry,
   each drape, each part's gmsh run, the merge, the deck write, the ccx solve.
2. **Function-level attribution** — `py-spy record --format raw` over the same
   pipeline, aggregating exclusive (leaf) samples. `py-spy` *launching* the
   process is required rather than attaching: `kernel.yama.ptrace_scope` is 1
   here, which forbids attaching to a process this shell did not start.

One stage table, one real solve path, after the fixes below:

| stage | s | share |
|---|---|---|
| geometry (core + two skin supports) | 0.14 | 0.0 % |
| drape.upper / drape.lower | 26.20 / 25.89 | 13.6 % |
| fem setup (sections, loads, ties) | 0.04 | 0.0 % |
| mesh.gmsh core / upper / lower | 1.61 / 0.89 / 0.82 | 0.9 % |
| mesh.merge | 0.53 | 0.1 % |
| **deck.write** | **286.56** | **74.8 %** |
| **solve.ccx** | **26.56** | **6.9 %** |
| results.load | 14.00 | 3.7 % |
| **TOTAL** | **383.26** | |

**Writing the deck costs 10.8x the solve.** Generating the mesh (gmsh) and
merging it are together 1 % of the run, so the suspicion that mesh *handling*
dominates was right in substance and wrong in location: it is the deck write,
which builds node and element sets out of the mesh, that dominates.

Function level, 43,727 samples:

| samples | share | leaf |
|---|---|---|
| **36,243** | **83 %** | `get_femelement_faces_table` (`meshtools.py:207`) |
| 6,943 | 16 % | `_run_solve` (`drape_backend_nextdrape.py:525`) |
| 285 | 0.7 % | `objecttools.run` |
| rest | <1 % | |

So the suspicion that mesh *handling* dominates the solve was right in
substance, but the location was not where it looked: gmsh is 3.5 s and the
merge 0.5 s, together about 1 % of the run. The mesh *query* is the wall.

## The fix

Hoist what is invariant out of the loop, and replace the intersection-set dance
with the subset test it is emulating:

* build every volume's node set **once**, before the face loop;
* per face, test membership with `std::includes` over the two sorted sets,
  which is what `aFaceNodes == intersection(aVolNodes, aFaceNodes)` computes —
  no vector, no second tree, no comparison of containers;
* stop at the first volume that contains the face, as before.

The predicate is unchanged, so no deck may change. That is the invariant the
verification below checks.

## Verification, and what the fixes actually bought

* **Deck snapshot unchanged** — `run_inspect_deck_snapshot.py --check` reports
  *no deck changed and no example moved*, so the predicate still selects the
  same faces on all 42 generated decks. This is the check that matters: the
  whole risk of touching `getFacesOnly` is reclassifying a face.
* **FEM suites green** — `femtest.app.test_mesh` and the mixed matrix, 51/51.
* **Measured, not assumed**, with the same cost tool after each change:

| change | effect |
|---|---|
| `getFacesOnly`/`getEdgesOnly` linear instead of rebuilding sets per pair | that function's samples 36,243 → 4,945 (−86 %) |
| element sets scanned once per getter instead of three times | deck write 459 s → 292 s |
| per-element set names hashed to 20 characters | the wing solves at all |
| `get_femelements_by_femnodes_std` membership against a set | **no measurable effect**: 292 s → 286 s |

That last row is recorded because it was wrong. The profile put 13 % of samples
there and the quadratic membership test looked like the cause; it is not. The
cost in that function is walking the whole element table once per geometry
reference, which no change to the membership test can address.

## A third defect, found only because the deck write finally finished

Once the deck was written in a reasonable time, CalculiX rejected it outright:

    *ERROR reading *NSET/ELSET: set name too long

The per-element `*ELSET` name appended an element id to a concatenation of
material, shell and thickness identifiers and reached **82 characters**;
CalculiX allows 80 (manual, *NSET/ELSET). FreeCAD checked the base name, and the
writer then appended `_21604` to it, which is how a name that passed the check
still arrived over the limit. The prefix is now hashed to 20 characters with the
element id kept — md5, not `hash()`, which is salted per process and would make
decks irreproducible.

Two things follow from that, and both are worth keeping. First, this defect was
invisible until two performance defects in front of it were fixed: the model had
never once been solved, and nothing said so. Second, the numbers in the table
above are for a model that now runs for the first time, so treat any earlier
figure for "the solve" as having measured nothing at all.

## Two other costs found on the way, both real, neither the wall

* **`merge_femmeshes` was quadratic in Python** (`femmesh/meshtools.py`): it
  indexed `mesh.Nodes[id]` inside a per-node loop, and `FemMesh.Nodes` is a
  getter that builds a dict of every node — so each lookup rebuilt the whole
  map. 12,588 samples on the lookup line against 36 on the `addNode` beside it.
  Hoisting the getter out of both loops fixed it; the merge went from never
  finishing to 0.49 s.
* **The wing's mesh was 11× finer than intended**, because
  `MeshSizeFromCurvature` (12 elements per 2π radians) refines independently of
  `CharacteristicLengthMax` and the NACA 2412 nose radius is only 3.2 mm. The
  core meshed to 294,917 points instead of 21,332. `mesh_parts_separately`
  gained a `curvature_size` argument and the wing passes 0.

Neither was the dominant cost, and each was briefly mistaken for it. That is
the argument for measuring by stage *and* by function before optimising
either.

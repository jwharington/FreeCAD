# Seam Extraction — Current Implementation Analysis

## Architecture Overview

The seam extraction system is a three-layer pipeline:

```
UI Command → FreeCAD Document Object → C++ Solver → Part.Shape Results
```

---

## Layer 1: Python Bridge (`tools/seam_extraction.py`)

Thin Python layer between FreeCAD and the C++ solver.

### Public API

```python
def extract_seam(master, attachment, seam_width=10.0) -> dict
```

**Returns:**
| Key | Type | Description |
|-----|------|-------------|
| `success` | `bool` | Whether extraction succeeded |
| `error` | `str` | Error message on failure |
| `seam` | `Part.Shape \| None` | Extracted seam surface |
| `remainder` | `Part.Shape \| None` | Remaining attachment geometry |

### Helper Functions

- **`_import_extractor()`** — Lazy-imports `Composites_drape.extract_seam` (C++ module). Avoids import-time dependency on the compiled module.
- **`_ensure_shape(obj)`** — Normalises inputs: accepts `Part.Face`, `Part.Shape`, or any object with a `.Shape` attribute. Raises `TypeError` otherwise.
- **`_decode_brep(brep_bytes)`** — Writes BREP bytes to a temp file and reads via `Part.read()`, producing a `Part.Shape`. This is the transport mechanism for TopoDS_Shape data crossing the C++/Python boundary.

### Data Flow

```
Part.Face / Part.Shape / Object.Shape
        ↓  _ensure_shape()
    TopoDS_Shape (via TopoShapePy cast)
        ↓  C++ solver
    BREP bytes (serialized TopoDS_Shape)
        ↓  _decode_brep()
    Part.Shape (via Part.read from temp file)
```

---

## Layer 2: FreeCAD Feature Objects (`features/SeamExtraction.py`)

Two document object types depending on input complexity.

### `SeamExtractionFP` — Basic Part Objects

For plain `Part::Feature` inputs (faces, compounds without laminate data).

**Properties:**
| Property | Type | Direction | Description |
|----------|------|-----------|-------------|
| `Master` | `App::PropertyLinkGlobal` | Input | Master surface (face or compound) |
| `Attachment` | `App::PropertyLinkGlobal` | Input | Attachment surface (face or compound) |
| `Width` | `App::PropertyLength` | Input | Desired seam width (default "10.0 mm") |
| `Seam` | `App::PropertyLink` | Output | Extracted seam surface (read-only) |
| `Remainder` | `App::PropertyLink` | Output | Remaining attachment geometry (read-only) |

**Behavior (`execute`):**
1. Calls `extract_seam()` with master, attachment, and seam width.
2. On success, creates two `Part::Feature` children: `{Name}_SeamSurface` and `{Name}_Remainder`.
3. Sets `Seam` and `Remainder` properties to reference them.

### `SeamExtractionShellFP` — Composite Shell Objects

For `CompositeShell` inputs — adds laminate awareness.

**Additional properties (inherited from CompositeShell):**
- `Support` — Support geometry for the seam surface
- `Laminate` — Virtual laminate created from the seam result
- `Rosette` — Propagated from master or attachment

**Behavior:**
1. `_sync_virtual_inputs()` — Called on recompute:
   - Runs `extract_seam()` on master/attachment.
   - Creates a hidden `Part::Feature` support with the seam shape.
   - Builds a `VirtualLaminateFP` from the attachment's laminae, tagged with the seam name.
   - Links `Support`, `Laminate`, and `Rosette` properties.
2. `execute()` — Delegates to `_sync_virtual_inputs()` on recompute.

### `VirtualLaminateFP`

A synthetic `LaminateFP` stored on the seam result. Contains the laminae layers copied from the attachment, enabling downstream composite analysis without requiring the original laminate object.

### `ViewProviderSeamExtraction`

Custom view provider inheriting from `VPCompositePart`. Claims no children (children are managed separately). Displays the `SEAM_TOOL_ICON`.

When the input is a composite shell, the view provider is replaced with `ViewProviderCompositeShell` for richer visualisation.

### `CompositeSeamExtractionCommand`

The UI command activated from the toolbar/menu.

**Workflow:**
1. Checks selection: requires exactly one master and one attachment.
2. Dispatches:
   - Both inputs are `CompositeShell` → `_create_shell_extraction()` → `SeamExtractionShellFP`.
   - Otherwise → `_create_part_extraction()` → `SeamExtractionFP`.
3. Adds result to the Composites container.
4. Clears selection and recomputes.

---

## Layer 3: C++ Solver (`App/CompositesDrape.cpp` + `nextdrape/SeamOverlapSolver`)

### Python Binding (`Composites_drape.extract_seam`)

Located in `App/CompositesDrape.cpp` alongside the `solve` (drape) function.

```cpp
m.def("extract_seam", [](py::object master_obj, py::object attachment_obj, double seam_width)
    → py::dict { success, error, seam, remainder });
```

**Unwrapping:** Uses the standard FreeCAD pattern — `static_cast<Part::TopoShapePy*>` on the PyObject, giving zero-copy access to `TopoDS_Shape`.

**Serialization:** Outputs use `BRepTools::Write` into an `ostringstream`, then `py::bytes()` to transfer BREP data to Python.

### `SeamOverlapSolver::Solve()` — Core Algorithm

**File:** `src/3rdParty/nextdrape/src/SeamOverlapSolver.cpp`

#### Step 1: Face Collection

Extracts all `TopoDS_Face` from both the master and attachment compounds.

#### Step 2: Shared Edge Detection

For each (master_face, attachment_face) pair:
- Iterates edges of both faces.
- Matches edges via `EdgesAreIdentical()`:
  1. `edgeA.IsPartner(edgeB)` — for sewn/shared topology.
  2. Endpoint coincidence check — both endpoints within tolerance (1e-6), allowing reversed orientation.
- Deduplicates: when master == attachment (same compound), processes each unordered pair once (`mi <= ai`).

#### Step 3: Joint Wire Construction

Collects all shared edges into a single `BRepBuilderAPI_MakeWire`.

#### Step 4: `BuildSeamSurfaceInternal()` — Boolean Pipeline

Given an attachment face, joint wire, and seam width:

1. **`CreateCircularExtrusion(jointWire, attachmentFace, seamWidth)`:**
   - Gets the surface normal at the midpoint of the attachment face.
   - Computes the spine tangent from the joint wire's first edge.
   - Creates a circular cross-section perpendicular to the spine tangent.
   - Sweeps the circle along the joint wire via `BRepOffsetAPI_MakePipeShell`.
   - Sewing: adds end-cap faces (simulated via `pipeBuilder.Simulate()`), sews tube + caps into a closed shell.
   - Converts shell to solid via `BRepBuilderAPI_MakeSolid` + `BRepLib::OrientClosedSolid()`.
   - Result: a solid cylindrical tube along the joint boundary.

2. **Boolean Cut 1:** `attachmentFace - extrusion → remainder`
   - Uses `BRepAlgoAPI_Cut` with fuzzy value 1e-3.
   - Result: attachment face with the tube region removed.

3. **Boolean Cut 2:** `attachmentFace - remainder → seam`
   - Subtracting the remainder from the original attachment yields the seam geometry (the part that overlapped with the tube).

#### Step 5: Fusion

Results from all face-pair extractions are fused together via `FuseShapes()` (sewing-based union) into `m_seam` and `m_remainder`.

---

## Geometric Result

| Output | Description |
|--------|-------------|
| **Seam** | Cylindrical tube surface along the shared edge boundary. Represents the overlap zone. |
| **Remainder** | Attachment face with the tube region subtracted. The "remaining" attachment geometry after seam extraction. |

### Visualisation

```
    Master (A)              Attachment (B)
    ──────────             ───────────────
                          │███████████│ ← Seam (cylindrical tube)
                          │░░░░░░░░░░░│ ← Remainder (cut face)
                          └───────────┘
```

The seam is a **cylindrical pipe shell** whose radius equals `seamWidth`. The remainder is the attachment face minus that pipe.

---

## Current Capabilities

| Feature | Status |
|---------|--------|
| Lap joint (A over B) | ✅ Implemented |
| Single-face inputs | ✅ Supported |
| Compound inputs | ✅ Supported |
| Composite shell inputs | ✅ Supported (with virtual laminate) |
| Stacking order reversal (B over A) | ❌ Not implemented |
| Scarf joint (tapered transition) | ❌ Planned, not implemented |
| Material property gradient mapping | ❌ Not implemented |
| Seam width parameterisation | ✅ Implemented (default 10.0 mm) |

---

## Known Limitations

### BREP Transport via Temp File

The Python bridge (`_decode_brep()`) writes BREP bytes to a temporary file and reads them back via `Part.read()`. This works but has drawbacks:
- Filesystem I/O overhead on every solve.
- Race condition risk in multi-threaded contexts (mitigated by `mkstemp` uniqueness).
- Could potentially use `Part.readBytes()` directly for zero-disk transfer.

### Debug Logging in C++

The solver contains extensive `std::cerr` debug logging (pipe build, sewing, solid creation). This is useful during development but should be guarded behind a compile-time or runtime flag for production use.

### No Stacking Order Control

The current algorithm always treats the first face as the attachment and cuts the tube from it. There is no parameter to reverse the stacking order (attachment over master vs. master over attachment).

### No Scarf Joint Support

The planned scarf joint (tapered transition with continuous property gradient) shares the same geometry foundation but requires:
- Tapered surface extrusion instead of circular pipe.
- Property interpolation across the overlap zone.
- G1 continuity at boundaries.

---

## File Reference

| File | Role |
|------|------|
| `tools/seam_extraction.py` | Python bridge layer |
| `features/SeamExtraction.py` | FreeCAD document objects & command |
| `App/CompositesDrape.cpp` | C++ pybind11 bindings |
| `3rdParty/nextdrape/include/nextdrape/SeamOverlapSolver.hpp` | Solver header |
| `3rdParty/nextdrape/src/SeamOverlapSolver.cpp` | Solver implementation |
| `resources/icons/Seam.svg` | Toolbar icon |

---

*Last updated: 2026-07-14*
*Aligned with current codebase (C++ solver via nextdrape)*

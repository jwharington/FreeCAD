# Composites Workbench

Composite laminate draping and FEM analysis integrated into FreeCAD.

## Quick Start

### Prerequisites

- FreeCAD built with `BUILD_COMPOSITES=ON` and `BUILD_FEM=ON`
- CalculiX (`ccx`) installed and on PATH
- Gmsh or Netgen mesher installed

### Running Examples

Three shell geometry examples are provided, each demonstrating the full
draping → FEM pipeline:

| Example | Geometry | Draper |
|---------|----------|--------|
| `conical_panel_segment` | Open conical frustum (60° arc) | ⚠️ Singularity at apex |
| `cylindrical_panel_segment` | Closed cylindrical arc (90°) | ✅ Reliable |
| `tubular_shell` | Tubular shell | ✅ Reliable |

#### From FreeCADCmd (headless)

```bash
cd build/pixi-debug   # or your FreeCAD build directory

# Mesh only (no solver) — fast, good for geometry iteration
FreeCADCmd -c "
import sys
sys.path.insert(0, 'Mod')
from Composites.compositeexamples import runner
result = runner.run('cylindrical_panel_segment', run_solver=False,
                    debug_options={'skip_view_providers': True})
print('Shell:', result['feature_stack']['shell'] is not None)
"

# Full pipeline — draping + mesh + CalculiX solve
FreeCADCmd -c "
import sys
sys.path.insert(0, 'Mod')
from Composites.compositeexamples import runner
result = runner.run('cylindrical_panel_segment', run_solver=True,
                    debug_options={'skip_view_providers': True})
fem = result['fem_job']
print('Analysis:', fem['analysis'] is not None)
print('Failure index:', fem['failure_report'].get('max_failure_index', 'N/A'))
"
```

> **Note:** For solver runs, FreeCADCmd's `-c` flag may terminate silently
> on long calculations. If this happens, write the script to a file and invoke
> it directly:
>
> ```bash
> cat > /tmp/run_example.py << 'EOF'
> import sys
> sys.path.insert(0, "Mod")
> from Composites.compositeexamples import runner
> result = runner.run("cylindrical_panel_segment", run_solver=True,
>                     debug_options={"skip_view_providers": True})
> print("Done:", result["fem_job"] is not None)
> EOF
> FreeCADCmd /tmp/run_example.py
> ```

#### From the FreeCAD GUI

1. Open FreeCAD with the Composites workbench enabled
2. Open the Python console (View → Panels → Terminal)
3. Run the example interactively:

```python
import sys
sys.path.insert(0, "/path/to/FreeCAD/build/<config>/Mod")
from Composites.compositeexamples.examples.cylindrical_panel_segment import create_cylindrical_panel

doc = create_cylindrical_panel()
# The composite shell, laminate, and draped mesh are now in the document
# Toggle the Grid display mode to see fibre orientation:
shell = doc.getObject("CompositeShell")
shell.ViewObject.DisplayMode = "Grid"
shell.ViewObject.ShowRosette = True
```

### Custom Examples

To create your own example, copy one of the existing examples and modify:

```python
# src/Mod/Composites/compositeexamples/examples/my_custom_panel.py
from ._shell_example_common import (
    create_composite_feature_stack,
    create_support_feature,
    ensure_document,
    make_demo_laminate,
    run_full_shell_job,
    import_geometry_modules,
    largest_face,
)

GEOMETRY = {
    "radius_mm": 100.0,
    "height_mm": 200.0,
    "arc_deg": 90.0,
}

BOUNDARY_CONDITIONS = {
    "support": "Fix both straight longitudinal edges",
    "load": "Apply uniform pressure normal to the surface",
}


def build(doc=None, run_solver=False, debug_options=None):
    opts = debug_options or {}
    doc = ensure_document(doc, "MyCustomPanel")
    laminate = make_demo_laminate()

    FreeCAD, Part = import_geometry_modules()
    if FreeCAD and Part:
        # Create your support geometry here
        shell_like = Part.makeCylinder(
            GEOMETRY["radius_mm"],
            GEOMETRY["height_mm"],
        )
        midsurface = largest_face(shell_like)
        support = create_support_feature(doc, "MySupport", midsurface)

    feature_stack = create_composite_feature_stack(
        doc,
        support,
        name_prefix="MyPanel",
        skip_view_providers=bool(opts.get("skip_view_providers")),
    )

    fem_job = None
    if run_solver:
        fem_job = run_full_shell_job(
            doc,
            support,
            case_id="my_custom_panel",
            boundary_conditions=BOUNDARY_CONDITIONS,
            solve=not bool(opts.get("mesh_only")),
            shell_obj=feature_stack.get("shell"),
        )

    return {
        "doc": doc,
        "laminate": laminate,
        "support": support,
        "geometry": GEOMETRY,
        "analysis_setup": BOUNDARY_CONDITIONS,
        "feature_stack": feature_stack,
        "fem_job": fem_job,
    }
```

Register the example in `registry.py`:

```python
EXAMPLE_MODULES = {
    ...
    "my_custom_panel": "composites.compositeexamples.examples.my_custom_panel",
}
```

Then run it:

```bash
FreeCADCmd -c "
import sys; sys.path.insert(0, 'Mod')
from Composites.compositeexamples import runner
result = runner.run('my_custom_panel', run_solver=True,
                    debug_options={'skip_view_providers': True})
"
```

## Architecture

```
compositeexamples/
├── examples/
│   ├── _shell_example_common.py   ← Shared helpers (DO NOT EDIT)
│   ├── conical_panel_segment.py   ← Conical frustum example
│   ├── cylindrical_panel_segment.py ← Cylindrical arc example
│   └── tubular_shell.py           ← Tubular shell example
├── registry.py                    ← Example registration
└── runner.py                      ← Example runner API
```

### Key Components

- **`_shell_example_common.py`** — Shared utilities used by all shell examples:
  - `create_composite_feature_stack()` — Creates laminae, laminate, LCS, and CompositeShell
  - `run_full_shell_job()` — Creates FEM analysis, mesh, constraints, and runs CalculiX
  - `make_demo_laminate()` — Quasi-isotropic [0/45/-45/90] laminate definition

- **`runner.py`** — Public API for running examples:
  ```python
  from Composites.compositeexamples import runner
  result = runner.run("example_id", run_solver=True, debug_options={...})
  ```

- **`registry.py`** — Maps example IDs to module paths

## FEM Extension Pipeline

When `run_solver=True` and `shell_obj` is a `CompositeShell`, the FEM extension
providers automatically wire up:

1. **Orthotropic orientations** — `drape_laminate_provider` injects per-layer
   fibre directions from the draped mesh into the FEM mesh
2. **Per-layer shell sections** — Each lamina becomes a separate shell layer
   with its own orientation and thickness
3. **Indirect material properties** — Engineering constants (E1, E2, G12, ν12)
   are derived from the lamina definitions

This enables accurate composite stress analysis with CalculiX shell elements.

## Troubleshooting

### "Application unexpectedly terminated" with solver runs

FreeCADCmd's `-c` flag has limited buffer size for long-running operations.
Use a script file instead (see examples above).

### "Draper invalid — NonDrapable"

The draper may fail on geometries with singularities (e.g., cone apex) or
extreme curvature. The FEM pipeline continues using the support shape as a
fallback. Try:

- Smaller arc angles (30–60° instead of 90°+)
- Larger radii relative to mesh density
- Checking the `MaxLength` property on the CompositeShell

### "ObjectsFem is required"

Ensure FreeCAD was built with FEM module enabled (`BUILD_FEM=ON`).

### "Unable to create FEM analysis/solver/mesh objects"

Missing FEM factories — check that CalculiX and a mesher (Gmsh/Netgen) are
installed and accessible.

### "Mesh too dense" / "mesh generation failed"

Reduce the draper mesh density by lowering `CompositeShell.MaxLength` (default
is typically sufficient). Values below 0.5mm may cause memory issues on large
surfaces.

## Tests

Run the integration test suite:

```bash
cd build/pixi-debug
../bin/FreeCADCmd -P Mod/Composites/compositestests/run_freecad_integration_tests.py
```

Or with pytest (requires FreeCAD in PYTHONPATH):

```bash
cd build/pixi-debug
python3 -m pytest Mod/Composites/compositestests/test_integration_freecad.py -xvs
```

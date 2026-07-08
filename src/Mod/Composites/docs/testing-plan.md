# Composites Testing Plan

**Status:** Active  
**Last Updated:** 2026-07-08  
**Owner:** John Wharington  

## Overview

This document outlines the testing strategy for the Composites workbench. The approach emphasizes **real FreeCAD objects** over mocks to catch integration issues early and ensure robust behavior.

## Testing Pyramid

### Layer 1: Unit Tests (Fast, Isolated)

**Goal:** Test individual functions and classes in isolation.

**Approach:**
- Pure Python code (e.g., `tools/seam.py`, `util/geometry_util.py`)
- Mock external dependencies (FreeCAD, Part, etc.)
- Run quickly (< 1 second per test)

**Location:** `src/Mod/Composites/compositestests/test_unit/`

**Examples:**
- `test_seam_tools.py` — geometry helpers
- `test_geometry_util.py` — vector/math utilities
- `test_mesh_util.py` — mesh operations

### Layer 2: Integration Tests (Medium Speed, Real Objects)

**Goal:** Test FeaturePython classes with real FreeCAD objects.

**Approach:**
- Use `FreeCADCmd` (headless) with real FreeCAD document objects
- Minimal GUI mock only for command registration
- Can save/load `.FCStd` files to verify persistence
- Run in 1–5 seconds per test

**Location:** `src/Mod/Composites/compositestests/test_integration_freecad.py`

**Examples:**
- `test_composite_shell_fp.py` — shell creation, laminate properties
- `test_seam_shell_fp.py` — seam shell creation, helper visibility, save/load
- `test_place_dart_fp.py` — dart placement, cut wire projection
- `test_rosette_fp.py` — rosette creation and orientation

**Key Pattern:**
```python
class TestFeatureFP(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument(f"Test_{self.id()}")

    def tearDown(self):
        if self.doc.Name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(self.doc.Name)

    def test_save_load_document(self):
        """Verify objects survive document round-trip."""
        obj = self._create_object()
        filepath = os.path.join(tempfile.gettempdir(), "test.FCStd")
        self.doc.saveAs(filepath)
        loaded_doc = FreeCAD.openDocument(filepath)
        try:
            loaded_obj = loaded_doc.getObject(obj.Name)
            self.assertEqual(loaded_obj.TypeId, obj.TypeId)
            # Verify properties
        finally:
            loaded_doc.close()
            os.remove(filepath)
```

### Layer 3: GUI Verification (Slow, Manual-ish)

**Goal:** Verify ViewProviders, symbols, selection, and property editor.

**Approach:**
- Run via FreeCAD MCP server (port 9875)
- Invoke commands through toolbar buttons
- Take screenshots to verify visual appearance
- Manually inspect property editor and recompute behavior

**Location:** Not automated; documented as verification steps

**Examples:**
- Create a Rosette via toolbar command
- Verify the coin symbol appears correctly oriented
- Change `Rosette.Angle` in property editor and observe drape re-solve
- Save/close/reopen document and verify persistence

## Avoiding Mocks

### Why Not Mocks?

Mocks create a simulation that diverges from reality:

1. **Property Registration Timing** — FreeCAD registers properties at specific times during object construction and document restore. Mocks don't replicate this.
2. **Recompute Ordering** — FreeCAD's dependency graph determines execution order. Mocks bypass this.
3. **Persistence** — Saving/loading involves serialization of C++ and Python state. Mocks can't simulate this.
4. **ViewProvider Behavior** — ViewProviders attach to objects and respond to selection. Mocks miss this.

### When to Use Minimal Mocks

Sometimes you need *just enough* mock to make headless tests work:

- `FreeCADGui.addCommand` — needed for feature registration, but can be mocked safely
- `FreeCADGui.ViewProvider` — rarely needed in headless tests

**Pattern:**
```python
# At the very top of test_integration_freecad.py
import FreeCADGui
if not hasattr(FreeCADGui, 'addCommand'):
    FreeCADGui.addCommand = lambda *args, **kwargs: None
```

## Test Organization

### By Feature

Each major feature gets its own test module:

```
compositestests/
├── test_integration_freecad.py
├── test_composite_shell_fp.py
├── test_seam_shell_fp.py
├── test_place_dart_fp.py
├── test_rosette_fp.py
└── test_laminate_fp.py
```

### By Concern

Alternatively, organize by concern:

```
compositestests/
├── test_integration_freecad.py
├── test_persistence.py
├── test_geometry.py
├── test_drape.py
└── test_gui.py
```

**Recommendation:** Organize by feature for clarity, with cross-cutting concerns (persistence, geometry) as separate modules that import feature classes.

## Running Tests

### Headless Integration Tests

```bash
cd /home/jmw/opt/FreeCAD
./build/debug/bin/FreeCADCmd -c "
import sys
sys.path.insert(0, 'src/Mod')
import unittest
loader = unittest.TestLoader()
suite = loader.discover('src/Mod/Composites/compositestests', pattern='test_integration*.py')
runner = unittest.TextTestRunner(verbosity=2)
runner.run(suite)
"
```

### Individual Test Module

```bash
./build/debug/bin/FreeCADCmd -c "
import sys
sys.path.insert(0, 'src/Mod')
import unittest
loader = unittest.TestLoader()
suite = loader.loadTestsFromName('test_seam_shell_fp')
runner = unittest.TextTestRunner(verbosity=2)
runner.run(suite)
"
```

### With Timeout (prevent hangs)

```bash
timeout 60 ./build/debug/bin/FreeCADCmd -c "..."
```

## Debugging Failed Tests

### 1. Inspect FreeCAD Log

```bash
tail -n 100 /tmp/freecad.log
```

Look for:
- `pyException`
- `Traceback`
- `AttributeError`
- `RuntimeError`
- `NameError`

### 2. Enable Verbose Output

```bash
export FC_LOG_LEVEL=2
./build/debug/bin/FreeCADCmd -c "..."
```

### 3. Step Through with Debugger

```bash
./build/debug/bin/FreeCADCmd -d gdb -c "..."
# Or use pydevd for remote debugging
```

### 4. Check Document State

```python
import FreeCAD
doc = FreeCAD.activeDocument()
for obj in doc.Objects:
    print(f"{obj.Name}: {obj.TypeId}")
    for prop in obj.PropertiesNames:
        val = getattr(obj, prop)
        print(f"  {prop}: {val}")
```

## Performance Considerations

### Test Duration Targets

- Unit tests: < 1 second total
- Integration tests: 1–5 seconds per test
- GUI verification: 10–30 seconds per feature

### Optimizations

1. **Reuse Documents** — If tests can share a document, reuse it to avoid creation overhead.
2. **Lazy Setup** — Create objects only when needed.
3. **Skip Slow Tests** — Use decorators to skip tests that require heavy computation.
4. **Parallel Execution** — Run independent tests in parallel (but be careful with FreeCAD's thread safety).

## Regression Testing

### Automated Gates

- All integration tests must pass before merging to main
- GUI verification must pass before release candidates

### Manual Checks

- Create each feature type via toolbar
- Verify symbols render correctly
- Check property editor displays correctly
- Save/close/reopen document and verify persistence

## Known Issues

### 1. FreeCADGui Missing in Headless Mode

**Symptom:** `AttributeError: module 'FreeCADGui' has no attribute 'addCommand'`

**Fix:** Provide minimal mock before importing features.

### 2. Reentrant Recompute During Restore

**Symptom:** Segfault or hang during document restore

**Fix:** Detect `fp.Document.Restoring` and skip solve logic.

### 3. Property Registration Timing

**Symptom:** `AttributeError` when accessing properties during restore

**Fix:** Guard property accesses with `getattr()` and check existence.

## References

- [FreeCAD Development Skill](/home/jmw/.pi/agent/skills/freecad-dev/SKILL.md)
- [Boy Scout Rule](/home/jmw/.pi/agent/skills/boy-scout/SKILL.md)
- [Clean Code Principles](/home/jmw/.pi/agent/skills/python-clean-code/SKILL.md)
- [Integration Roadmap](src/Mod/Composites/docs/integration-roadmap.md)
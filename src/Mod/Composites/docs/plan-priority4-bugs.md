# Plan: Priority 4 — Pre-existing Cosmetic Bugs

**Date:** 2026-07-15
**Scope:** Known cosmetic/functional bugs that are orthogonal to Priority 1 work
**Relationship:** These are tracked separately from Priority 1 (performance + UV quality). They can be fixed independently or deferred.

---

## Bug 1: `offset_angle` Shader Parameter Warning

### Symptom

Console output:
```
SoGLSLShaderParameter::isValid(): parameter 'offset_angle' not found
```

### Root Cause

The GLSL fragment shader defines a uniform `offset_angle` but the Python-side shader parameter registration (`SoGLSLShaderParameter`) either:
- Uses a different name, or
- Registers the parameter after the shader is already linked, or
- The uniform declaration in GLSL doesn't match the Python-side registration

### Investigation Steps

1. Search `shaders/MeshGridShader.py` for `offset_angle` references
2. Check the GLSL fragment shader source for `uniform float offset_angle`
3. Verify `SoGLSLShaderParameter` registration matches the GLSL uniform name exactly
4. Check if the shader is re-linked after parameter registration

### Fix

Align the parameter name between GLSL (`uniform float offset_angle`) and Python registration (`SoGLSLShaderParameter("offset_angle", ...)`). Ensure registration happens before first draw call.

### Files

- `shaders/MeshGridShader.py`
- `shaders/Grid_fragment_shader.glsl`

### Risk

Low — cosmetic only, no functional impact.

---

## Bug 2: `build(run_solver=True)` Fails with `ValueError: null shape`

### Symptom

Running `conical_panel_segment.build(run_solver=True)` raises:
```
ValueError: null shape
```

### Root Cause

This is a pre-existing drape solve bug unrelated to shader support. Likely caused by:
- An empty or uninitialized shape passed to the drape solver
- A missing step in the solve pipeline when `run_solver=True`
- The shape being cleared or invalidated before the solver accesses it

### Investigation Steps

1. Trace the call path from `build(run_solver=True)` to the error
2. Identify where the "null shape" originates (likely a FreeCAD Part operation)
3. Determine if this is a race condition or a missing initialization step

### Fix

Depends on investigation. Likely one of:
- Initialize shape before solver call
- Add a null-check with meaningful error message
- Fix the solve pipeline ordering

### Files

- `compositeexamples/examples/conical_panel_segment.py`
- Relevant Composites feature files

### Risk

Medium — functional bug but only triggered in specific solve paths.

---

## Tracking

| Bug | Severity | Status | Priority |
|-----|----------|--------|----------|
| `offset_angle` warning | Cosmetic | Open | Low — fix when convenient |
| `ValueError: null shape` | Functional | Open | Medium — fix before release |

Both bugs should be investigated and fixed before merging Priority 1 changes, but they are independent of the k-d tree and UV quality work.
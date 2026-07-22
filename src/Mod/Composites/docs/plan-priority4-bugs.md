# Plan: Priority 4 — Pre-existing Cosmetic Bugs (Resolved)

**Date:** 2026-07-15
**Status:** Both bugs resolved/obsolete. See `plan-priority1-master.md`.

## Bug 1: `offset_angle` shader parameter warning — RESOLVED

**Symptom:** `SoGLSLShaderParameter::isValid(): parameter 'offset_angle'
not found in program.`

**What happened:** `offset_angle` was registered in `shader_params` but
never declared/used in GLSL, so the linker eliminated it and Coin warned on
every render. Now declared AND used in `Grid_fragment_shader.glsl` to rotate
the grid UV (`rcoord = R(offset_angle) * coord.xy`) so the grid aligns with
the selected layer's fibre orientation. The accompanying plumbing bug
(`get_offset_angle` int/str key mismatch silently returning 0, which
clobbered the angle on reload) is also fixed. See the master plan's "Shader
features → Grid rotation" section.

## Bug 2: `build(run_solver=True)` fails with `ValueError: null shape` — OBSOLETE

**Symptom (as reported):** `conical_panel_segment.build(run_solver=True)`
raised `ValueError: null shape`.

**Status:** No longer reproduces. `test_compositeexamples::
test_run_forwards_run_solver_flag` passes; the drape attaches on recompute
without the FEM solver. The original investigation was speculative ("likely
caused by …") and the premise no longer holds. No fix was applied; the bug
appears to have been resolved by unrelated pipeline changes.

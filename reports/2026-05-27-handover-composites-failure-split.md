# Handover Plan: Split Composite-Specific Failure Models from FreeCAD FEM

**Date:** 2026-05-27  
**Source branch:** `fem-orthotropic` (rebased)  
**Scope decision (confirmed):** Keep failure-model framework in FreeCAD FEM core; move only composite-specific failure models to `~/opt/FreeCAD-CompositesWB`.

---

## 1) Extracts from current plan (for continuity)

From `reports/2026-05-27-fem-orthotropic-deepdive.html`:

- **Applied grouped history (relevant groups):**
  - **Group C:** Laminated/draped shell plumbing
  - **Group E:** Post-processing failure metrics
- **Observed gaps to preserve in follow-up work:**
  - `expanded_mesh_tools.parse_12d` not yet integrated in SEF path.
  - SEF currently relies on default/fallback allowables.
  - No dedicated FEM test coverage yet for new failure-model path.
- **Suggested follow-up split still valid:**
  - Orthotropic writer/LCS
  - Laminate+drape workflow
  - Failure models + SEF (+ deterministic tests)

---

## 2) File/function split map (precise)

## 2.1 Keep in `~/opt/FreeCAD` (FEM core)

### `src/Mod/Fem/femresult/failuremodels.py`
Keep:
- `default_options` (core defaults; can be slimmed)
- `calc_failure_maximum_strain(...)`
- `calc_failure_maximum_stress(...)`
- `failure_models` registry object (as extension-capable)
- `calc_stress_exposure_factor(...)`

Move out (composite-specific):
- `calc_failure_tsai_wu(...)`
- `calc_failure_hashin(...)`
- Composite interaction parameters usage: `f12`, `f13`, `f23` (currently implicit)

### `src/Mod/Fem/femresult/resulttools.py`
Keep:
- `add_stress_exposure_factor(res_obj, objs)` in core
- but refactor to resolve model through registry/provider, not hardcoded composite models.

### `src/Mod/Fem/feminout/importCcxFrdResults.py`
Keep:
- call site that populates SEF (`resulttools.add_stress_exposure_factor(...)`)

### `src/Mod/Fem/femobjects/result_mechanical.py`
Keep:
- `StressExposureFactor` property definition

### `src/Mod/Fem/App/FemVTKTools.cpp`
Keep:
- scalar map entry for `StressExposureFactor`

### `src/Mod/Fem/femtaskpanels/task_result_mechanical.py`
Keep:
- SEF visualization/UI plumbing (`SEF` selection, user expression symbol)

## 2.2 Move to `~/opt/FreeCAD-CompositesWB`

Create module (proposed):
- `freecad/Composites/fem/failure_models_composites.py`

Move/port:
- Tsai-Wu model implementation
- Hashin model implementation
- composite allowables schema + defaults
- optional helper to map laminate objects/material cards -> model options

Register into FEM core at runtime:
- register model name `tsai_wu`
- register model name `hashin`
- optionally register aliases with explicit namespace:
  - `composites.tsai_wu`
  - `composites.hashin`

---

## 3) Minimal-impact interface required in FEM core

Add a tiny registry API in core (`femresult/failuremodels.py`):

- `register_failure_model(name: str, fn: callable, metadata: dict | None = None)`
- `unregister_failure_model(name: str)` (optional)
- `get_failure_model(name: str)`
- `list_failure_models()`

Behavior:
- core ships built-ins (`maximum_strain`, `maximum_stress`)
- composites WB registers composite models only when installed/loaded
- `calc_stress_exposure_factor(...)` resolves by name through registry

No hard dependency from FEM core to Composites WB.

---

## 4) Work plan by repository

## 4.1 Work in `~/opt/FreeCAD` (this repo)

1. **Refactor failure-model registry**
   - Extract Tsai-Wu/Hashin out of core file.
   - Keep generic models and registration hooks.
2. **Harden SEF call path**
   - In `resulttools.add_stress_exposure_factor`, handle unknown model names gracefully.
   - Keep defaults deterministic.
3. **Tests (core)**
   - Add `src/Mod/Fem/femtest/app/test_failuremodels.py` for max stress/strain + SEF monotonicity.
   - Avoid composite-model assertions in core tests.
4. **Docs/comments**
   - Note optional external providers for additional criteria.

## 4.2 Work in `~/opt/FreeCAD-CompositesWB`

1. **Add composite failure model provider module**
   - Port Tsai-Wu + Hashin logic from FEM branch.
2. **Registration at WB init**
   - On load, import FEM failure registry and register composite models.
   - If FEM registry unavailable, fail soft (log warning, no crash).
3. **Composite allowables mapping**
   - Provide adapter from laminate/material definitions to options dict.
4. **Tests (Composites WB)**
   - deterministic tests for Tsai-Wu/Hashin numerical outputs.
   - integration test: registration visible from FEM failure model listing.

---

## 5) Integration contract

- FEM core must not import Composites WB.
- Composites WB may import FEM registry when available.
- Model names must be stable and documented.
- Unknown model names in result post-processing must not break result import.

---

## 6) Risk controls and rollback

- Keep SEF property/UI in core unchanged to avoid UX regression.
- Land core registry refactor first with backward-compatible names.
- Then land Composites provider; test with and without WB installed.
- Rollback path: re-register Tsai-Wu/Hashin in core quickly if provider integration blocks release.

---

## 7) Recommended delivery sequence

1. FreeCAD core PR: registry split + tests (no composites dependency).
2. Composites WB PR: provider module + registration + tests.
3. Optional FreeCAD follow-up: model selection UI enhancements once provider is proven.

---

## 8) Immediate next commands (operator checklist)

In `~/opt/FreeCAD`:
- create branch `fem-failure-registry-split`
- implement Section 4.1

In `~/opt/FreeCAD-CompositesWB`:
- create branch `composites-failure-provider`
- implement Section 4.2

Then run cross-repo integration test matrix:
- FreeCAD only (no Composites WB)
- FreeCAD + Composites WB loaded

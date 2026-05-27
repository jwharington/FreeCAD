# Implementation Checklists (Issue-Ready)

**Date:** 2026-05-27  
**Scope:** Split composite-specific failure models to `~/opt/FreeCAD-CompositesWB` while keeping general failure model framework in `~/opt/FreeCAD`.

---

## A) `~/opt/FreeCAD` checklist (FEM core)

**Branch:** `fem-failure-registry-split`

### Issue FC-1: Introduce failure-model registry API in FEM core
- [ ] Add registry functions in `src/Mod/Fem/femresult/failuremodels.py`:
  - [ ] `register_failure_model(name, fn, metadata=None)`
  - [ ] `get_failure_model(name)`
  - [ ] `list_failure_models()`
  - [ ] (optional) `unregister_failure_model(name)`
- [ ] Ensure built-in registration on module load:
  - [ ] `maximum_strain`
  - [ ] `maximum_stress`
- [ ] Keep `calc_stress_exposure_factor(...)` using registry lookup.

**Commit stage**
1. `Fem: add failure model registry API with built-in generic models`

**Acceptance**
- [ ] `list_failure_models()` includes only generic built-ins by default.
- [ ] No Composites WB imports in FEM core.

---

### Issue FC-2: Remove composite-specific criteria from FEM core
- [ ] Remove/relocate from `failuremodels.py`:
  - [ ] `calc_failure_tsai_wu`
  - [ ] `calc_failure_hashin`
- [ ] Keep API compatibility for unknown model names (fail-soft path).

**Commit stage**
2. `Fem: remove composite-specific criteria from core failuremodels`

**Acceptance**
- [ ] Core passes with no Tsai-Wu/Hashin symbols present.
- [ ] SEF path remains operational for generic models.

---

### Issue FC-3: Make SEF post-processing provider-safe
- [ ] Refactor `src/Mod/Fem/femresult/resulttools.py::add_stress_exposure_factor`:
  - [ ] Resolve model by registry name.
  - [ ] Graceful fallback when requested model unavailable.
  - [ ] Keep result import robust (no hard crash from unknown model).
- [ ] Keep current result/UI plumbing unchanged:
  - [ ] `feminout/importCcxFrdResults.py`
  - [ ] `femobjects/result_mechanical.py`
  - [ ] `femtaskpanels/task_result_mechanical.py`
  - [ ] `App/FemVTKTools.cpp`

**Commit stage**
3. `Fem: harden SEF post-processing for optional external failure-model providers`

**Acceptance**
- [ ] FRD import works without Composites WB installed.
- [ ] `StressExposureFactor` property still populated/visible when applicable.

---

### Issue FC-4: Add core tests
- [ ] Create `src/Mod/Fem/femtest/app/test_failuremodels.py`
  - [ ] deterministic `maximum_strain`
  - [ ] deterministic `maximum_stress`
  - [ ] SEF monotonicity under stress scaling
- [ ] (optional) add tiny registry test (list/register/get)

**Commit stage**
4. `Fem: add unit tests for generic failure models and SEF behavior`

**Acceptance**
- [ ] Tests pass in FEM-only environment.
- [ ] No composite model expectations in core suite.

---

## B) `~/opt/FreeCAD-CompositesWB` checklist

**Branch:** `composites-failure-provider`

### Issue CWB-1: Add composite failure model provider module
- [ ] Create `freecad/Composites/fem/failure_models_composites.py`
- [ ] Implement:
  - [ ] Tsai-Wu
  - [ ] Hashin
- [ ] Include provider metadata (name/version/model descriptions).

**Commit stage**
1. `Composites: add composite failure model provider (Tsai-Wu, Hashin)`

**Acceptance**
- [ ] Deterministic direct function tests pass.

---

### Issue CWB-2: Register models into FEM core at WB init
- [ ] Wire registration from Composites init path (safe import):
  - [ ] import FEM registry API if available
  - [ ] register `tsai_wu`, `hashin` (plus namespaced aliases optional)
  - [ ] fail-soft with warning if FEM registry missing

**Commit stage**
2. `Composites: register composite failure models with FEM registry on startup`

**Acceptance**
- [ ] With both repos loaded, `list_failure_models()` shows composite models.
- [ ] With FEM absent/incompatible, Composites WB does not crash.

---

### Issue CWB-3: Add composite allowables adapter
- [ ] Add mapper from composite laminate/material data to `model_options` dict.
- [ ] Keep adapter local to Composites WB (no FEM core coupling).

**Commit stage**
3. `Composites: add laminate/material allowables adapter for failure models`

**Acceptance**
- [ ] Tsai-Wu/Hashin options can be constructed from WB objects.

---

### Issue CWB-4: Add tests and integration check
- [ ] Add unit tests for Tsai-Wu/Hashin outputs.
- [ ] Add integration test to assert registry registration into FEM.

**Commit stage**
4. `Composites: add tests for failure model provider and FEM registry integration`

**Acceptance**
- [ ] Provider tests pass standalone.
- [ ] Integration test passes when paired with updated FreeCAD core.

---

## C) Cross-repo integration checklist

- [ ] Matrix run 1: FreeCAD only (`~/opt/FreeCAD`) — no Composites WB loaded.
- [ ] Matrix run 2: FreeCAD + Composites WB loaded.
- [ ] Verify in run 1:
  - [ ] generic failure models available
  - [ ] no import-time errors
- [ ] Verify in run 2:
  - [ ] `tsai_wu`/`hashin` registered
  - [ ] SEF pipeline can use composite models when configured
- [ ] Confirm no regressions in:
  - [ ] orthotropic writer output
  - [ ] result UI (SEF visibility)

---

## D) Suggested PR slicing

1. **PR-FreeCAD-1:** Registry + generic models + safe SEF lookup (+ tests)
2. **PR-Composites-1:** Composite provider + registration (+ tests)
3. **PR-FreeCAD-2 (optional):** UX polish for model selection/diagnostics

---

## E) Immediate commands

```bash
# Repo 1
cd ~/opt/FreeCAD
git checkout -b fem-failure-registry-split

# Repo 2
cd ~/opt/FreeCAD-CompositesWB
git checkout -b composites-failure-provider
```

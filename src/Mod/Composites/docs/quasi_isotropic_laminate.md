# PRD: Quasi-isotropic laminate presentation — isotropic FEM material without draping

| | |
|---|---|
| **Status** | Implemented (FEM verification gate closed at 5%; off-axis material-export fix `1aa33763fe`) |
| **Date** | 2026-09-15 |
| **Related** | `handoff-2026-09-16.md` (implementation state + lessons), `stiffener_composite_shell.md` (PRD style/precedent), `adr/0003-quasi-isotropic-presentation-contract.md` (decision record), `../CONTEXT.md` (terminology), `mechanics/stack_model.py`, `fem/drape_laminate_provider.py`, `../compositeexamples/examples/quasi_iso_laminate_plate.py` |
| **Scope** | QI stack validation, equivalent isotropic material generation, CompositeShell draping bypass, FEM provider shortcut path. |

## Session onboarding

> **New session? Read this block, then the implementation handoff
> `handoff-2026-09-16.md` (same directory) — then skim §§2–7 before touching code.**

- **Status:** steps 1–10 implemented (commits `a33c7773fc`…`1a39c9727a`,
  plus the approximate-tier budget `4d11341619`/`2811aed465`). The FEM
  verification gate (§7.6) has been **run**: variant (b) (draped per-ply)
  was solved against variant (a) on the same plate/mesh and exposed a real
  defect in the **per-ply material export** — rotated engineering
  constants written as principal, dropping the normal-shear coupling. It
  is fixed (`1aa33763fe`, `TYPE=ANISOTROPIC`): the draped membrane now
  matches the QI presentation to ≤~1.6% (was ~27%). Metric switched to
  mean axial ux (`af1bbb95eb`). Remaining: decide the §7.6 tolerance and
  isolate the small residual (composite-section vs single-layer, plus the
  backend's mesh-edge `get_lcs` frame). Do not re-derive from this PRD
  alone; the handoff (`handoff-2026-09-16.md`) is the source of truth for
  current state.
- **What this is:** quasi-isotropic (QI) laminates — balanced stacks with
  evenly spaced ply angles, e.g. `[0/±45/90]s` or `[0/±60]` — behave as
  isotropic sheets in-plane. They therefore need **no draping, no rosette,
  and no per-element material orientation** in the FEM workbench. The whole
  per-element query pipeline (`get_drape_lcs` over the mesh) is bypassed;
  the laminate collapses once, at definition time, into a single equivalent
  isotropic material.
- **Key motivations:** (a) FEM solve-time/export-time cost — the FEM
  writer must not query material orientation across the mesh; (b) correct
  physics — a validated QI stack *is* isotropic in-plane, so the orthotropic
  machinery adds cost without accuracy.
- **Key inherited decisions** (consistent with the seam/stiffener PRDs,
  recorded in ADR-0003):
  loud failures with recorded `last_error`; validation at definition time,
  not at export time; modelling-only scope; isotropy is **declared then
  verified** (two tiers, D1) — an unbalanced stack never silently becomes
  a pseudo-isotropic material; the contract **ends at the exported
  material** — the solver owns bending/shear (D2); QI **composes through**
  the stiffener and seam machinery (D8) — isotropic ⊕ isotropic =
  isotropic, any draped side keeps today's path unchanged.
- **Testing:** headless first (§7.0 tiering; `FreeCADCmd` per the
  `freecad-dev` skill); greyed icons / `Invalid` state on success paths
  are test failures (§7.0 validity invariant).

| | |
|---|---|
| **Status** | Implemented — see `handoff-2026-09-16.md` for verification state |

## Table of contents

- [1. Problem statement](#1-problem-statement)
- [2. Terminology](#2-terminology)
- [3. Design decisions](#3-design-decisions)
- [4. Mechanics implementation](#4-mechanics-implementation)
- [5. Object and feature implementation](#5-object-and-feature-implementation)
- [6. FEM integration](#6-fem-integration)
- [7. Test plan](#7-test-plan)
- [8. Examples](#8-examples)
- [9. Acceptance criteria](#9-acceptance-criteria)
- [10. Out of scope / future phases](#10-out-of-scope--future-phases)
- [11. Open questions](#11-open-questions)
- [12. Implementation order](#12-implementation-order)

---

## 1. Problem statement

A draped `Composite::Shell` carries a rosette-driven material frame. In the
FEM workbench this costs real time at export and solve:

- `fem/drape_laminate_provider.py::shell_orientation_provider` walks **every
  shell element** (`{e: element_info(e) for e in elements}`), fetching
  element nodes (`femmesh_obj.getElementNodes`, `getNodeById`) and calling
  `CompositeShell.get_drape_lcs(tris)` per element to build a per-element
  local coordinate system map.
- The section is exported as `COMPOSITE,ORIENTATION=…` with an orthotropic
  material, forcing the solver to carry a distributed material frame.

For a quasi-isotropic layup this is pure overhead: the in-plane response is
rotation-invariant, so the orientation field carries **zero information**.
Today a QI layup pays the full draping + per-element-query cost for nothing.

Required: a presentation path in which a QI laminate

1. is validated as genuinely balanced (equal ply counts, evenly spaced
   angles, B ≈ 0) — at definition time, loudly on failure;
2. collapses once into a single equivalent isotropic material
   (`E`, `ν`, `G`, `Density`, `Thickness`);
3. requires no draping or rosette on the shell;
4. exports to FEM as a plain isotropic material + shell section, with no
   `*ORIENTATION`, no per-element querying, no composites-specific
   machinery in the solver input.

## 2. Terminology

Recorded in `CONTEXT.md` (new *Quasi-isotropic* term group) as of the
grill session; repeated here for the implementation reader:

**Quasi-isotropic (QI) laminate**:
A stack with equal numbers of plies at evenly spaced orientations
(typically including 0° and 90°), whose in-plane extensional response is
rotation-invariant. A QI laminate *presents isotropic* — it needs no
orientation machinery.
_Avoid_: isotropic laminate (it is not material-isotropic; only the
effective response is), balanced laminate (necessary but not sufficient
without even spacing).

**Isotropic presentation**:
The collapse of a validated QI laminate into one equivalent isotropic
material + thickness, computed once at laminate level, consumed by FEM
without orientation lookup.
_Avoid_: smearing (a `StackModelType` concept, applies to orthotropic
merging too), homogenisation (implies micromechanics).

QI is a **laminate** property, not a shell type. There is deliberately
no `QICompositeShell` feature class: a QI shell is any shell carrying a
laminate with the declaration set (either tier, D1) — a plain
`Composite::Shell`, a
stiffener web, or a seam/foot shell whose combined laminate derived
QI-ness from its sides (§5.4).

**Balance validation**:
The loud check that a stack declared isotropic-presenting satisfies the
QI conditions within tolerance. Runs at definition/recompute time.
_Avoid_: isotropy test (ambiguous with material isotropy).

**Drape-dependent operation**:
An operation that consumes the drape solution — texture-plan generation,
align-fibre rosette, weave-texture rendering, FEM orientation lookup.
Undefined on an isotropic shell (there is no drape and no fibre frame);
blocked loudly at command level, not merely at protocol level.
_Avoid_: draped operation, solver operation.

## 3. Design decisions

### D1 — Declared, then verified (loud failure)

Isotropy of presentation is an explicit user declaration, not an
inference, and it is **two-tier** (resolved during grill 2026-09-15):

- `IsotropicEquivalent` (exact): the stack must satisfy the QI
  conditions to round-off — loud error otherwise. No advisory tolerance.
- `ApproximateIsotropicEquivalent`: for deliberately nearly-balanced
  stacks (e.g. 45°-doubled QI). Passes only when every membrane residual
  is within a coarse budget (**20% of A₁₁** — interim value by user
  decision 2026-09-16, widened from the provisional 5% so the
  45°-doubled stack `[0/2×45/90]s` with its measured A66 residual of
  ≈15% of A₁₁ is admitted for now); the deviation is recorded as a
  read-only property and never silently ignored. Large residuals
  (clearly orthotropic stacks) are rejected in **both** tiers. Not
  usable with core plies.

A stack that fails its tier's validation is a **loud error**
(`last_error` recorded, feature marked touched-error), exactly like the
seam/stiffener failure contract. Rationale: silently exporting a
pseudo-isotropic material produces quietly wrong physics; that is worse
than an error. The approximation, when wanted, must be a *named,
quantified* declaration — never a loose tolerance on the exact one.

### D2 — Isotropy is a membrane property; the solver owns the rest

(resolved during grill 2026-09-15) The workbench's contract ends at the
exported material: it validates that the declared stack is isotropic
**in-plane**, computes the equivalent constants, and hands the solver a
plain isotropic material. Bending, transverse shear, and through-
thickness behaviour of that equivalent plate are the solver's domain —
no D-matrix machinery is checked, exported, or warned about in the QI
path (the D matrix never leaves the workbench there). For a stack with
equal ply fractions at angles evenly spaced over 180°, the membrane
conditions A₁₁ = A₂₂, A₁₆ = A₂₆ = 0, A₆₆ = (A₁₁ − A₁₂)/2 hold
**exactly**, so the equivalent constants satisfy G = E/(2(1+ν)) and a
genuine isotropic material representation exists.

### D3 — Equivalent constants come from A, once

The equivalent isotropic constants are derived from the merged A matrix
(not via the determinant route in `merge_clt`, which is kept for the
orthotropic path) because A-isotropy makes the algebra exact:

- h = Σ t_k (total thickness)
- ν_eff = A₁₂ / A₁₁
- E_eff = (A₁₁ − A₁₂)(A₁₁ + A₁₂) / (A₁₁ · h)
- G_eff = (A₁₁ − A₁₂) / (2 h)   — identically E_eff / (2(1+ν_eff))

Density is the existing thickness-weighted density from `merge_clt`.
Through-thickness properties (`YoungsModulusZ`, `PoissonRatioXZ/YZ`,
`ShearModulusXZ/YZ`) are retained on the `HomogeneousLamina` from the
existing C/H path so the object remains usable for solid-element FEM; the
FEM shell path (§6) uses only E, ν, G, density, thickness.

### D4 — Draping bypass is structural, not conditional

A shell carrying an isotropic-equivalent laminate never enters the drape
backend at all — no rosette is required (the `CompositeShellCommand`
`sel_args` already mark `rosette` optional), no `Rosette` property is set,
and the shell's drape-LCS protocol functions
(`get_drape_lcs` etc., `features/CompositeShell.py:624`) fail loudly if
called, consistent with `_require_valid()`. Rationale: a structural bypass
cannot regress into "draped but ignored"; an optional-bypass design would
leave the cost path reachable.

### D5 — FEM export takes the plain-material path

The CalculiX writer (`src/Mod/Fem/femsolver/calculix/write_femelement_geometry.py`)
already writes a plain material reference when `matgeoset["orientation"]`
is `None` — no `*ORIENTATION` block, no `ORIENTATION=` suffix on the
material name. The QI path therefore only requires the Composites
provider (`fem/drape_laminate_provider.py`) to:

1. **not** supply an `"orientation"` key for QI shells (skip
   `shell_orientation_provider` entirely);
2. supply the equivalent isotropic material dict via
   `indirect_material_provider` (it already flows through
   `membertools.py::mats_laminate`);
3. write a single-layer plain shell section (thickness + material name)
   instead of the ply-by-ply `*SHELL SECTION, COMPOSITE=…`.

Zero per-element work: the orientation provider is never called, the mesh
is never walked, and the solver input carries one material and one section
per QI shell.

### D6 — Smeared merge, not new stack machinery

The collapse reuses the existing `StackModelType.Smeared` path through
`stack_expansion.py` → `merge_clt` (`mechanics/stack_model.py`); the new
work is an isotropic variant of `merge_clt`'s output stage plus the
validation function. Nested laminates and core plies are **rejected** in
isotropic presentation in phase 1. Note (grill 2026-09-15): the core
rejection is *not* about isotropy — a foam-core QI sandwich is in-plane
isotropic and the numeric check would pass — it is about substitution
magnitude: sandwich bending is dominated by core shear and facesheet
separation, far from a monolithic isotropic plate of thickness h. A
sandwich QI presentation deserves its own deliberate decision (likely
facesheet+core export shape); until then, `core=True` raises in both
tiers with a message pointing at the limitation. The long-term principle
is **numeric-only** admission: validation residuals are the sole arbiter
of what may present isotropic; structural exclusions are phase-1 policy,
not permanent law (see OQ-7).

### D7 — Drape-dependent operations are blocked at entry level

A QI shell has no drape solution, so every consumer of the draper
protocol must be protected — not only the FEM provider (D5). The drape
protocol functions failing loudly (D4) is the backstop, not the guard:
commands are **blocked at selection/activation time** with a clear
message, because a mid-execute failure after the user built a selection
is a bad contract. Known consumers and their required behaviour:

| Consumer | Uses | QI behaviour |
|---|---|---|
| `TexturePlan` command (`features/TexturePlan.py`) | `get_boundaries` via `get_stack_assembly` | command blocked at selection: shell is isotropic, no flat-pattern exists |
| `AlignFibreRosette` (`features/AlignFibreRosette.py`) | `get_draper()` → `get_tex_coord_at_point` | blocked at selection: no fibre direction to align |
| Weave texture rendering (`features/coin_geometry.py`, `VPCompositeShell`) | `get_tex_coord_at_point` per vertex | render falls back to plain material colour — render-time code must not raise |
| FEM orientation provider (`fem/drape_laminate_provider.py`) | `get_drape_lcs` per element | provider skipped entirely (D5) |
| `rosette_solver` / `fibre.py` | `get_draper` / `get_boundaries` | unreachable: no rosette can attach to an isotropic shell (§5.2) |

Rendering is the one exception to loud failure: it is ambient, cannot be
"blocked", and a missing texture must degrade to a plain colour, never a
crash or a black shell.

### D8 — QI composes through the stiffener and seam machinery

The stiffener and seam flows combine laminates: side stacks are rotated
into the shared frame by solved transfer angles
(`SeamCompositeLaminateFP._side_layers`), concatenated
(`_combined_layers`), and recorded as a literal combined stack with
`Symmetry` pinned `Assymmetric`. A QI laminate must compose through this
machinery seamlessly — as a seam side, as a stiffener web, and as a
derived property of the combined result. The composition algebra:

- **isotropic ⊕ isotropic = isotropic** — the merged A of isotropic
  layer sets is isotropic, so a combined stack presents isotropic **iff
  every side is QI**.
- **a QI side is orientation-free** — its plies enter the literal stack
  record at their nominal angles with a **fixed rotation of 0**
  (rotating an isotropic side is meaningless); the solved transfer
  rosette on that side is *not required*.
- **any draped side makes the combination draped** — transfers,
  orientation provider, and rendering run for the draped side exactly as
  today; the QI side contributes orientation-free plies.
- **combined QI-ness is derived, never declared** — the combined
  laminate's `IsotropicEquivalent` is a read-only computation from its
  sides; when derived-true, the combined stack is re-validated by the
  §4.2 balance check (expected to pass trivially, but verified loudly
  rather than assumed).

Details per feature in §5.4. The reserved combination models (interleave,
taper) inherit the same algebra when implemented.

## 4. Mechanics implementation

### 4.1 Isotropic merge path — `mechanics/stack_model.py`

New function alongside `merge_clt`:

```python
def merge_clt_isotropic(prefix: str, layers: List[Lamina]) -> HomogeneousLamina:
```

- Computes A via the same `accumulate_ABD` accumulation (or a slimmed
  A-only variant — implementation detail).
- Extracts equivalent constants per D3.
- Builds the material dict via `material_from_dict(mat, orthotropic=False)`
  — isotropic shape: `YoungsModulus`, `PoissonRatio`, `ShearModulus`
  (derived, written for completeness), `Density`.
- Keeps through-thickness properties from the C/H matrices (D3).
- Returns a single `HomogeneousLamina` with `orientation=0`,
  `thickness=h`, `description` naming the source stack
  (e.g. `"QI [0/45/-45/90]s"`).
- Assembly of the description belongs in this function or its caller; the
  canonical stack notation comes from `format_orientation` /
  `format_layer` in `util/geometry_util.py`.

### 4.2 Balance validation — `mechanics/stack_model.py`

New pure function (testable without FreeCAD):

```python
def validate_quasi_isotropic(
    A: np.ndarray, B: np.ndarray,
    tol: float = 1e-6,
    budget: float = 0.20,
) -> None  # raises QuasiIsotropicError on failure
```

Checks (A is the merged CLT extensional matrix; scale-relative
residuals):

| Condition | Type | Note |
|---|---|---|
| \|A₁₁ − A₂₂\| / A₁₁ ≤ tol | error | |
| \|A₁₆\|/A₁₁, \|A₂₆\|/A₁₁ ≤ tol | error | exactly 0 for evenly spaced sets |
| \|A₆₆ − (A₁₁ − A₁₂)/2\| / A₁₁ ≤ tol | error | implied by the above; kept explicit |
| \|B\| / A₁₁ ≤ tol (all 9 terms) | error | symmetric stack required |

- Tolerances: exact tier proposed at **1e-6** (relative) — the balanced
  QI conditions are analytically exact, so only floating-point
  round-off should register; approximate tier budget **20% of A₁₁** per
  residual (interim value by user decision 2026-09-16, widened from the
  provisional 5% to admit the 45°-doubled stack; D1). **These
  thresholds must not be widened without explicit user confirmation**
  (testing-discipline rule).
- Failure mode: raise a dedicated exception type; the caller (feature
  layer, §5) records `last_error` and marks the object touched-error, per
  the established loud-failure contract.

### 4.3 Stack expansion

`objects/laminate.py::get_layers` is unchanged for the orthotropic paths.
The isotropic collapse is routed by the **declaration flag, passed as a
parameter** (resolved during grill 2026-09-15, replacing OQ-2): the
routing point is `LaminateFP.execute` → `get_layers_ccx(laminate,
model_type)` (`features/Laminate.py`, `util/fem_util.py`), which passes
`isotropic=obj.IsotropicEquivalent or obj.ApproximateIsotropicEquivalent`
down to the merge branch (`merge_clt_isotropic` + validation). The
`StackModelType` enum is untouched — isotropic presentation is orthogonal
to how the stack is represented, and an enum member would make it
combinatorial with the existing members and their `merged_name` dispatch.

## 5. Object and feature implementation

### 5.1 `Composite::Laminate` (`features/Laminate.py`, `objects/composite_laminate.py`)

New properties on the Laminate FP object:

| Property | Type | Purpose |
|---|---|---|
| `IsotropicEquivalent` | `App::PropertyBool` | declares exact QI presentation; drives validation + collapse |
| `ApproximateIsotropicEquivalent` | `App::PropertyBool` | approximate presentation (D1, two-tier); passes only within the residual budget; deviation magnitude recorded on the object |

`CompositeLaminate` (dataclass in `objects/composite_laminate.py`) gains
matching fields (`isotropic_equivalent: bool = False`,
`approximate_isotropic_equivalent: bool = False`) so the non-GUI model
path mirrors the feature, plus a residual-carrier for the approximate
tier's recorded deviation. The existing `Ply.set_missing_child_props`
mechanism is reused for propagation where applicable.

### 5.2 `Composite::Shell` (`features/CompositeShell.py`)

- `sel_args` already marks `rosette` optional — a QI shell is created with
  support + laminate only. **No property changes needed.**
- When the laminate has `IsotropicEquivalent=True`:
  - the shell does not instantiate the drape backend. **The bypass must
    be inside `CompositeShell.execute`** (check the laminate flag before
    `_run_drape_sync`, keeping the shape/placement sync): the stiffener
    flow drives `shell.Proxy.execute(shell)` directly via
    `_ensure_draped` (`StiffenerCompositeShell.py`), so a bypass only in
    the protocol functions would be re-entered by that direct drive;
  - `get_drape_lcs` / `get_lcs_at_point` / `get_tex_coord_at_point` raise
    loudly ("isotropic shell has no drape frame") rather than returning
    garbage — structural bypass per D4;
  - a single helper — e.g. `is_isotropic_shell(obj)` next to the existing
    `is_composite_shell` / `is_laminate` predicates — is the guard every
    drape-dependent command tests (D7).
- Entry-point guards added per D7:
  - `TexturePlanCommand.Activated` / `sel_args` test: reject a selection
    containing an isotropic shell with the message "isotropic shell has no
    drape: no texture plan";
  - `AlignFibreRosetteCommand`: same guard ("no fibre direction to
    align"); also unreachable via the normal flow because a rosette
    cannot attach to an isotropic shell;
  - `VPCompositeShell` / weave shader path: **no new fallback mechanism
    is needed** (verified during grill 2026-09-15): the weave look is the
    `MeshGridShader` overlay on drape geometry, and
    `coin_geometry._map_uv_to_support` already guards a `None` backend.
    With no drape geometry and no shader, the shell renders as its native
    Part shape in plain colour; the `DisplayMode="Grid"` switch only
    occurs when the shader is attached. Covered by a test, not new code.

### 5.3 Error contract

`QuasiIsotropicError` messages must name the offending residual, e.g.:
`"not quasi-isotropic: |A16|/A11 = 2.4e-2 exceeds 1e-6 (angle set not evenly spaced?)"`.

Wiring invariants for declared stacks:

- The declaration flags **override** `StackModelType` for FEM layer
  generation: a declared stack always exports as the single isotropic
  equivalent, regardless of the discrete/smeared setting (which keeps
  governing the BOM / stack-record views).
- A rosette manually attached to an isotropic shell is a wiring error:
  loud on recompute ("isotropic shell takes no rosette"), consistent
  with the seam/stiffener wiring-validation style.

### 5.4 Composition — `SeamCompositeLaminate` and `StiffenerCompositeShell`

Both flows reuse the `SeamCompositeLaminateFP` machinery (the stiffener
foot's combined laminate is built with it — `StiffenerCompositeShell.py`
imports `CombinationModel, SeamCompositeLaminateFP`). QI changes this
machinery minimally, per D8:

| Aspect | Change |
|---|---|
| Wiring validation | `SeamCompositeLaminateFP._validate_wiring`: a side whose laminate is QI may omit its transfer rosette (proxy-type check relaxed for that side); a draped side still requires it; the shared-edge checks stay (geometry, not orientation). `StiffenerCompositeShell.validate_composite_wiring` needs **no change** — a missing rosette is already tolerated today (auto-created, A.3); only a linked non-rosette raises |
| `_side_layers` (QI side) | rotation contribution fixed at 0 — plies enter the record at nominal angles; no transfer resolution for that side |
| `_seam_angles` / `SideAngleReport` | `None`-tolerant angle reads; QI sides report `n/a` in the map; `EffectiveOffsetAngle` written only when both sides are draped |
| `_seam_angles` / `_update_angle_outputs` | QI sides contribute no solved angle (report `n/a`); they never block the solve of the draped side |
| Transfer resolution in `execute` | skips `MasterTransfer`/`AttachmentTransfer` stand-ins for QI sides (no `resolve` needed) |
| Combined presentation | combined laminate's `IsotropicEquivalent` **derived read-only** = all sides QI; re-validated via §4.2 when true |
| Stiffener web | QI web laminate → **skip `_ensure_web_rosette` auto-creation** (a missing rosette is already tolerated; leave `fp.Rosette = None`) and **skip `_ensure_draped(web_shell)`**; web shell renders plain (D7 fallback) |
| Stiffener analysis transfer | `_StiffenerFootTransfer` (web → foot, analysis-only) is meaningless for a QI web (isotropic web has no angles to translate) — skip creating it in that case; `_PanelFootTransfer` (master/panel side) is kept whenever the panel is draped |
| Stiffener foot / seam-region shell | carries the combined laminate; the FEM provider sees an ordinary shell whose laminate flag drives the D5 skip — **no special-casing** in `fem/drape_laminate_provider.py` |
| Weave rendering on child shells | web / seam / remainder shells fall back to plain colour when their (combined) laminate is QI |

When at least one side is draped, the combination behaves exactly as
today — the draped side's transfers, angles, and orientation provider
run unchanged. The remainder shell of a seam extraction carries the
attachment's own laminate: if that is QI, the remainder is orientation-
free under the same rules.

`SeamCompositeLaminate` pins `Symmetry = Assymmetric` for the literal
record; this is untouched — a QI declaration on the *sources* is what
makes the combined stack isotropic, not symmetry mirroring.

## 6. FEM integration

### 6.1 Provider changes — `fem/drape_laminate_provider.py`

- `shell_orientation_provider`: when the shell's laminate
  `IsotropicEquivalent` is true, return `{}` — no orientation key, no
  `get_drape_lcs`, no mesh walk. (The CalculiX writer already emits a
  plain material reference when `orientation` is `None` — verified in
  `src/Mod/Fem/femsolver/calculix/write_femelement_geometry.py:171`.)
- `shell_section_provider`: when isotropic, return a single-layer plain
  section spec (thickness + material name) instead of
  `laminate.Proxy.write_shell_section(...)` ply composite geo. The
  existing `write_shell_section_ccx` in `util/fem_util.py` already
  supports a single `HomogeneousLamina` layer; the smeared isotropic
  output is one, so the same writer works unchanged.
- `indirect_material_provider`: unchanged mechanics — the laminate's FEM
  layer list is a single isotropic `HomogeneousLamina`. **Verified**
  (grill 2026-09-15): `write_lamina_material_ccx` (`util/fem_util.py`)
  already branches on `is_orthotropic(layer.material)` and emits
  `*ELASTIC, TYPE=ISO` with E, ν and `*DENSITY` for isotropic dicts —
  **no material-writer changes are needed**.

### 6.2 What disappears at export time

For a QI shell the FEM export does:

| Stage | Draped shell | QI shell |
|---|---|---|
| Orientation provider | per-element node fetch + drape LCS | not called |
| Mesh walk | O(N_elements) | none |
| Material | orthotropic `*ELASTIC, TYPE=ORTHOTROPIC` + `*ORIENTATION` | `*ELASTIC, TYPE=ISO` |
| Section | `*SHELL SECTION, COMPOSITE=` ply list | single-layer `*SHELL SECTION` |
| Solver cost | orientation transforms per element | none |

## 7. Test plan

All in `compositestests/`, real objects, no mocks, per the module testing
philosophy. Tolerances below are proposals for new tests; widening any of
them requires explicit user confirmation.

### 7.0 Execution: headless first; validity as an invariant

**Headless-first tiering** — as much testing as possible runs without a
GUI (canonical commands per `freecad-dev` skill; always the build-tree
binary `build/debug/bin/FreeCADCmd`):

| Tier | Runs on | How | Covers |
|---|---|---|---|
| A — validation core | plain python, no FreeCAD | run `validate_quasi_isotropic` directly (A.2: the only FreeCAD-free unit) | §4.2 residuals, both tiers |
| B — headless | `FreeCADCmd` | `FreeCADCmd -t compositestests.<module>` for single modules (incl. the §7.1 merge tests — `material_properties.py` imports `FreeCAD.Units`, A.2); `FreeCADCmd -P src/Mod/Composites/compositestests/run_freecad_integration_tests.py` for the integration set (FreeCADGui mocked before imports) | §7.1–§7.6, examples, provider, e2e |
| C — GUI | full GUI (MCP session) | only visual checks: weave-vs-plain rendering, rosette symbol layout, and **icon validity** | the one thing headless cannot see |

Run only the modules relevant to the step in progress (testing
discipline: fail fast, short timeouts, batched); `run-tests.sh` records
per-test timings to a parseable file for regression comparisons.

**Validity invariant (greyed icons are failures).** A greyed-out icon in
the GUI is the visible symptom of a feature left in an error state — it
means something is wrong. Therefore:

- every success-path test asserts `assertNotIn("Invalid", obj.State)`
  for **every** Composites feature the test created (existing convention
  in `test_seam_composite_laminate.py` / `test_stiffener_composite_shell.py`
  — extended here to all QI features: web, foot, seam-region, remainder,
  combined laminates);
- the loud-failure path asserts the **opposite**: `Invalid` present *and*
  `last_error` populated — a rejected declaration must show as a greyed
  icon, never as a silently valid object;
- GUI-tier checks additionally eyeball that no icon is greyed after the
  example recomputes settle (mirrors the State assertions above).

This applies to the D7 render fallback too: a QI shell must render plain
**and stay valid**, not fail its recompute.

### 7.1 Mechanics unit tests — `test_mechanics.py`

New `TestQuasiIsotropic` class, building stacks from the existing
`_make_glass()` / `_make_resin()` helpers (real unit-conversion path):

- `test_qi_A_matrix_isotropic` — `[0/45/−45/90]` equal plies:
  `|A11−A22| ≤ 1e-6·A11`, `|A16|, |A26| ≤ 1e-6·A11`
  (analytically exact zeros; round-off only).
- `test_qi_G12_identity` — on the equivalent material,
  `|G − E/(2(1+ν))| ≤ 1e-9 · G` (identity from D3 must hold to
  round-off).
- `test_qi_equiv_rotation_invariant` — `material_rotate(equiv, θ)` equals
  `equiv` for θ ∈ {30°, 61.3°} to `1e-9` relative (the defining property
  of the presentation).
- `test_qi_symmetric_stack_B_zero` — `expand_symmetry` with
  `SymmetryType.Even` produces `|B|/A11 ≤ 1e-6`.
- `test_unbalanced_stack_rejected` — `[0/45]` raises
  `QuasiIsotropicError` naming `A11 − A22`.
- `test_uneven_angle_set_rejected` — `[0/30/90]` (equal counts, not evenly
  spaced) raises naming `A16`.
- `test_core_ply_rejected` — stack with `core=True` raises under
  isotropic presentation.
- `test_approximate_tier_passes_near_balanced` — nearly-balanced
  ±45-family thickness perturbation of a symmetric QI stack passes the
  approximate tier (each residual ≤ budget) and fails the exact tier.
- `test_approximate_tier_doubled_45_accepted` — the 45°-doubled stack
  (measured A66 residual ≈15% of A₁₁) passes the approximate tier under
  the interim 20%-of-A₁₁ budget (user decision 2026-09-16) and fails
  the exact tier.
- `test_approximate_tier_records_deviation` — validation returns the
  per-residual magnitudes (pure dict, FreeCAD-free); the feature layer
  stores them read-only (§7.3).
- `test_approximate_tier_rejects_large_residual` — a clearly orthotropic
  stack fails both tiers.
- `test_isotropic_dict_shape` — merged material has `YoungsModulus`,
  `PoissonRatio`, `Density`; no `YoungsModulusX`.
- `test_thickness_weighted_imbalance_rejected` —
  `[0(0.2)/45(0.3)/−45(0.3)/90(0.2)]`: equal ply counts, unequal
  thicknesses — the 45° pair carries 60% of the angled weight. NOT
  isotropic; the numeric A-check must reject it (the classic hand-built
  stack mistake; no structural pre-check would catch it).
- `test_angle_normalisation_equiv` — the same physical stack entered as
  `[0/135/−135/90]` (mod-180 equivalents of `[0/−45/45/90]`) passes
  validation; a stack that is only QI-looking before normalisation
  fails. Validation operates on the `normalise_orientation` set.

### 7.2 Drape-dependent operation protection — `test_compositeexamples.py` / new cases in `test_laminate.py`

- `TexturePlan` execution on an isotropic shell raises loudly before any
  geometry work (entry guard), naming the isotropic shell.
- `AlignFibreRosette` creation against an isotropic shell is blocked at
  selection validation.
- Rendering: an isotropic shell in a headless recompute does not raise,
  stays valid (`State` clean, no greyed icon) and produces no
  weave-texture geometry; GUI-only confirmation of the plain-colour
  fallback follows the existing `GuiUp`-guarded patterns
  (`test_compositeexamples.py` guard blocks) in the GUI tier.
- The protocol backstop still holds: calling `get_tex_coord_at_point` or
  `get_drape_lcs` directly on an isotropic shell raises.

### 7.3 Feature-level tests — `test_laminate.py`

- `get_layers(StackModelType.Smeared)` on a QI-declared laminate returns
  exactly one `HomogeneousLamina`, isotropic dict shape, correct
  `thickness = Σ t_k`.
- `last_error` populated and recompute marked error when
  `IsotropicEquivalent=True` on an unbalanced stack (loud-failure
  contract).
- `test_bom_record_unchanged_for_qi` — `get_stack_assembly`/BOM output
  for a declared-QI laminate is identical to the undeclared one (the
  literal ply record survives; the flag redirects only FEM export —
  pins the Q6 precedence decision).

### 7.4 Composition tests — `test_seam_composite_laminate.py`, `test_stiffener_composite_shell.py`

Seam (QI algebra per D8):

- both sides QI: no transfer rosettes required; wiring validates; the
  combined laminate's derived `IsotropicEquivalent` is true and the
  combined stack passes balance validation.
- draped side + QI side: the draped side's transfer rosette is required
  and solved; the QI side contributes no angle; the combined laminate is
  draped (derived flag false).
- both draped: existing behaviour unchanged (regression guard — no QI
  wiring may alter the draped path).
- QI side plies enter the literal record at nominal angles (rotation 0).
- remainder shell of an extraction with a QI attachment is orientation-
  free.

Stiffener:

- QI web laminate: stiffener created without rosette;
  `validate_composite_wiring` passes; no `_WebRosette` created; web
  shell renders plain without raising.
- QI stiffener + QI panel: foot combined laminate derives QI, foot shell
  is orientation-free end to end.
- QI stiffener + draped panel: foot combined laminate is draped;
  panel-side transfer machinery unchanged.

### 7.5 FEM provider tests — `test_drape_laminate_provider.py` + new

- Orientation provider returns `{}` for a QI shell (no mesh walk: assert
  with a small real femmesh). Follow the established fake-registry
  capture pattern of `test_drape_laminate_provider.py` — inject a fake
  `femtools.fem_extension_registry` into `sys.modules`, capture the
  provider callables, exercise them against real Composites objects;
  the mock boundary is the FEM registry, never the Composites objects
  (A.4).
- Section writer output for the QI laminate contains exactly one layer
  line and the isotropic material name; no `ORIENTATION=` token.
- Generated CalculiX input for a QI shell model: no `*ORIENTATION` block
  for that elset; material written as isotropic. (Follow the existing
  provider-test patterns in `test_drape_laminate_provider.py`.)
- `test_failure_provider_skips_qi` — a QI shell reaching
  `fem/failure_models_composites.py` skips loudly/no-ops; the solve never
  crashes (failure criteria for QI are out of scope, but the interplay
  must be inert).
- `test_draped_path_byte_identical` (negative control) — for a *non-QI*
  stack, the provider changes leave the section head and per-element
  `*ORIENTATION` (the QI-vs-draped branching) byte-identical to the
  pre-change path.  *Scope superseded 2026-09-16:* the per-ply material
  blocks **did** intentionally change — off-axis plies now export as
  `TYPE=ANISOTROPIC` to keep the normal-shear coupling (see the handoff
  §3).  The control therefore pins the provider branching, not the whole
  solver input.

### 7.6 End-to-end FEM analysis test — new `test_quasi_iso_fem.py`, case: the stiffener panel example

**The stiffener panel example (§8.2) is the test case for this work**
(grill 2026-09-15). FreeCAD-integration pattern
(`run_freecad_integration_tests.py` entrypoint, real FreeCAD process,
no mocks); the FEM-analysis construction can reuse the
`test_conical_panel_full_pipeline_round_trip` pattern
(`runner.run(..., run_solver=True)` — already solved headless, A.4):

- Build the example in both variants and run CalculiX:
  - **mixed variant** (draped panel + QI stiffener): foot combined
    laminate is draped — panel-side orientation machinery runs, no
    per-element query for the QI web shell; solver input shows the web
    shell as `TYPE=ISO` single layer and the foot as the existing
    composite section;
  - **QI-panel variant** (`panel_qi=True`): entire assembly
    orientation-free — no `*ORIENTATION` anywhere, all shells `TYPE=ISO`.
- **Cross-validation (membrane gate):** in the QI-panel variant, the
  same stack solved twice — (a) QI isotropic presentation, (b)
  conventional draped orthotropic per-ply export — under an in-plane
  (membrane-dominated) load case. Agreement is measured on the mean axial
  edge displacement (ux; `|u|` is corner-weighted by Poisson uy) and is
  asserted within **5%** (tolerance agreed 2026-09-16; measured ≤1.6% at
  the finest mesh). This proves the collapse preserves the membrane
  answer, which is the whole contract (D2). Bending load-case comparisons
  would test the solver, not the export, and are out of scope.
  *(2026-09-16 finding: the draped per-ply export was ~27% off because
  rotated plies were emitted as orthotropic engineering constants, which
  drop the normal-shear coupling; fixed in `1aa33763fe` by emitting
  `TYPE=ANISOTROPIC`, see the handoff §3.)*
- **Validity sweep:** after every variant build + solve, no created
  feature (panel, stiffener, web shell, foot shell, combined laminate,
  seam features if present) is in `Invalid` state — no greyed icons
  (§7.0).
- **Performance assertion (soft):** count `get_drape_lcs` calls during
  export == 0 for QI shells in both variants. If instrumented timing is
  stable, assert export wall-clock not worse than the draped baseline;
  otherwise keep as a logged metric.

## 8. Examples

### 8.1 Extend — `compositeexamples/examples/quasi_iso_laminate_plate.py`

Add isotropic-presentation output to `build(...)`: declare
`IsotropicEquivalent`, return the merged equivalent `HomogeneousLamina`
in the result dict so downstream consumers (and the example runner) can
inspect E/ν/G/density.

### 8.2 New — `compositeexamples/examples/quasi_iso_stiffener_panel.py`

**The canonical end-to-end test case** (grill 2026-09-15): the
stiffener panel example with QI stiffeners — the QI property exercised
through the full composition path, not just a flat plate. A QI variant
of the existing `stiffener_composite_shell.py` (30° draped panel +
Z-stiffener with its own laminate, web rosette, solved foot transfers):

1. panel stays a draped composite shell (the realistic baseline);
2. the stiffener's own laminate becomes QI `[0/±45/90]s` with
   `IsotropicEquivalent=True` → **no web rosette is created**, the web
   shell has no drape and renders plain;
3. the foot combined laminate (stiffener ⊕ panel) is **draped, mixed**:
   the panel-side foot transfer still solves; the QI side enters the
   record at nominal angles with rotation 0 (D8);
4. build flag `panel_qi: bool = False` — when true the panel laminate is
   also QI, making foot and assembly **fully orientation-free** (the
   FEM-export shortcut end to end). The runner forwards build kwargs
   (`runner.run("quasi_iso_stiffener_panel", panel_qi=True)`), so the
   variant needs no second registry entry (A.4).

Assertions in the example result dict: web rosette absent, derived
combined flag per variant, weave-render ownership (panel remainder +
foot weave in the draped-panel variant; all-plain in the QI-panel
variant).

Registered in `compositeexamples/registry.py` (pattern of the existing
`stiffener_composite_shell` entry), picked up by
`test_compositeexamples.py` (assertion + build run added there).

### 8.3 — `compositeexamples/examples/quasi_iso_fem_plate.py`

Flat plate example running through FEM:

1. rectangular plate, QI laminate `[0/45/−45/90]s` (reuse the carbon/resin
   materials already in `quasi_iso_laminate_plate.py`),
2. `Composite::Shell` (no rosette) over the plate,
3. FreeCAD FEM analysis: shell thickness, constraint + load,
4. CalculiX solve; result dict includes max displacement and the solver
   input snippet showing `TYPE=ISO` + single-layer section.

A minimal membrane-only companion (kept small); the stiffener panel
example (§8.2) carries the composition coverage. Registered in
`compositeexamples/registry.py`, picked up by
`test_compositeexamples.py`.

### 8.4 New — `compositeexamples/examples/quasi_iso_seam.py`

QI variant of the seam scenario (the composition gap the stiffener
panel does not cover): two QI panels lap-jointed, seam extraction →
`SeamCompositeLaminate` with **no transfer rosettes on either side**
(the wiring-relaxation case, D8) → derived-QI combined laminate → the
seam-region shell is orientation-free through the *actual extraction
flow*, not hand-wired fixtures. Assertions: wiring validates without
transfers, derived combined flag true, seam-region shell exports
`TYPE=ISO`, remainder shell (QI attachment) likewise.

### 8.5 New (demo) — `compositeexamples/examples/quasi_iso_cylindrical_panel.py`

QI variant of `cylindrical_panel_segment.py`: demonstrates that
curvature is irrelevant to the QI path — no drape on a curved mould,
plain render on the curved region, unchanged FEM export. Adds little
test discrimination beyond the flat case; primarily a demo. Registered
in `registry.py`, covered by `test_compositeexamples.py` build run.

### 8.6 Benchmark — `compositestests/inspect_qi_export_benchmark.py`

An `inspect_*`-style script (not a CI gate): draped vs QI export
wall-clock against mesh size on the stiffener panel scenario, logging
the realised speedup. Complements the soft §7.6 performance assertion
with real numbers.

## 9. Acceptance criteria

1. A validated QI laminate exports an equivalent **isotropic** material —
   dict shape and rotation-invariance verified by unit tests.
2. An unbalanced or unevenly-spaced stack declared `IsotropicEquivalent`
   fails loudly with a residual-naming error; no silent pseudo-isotropic
   export.
3. FEM export of a QI shell performs **zero** per-element orientation
   queries and produces solver input with no `*ORIENTATION` and no
   `COMPOSITE,ORIENTATION=`.
4. Cross-validation: isotropic-presentation solve agrees with the
   conventional per-ply orthotropic solve of the same stack within the
   agreed tolerance.
5. All drape-dependent operations (texture plan, align-fibre rosette)
   are **blocked at entry** on an isotropic shell with clear messages;
   direct protocol calls raise; rendering degrades to plain colour
   without raising.
6. Stiffener and seam flows work seamlessly with QI laminates (D8):
   QI⊕QI combinations derive isotropic presentation and skip orientation
   machinery; any draped side keeps today's behaviour exactly; wiring
   validation accepts QI sides without transfer rosettes / web rosette.
7. **The stiffener panel QI example (§8.2) builds and runs headless via
   the example runner in both variants** (draped panel + QI stiffener;
   `panel_qi=True`), and the end-to-end FEM test (§7.6) runs CalculiX on
   it with the membrane cross-validation gate; the flat-plate companion
   (§8.3) is covered by `test_compositeexamples.py`.
8. **The QI seam example (§8.4) runs through the actual extraction flow**
   with no transfer rosettes and an orientation-free seam region.
9. Validation catches thickness-weighted imbalance and mod-180 angle
   variants correctly (§7.1); BOM record unchanged for declared stacks
   (§7.3); the draped section/orientation branching is unchanged for
   non-QI stacks (§7.5) — the per-ply material blocks now use
   `TYPE=ANISOTROPIC` (off-axis coupling fix, 2026-09-16).
10. **Validity invariant:** every success-path test/example leaves all
    created Composites features out of `Invalid` state (no greyed icons
    in the GUI); the loud-failure path leaves the rejected feature
    visibly invalid with `last_error` recorded.
11. `CONTEXT.md` gains the §2 terminology entries.

## 10. Out of scope / future phases

- **Ply-level stress recovery from a QI shell** (resolved during grill
  2026-09-15): the QI export is a single smeared isotropic layer, so
  per-ply solver output is not available — accepted trade. The discrete
  stack record stays on the laminate feature for layup documentation; a
  post-processing recovery path is the clean later extension, never a
  retention of orthotropic export machinery in the QI path.

- Failure criteria (Tsai-Wu etc.) for QI shells — `fem/failure_models_composites.py` territory, later.
- QI stack *generators* (design tools producing `[0/±45/90]s` from a ply count) — a follow-up UX concern; this PRD consumes existing stacks.
- Solid-element FEM with through-thickness properties (the isotropic dict keeps Z-properties, but no solid path is wired here).
- Auto-detection of QI-ness without a declaration (superseded by the
  two-tier contract, D1).

Grill-session status (2026-09-15): OQ-1..OQ-6 are resolved or accepted
below; OQ-7 is the deliberately deferred sandwich case; the one remaining
item deferred to implementation review is the cross-validation test
tolerance (§7.6).

## 11. Open questions

- **OQ-1 (resolved 2026-09-15):** two-tier contract — exact tier hard-
  enforces to round-off; near-balanced stacks use the separate
  `ApproximateIsotropicEquivalent` declaration with a residual budget
  (D1). No advisory tolerance on the exact tier.
- **OQ-2 (resolved 2026-09-15):** flag-as-parameter; enum untouched
  (§4.3).
- **OQ-3 (resolved 2026-09-15):** bending residuals are out of contract
  (D2) — no bending checks, no warning property.
- **OQ-4 (resolved 2026-09-15):** names fixed as
  `IsotropicEquivalent` / `ApproximateIsotropicEquivalent`; "QI" is the
  informal prose shorthand, never a property or type name.
- **OQ-5 (accepted default 2026-09-15):** a QI side enters the literal
  combined record at nominal angles, rotation 0 — the record stays a
  truthful physical layup record; no meaningless angle is invented.
- **OQ-6 (accepted default 2026-09-15):** combined laminates carry a
  **derived read-only** `IsotropicEquivalent` (= all sides declared);
  the combined stack cannot be more isotropic than its sides.
- **OQ-7 sandwich QI presentation (new, grill 2026-09-15):** QI facesheets
  + isotropic foam core passes the membrane check numerically but the
  monolithic-plate substitution distorts bending by an order of
  magnitude. Phase 1 excludes cores (D6); revisit with a deliberate
  sandwich export shape later.
- **OQ-8 approximate-tier budget vs the 45°-doubled family (resolved
  2026-09-16, user decision):** the provisional 5%-of-A₁₁ budget
  rejected the 45°-doubled stack `[0/2×45/90]s` (measured A66 residual
  ≈15% of A₁₁). The budget is widened to **20% of A₁₁** as an interim
  value so the stack is admitted for now; the exact tier stays at 1e-6
  untouched. Revisit if the intended "nearly balanced" population
  changes.

## 12. Implementation order

1. **Mechanics:** `merge_clt_isotropic` + `validate_quasi_isotropic` +
   `QuasiIsotropicError` in `mechanics/stack_model.py` (§4). Pure numpy,
   FreeCAD-free.
2. **Mechanics unit tests** (§7.1) — red→green on the pure layer before
   any feature wiring (validation core runs FreeCAD-free, §7.0 tier A;
   the merge tests run under `FreeCADCmd`, §7.0 tier B).
3. **Objects:** `CompositeLaminate` dataclass flag + `get_layers` routing
   (§5.1, §4.3).
4. **Features:** `IsotropicEquivalent` + `ApproximateIsotropicEquivalent`
   on `Composite::Laminate`, error contract wiring, `CompositeShell`
   drape bypass + loud drape-LCS failure (§5.2, §5.3). Include the
   small dedup found in the research pass: delete the duplicate
   `is_composite_shell` from `features/PlaceDart.py` (identical body to
   the canonical `features/CompositeShell.py:60` — six modules already
   import from there) and import the canonical one; verified by
   `test_place_dart.py` + the `texture_plan` example. The new
   `is_isotropic_shell` lives next to the canonical definition.
5. **Feature tests** (§7.2, §7.3) + example update (§8.1); entry-point
   guards for TexturePlan / AlignFibreRosette and the render fallback.
6. **Composition (D8, §5.4):** seam/stiffener wiring relaxation,
   `_side_layers` zero-rotation for QI sides, derived combined flag +
   re-validation, `_WebRosette` skip; composition tests (§7.4).
7. **Examples:** stiffener panel QI (§8.2) and QI seam (§8.4)
   registered in `registry.py`; composition scenario coverage via the
   example runner.
8. **FEM provider** (§6.1): orientation-provider skip, single-layer
   plain section; material writer already ISO-capable (verified).
9. **FEM provider tests** (§7.5: provider behaviour, failure-provider
   guard, section/orientation negative control) + flat-plate companion
   example (§8.3) registered in `registry.py`.
10. **End-to-end FEM test** (§7.6, stiffener panel case) with
    cross-validation run; fix remaining OQ decisions as encountered.
11. **Extras:** curved-surface demo (§8.5) and export-time benchmark
    script (§8.6) — demo value, no CI gate.
12. **Docs:** `CONTEXT.md` terminology additions; this PRD's status →
    implemented.
13. **Build hygiene:** `compositeexamples/CMakeLists.txt` is empty
    (verified) — no per-file install edits are needed for new examples;
    registration in `registry.py` is the only wiring. What *is* required
    per the `freecad-dev` skill: `build-install-freecad.sh` (confirm
    `=== Done ===`) then purge stale `.pyc` under
    `build/debug/Mod/Composites/` before any runtime verification.
---

## Appendix A — verified code facts (research pass 2026-09-15)

Everything below was read in source; signatures and behaviours are as
implemented today, not as proposed. Where the plan changes one of these
facts, the change is called out in §5/§6.

### A.1 Model dataclasses (`objects/`)

- `Lamina` (dataclass): `core: bool = False`, `thickness: float = 1.0`;
  carries the static `set_missing_child_props(parent, children, items)`
  helper (used by `CompositeLaminate.get_layers` to propagate
  `volume_fraction_fibre` / `material_matrix` to children that have the
  attribute but no value). `get_layers()` returns `[self]`.
- `Ply(Lamina)`: adds `orientation: float = 0`.
- `HomogeneousLamina(Ply)`: adds `material: dict`, `orientation_display`.
  `description` = material `Name`, **plus `format_orientation(...)` only
  when `is_orthotropic(material)`** — an isotropic merged layer
  therefore prints as a plain name (e.g. `LaminateQI`), no angle suffix.
  `get_product()` yields the BOM `(description thickness, 0)` entry.
- `Fabric(Ply)`: `weave`, `material_fibre`, `volume_fraction_fibre`;
  thickness ⇄ area-density conversions live here.
- `SimpleFabric.get_plies()` expands weave families into real plies
  (`WeaveType.UD → [0]`, `BIAX090 → [0, 90]`, `BIAX45 → [45, −45]`,
  `TRIAX* → [0, θ, 90, −θ, 0]`), normalising each orientation through
  `normalise_orientation`. Note the TRIAX expansions are **assymmetric**
  families with doubled 0° — relevant only if a woven QI stack is ever
  declared; phase 1 QI tests use UD plies.
- `Laminate.get_layers(model_type)` (objects/laminate.py): recurses into
  child `get_layers`, then `expand_symmetry(layers, self.symmetry)`,
  then `calc_stack_model(prefix, model_type, expanded_layers)`, then
  sets `self.thickness` from the merged result. The QI branch (§4.3)
  hooks in exactly here: same expansion, different merge.

### A.2 Material properties (`mechanics/material_properties.py`)

- Unit conversion is **FreeCAD-dependent** (`from FreeCAD import Units`)
  — the dict extraction runs quantities through
  `Units.Quantity(val).getValueAs(units)`. Units used: MPa for moduli,
  `t/mm^3` for density, dimensionless for Poisson ratios. **Implication:
  the "pure numpy, FreeCAD-free" claim for §4 holds only for
  `validate_quasi_isotropic`; `merge_clt_isotropic` imports FreeCAD via
  this module** (same as `merge_clt` today). Tier-A tests (§7.0) can
  still run headless in FreeCADCmd; truly FreeCAD-free coverage is the
  validation function alone.
- `is_orthotropic(material)` = presence of key `"YoungsModulusX"` — the
  isotropic/orthotropic dispatch everywhere (writer included) keys on
  this single key, so `merge_clt_isotropic` must simply **not emit**
  that key.
- `material_from_dict(mat, orthotropic=False)` copies only the keys
  present in `mat` (`iso_items`: `YoungsModulus`, `PoissonRatio`,
  `Density`) — missing keys are silently skipped, so a forgotten
  `Density` yields a dict without density that fails later at the
  writer (`write_lamina_material_ccx` indexes `mat['Density']`
  directly). `merge_clt_isotropic` must set Density explicitly.
- `merge_clt` density: thickness-fraction-weighted (`p_k = t_k/T`),
  consistent with the D3 plan to reuse it.

### A.3 Composition wiring (`features/SeamCompositeLaminate.py`, `features/StiffenerCompositeShell.py`)

**SCL object shape.** `SeamCompositeLaminateFP(CompositeLaminateFP)`:
`Master` / `Attachment` are visible `PropertyLinkGlobal`; `SeamRegion`,
`MasterTransfer`, `AttachmentTransfer` are **`PropertyLinkHidden`** —
back-references/solved-value refs kept hidden specifically to avoid
shell→SCL→transfer→shell DAG cycles (known-issue #9). Outputs:
`EffectiveOffsetAngle` (read-only `PropertyAngle`) and `SideAngleReport`
(read-only `PropertyMap`). `Symmetry` pinned `Assymmetric`
(read-only + hidden); `Layers` read-only. **The QI derived flag must be
read-only the same way, and must not become a visible DAG link
dependency on the sides' laminate flags** — read it via `getattr` in
execute, not as a link.

**`_validate_wiring` today** requires, in order: Master/Attachment are
CompositeShells (via `is_composite_shell`, `features/CompositeShell.py:60`);
both transfers are rosettes (proxy-type check:
`Composite::Rosette` or `Composite::TransferRosette` — TypeId checks do
not match these `Part::FeaturePython` features); SeamRegion is a
CompositeShell; both sides have laminate layers; both sides share a
boundary edge with the seam region (`TransferRosetteFP._shared_edge` on
live support geometry). **QI change (§5.4): the transfer requirement
becomes conditional** — a side whose laminate is QI may omit its
transfer; the edge checks stay (they are geometry, not orientation).

**`_seam_angles` / `_update_angle_outputs`** read
`MasterTransfer.Angle.Value` / `AttachmentTransfer.Angle.Value`
unconditionally and write both output properties. QI sides need
`None`-tolerant reads and `n/a` entries in `SideAngleReport`;
`EffectiveOffsetAngle` is only meaningful when both sides are draped.

**Stiffener flow, exact roles.** `_ensure_combined_laminate` wires the
foot SCL as: **Master = panel** (stays whole), **Attachment = web
shell** (stiffener's own laminate), SeamRegion = foot shell;
`MasterTransfer` = `_PanelFootTransfer` (`TransferRosetteFP` — its solve
seeds the foot shell's drape and it becomes the foot shell's Rosette);
`AttachmentTransfer` = `_StiffenerFootTransfer`
(`AnalysisTransferRosetteFP` — analysis only, never the foot's
Rosette). `CombinationModel` is forced to `StackAttachmentOverMaster`
(a wiring choice of this flow; the seam flow's default
`StackMasterOverAttachment` is untouched). Resin is assigned **before**
the references — wiring the last visible ref fires the SCL's onChanged
recompute, and it must not run against an empty resin (transient
traceback gotcha). **QI mapping:** the *Attachment* side is the QI web →
its analysis transfer (`_StiffenerFootTransfer`) is meaningless when the
web is isotropic and should be skipped in that case; the *Master* (panel)
keeps its transfer whenever draped.

**Correction to §5.4/§7.4 as drafted:** `validate_composite_wiring`
does **not** raise on a missing stiffener rosette — a missing rosette is
the normal fresh-build state and the flow **auto-creates
`_WebRosette`** (`_ensure_web_rosette`), never overwriting a
user-linked one; only a *linked non-rosette* raises. The real QI change
is therefore: **skip the auto-creation** when the web laminate is QI
(leave `fp.Rosette = None`), and skip `_ensure_draped(web_shell)`.
`stiffener_claimed_children` already tolerates absent names (resolves
to None, skipped) — a web rosette that is legitimately never created
needs no change there.

**Direct-drive gotcha.** `_ensure_draped(shell)` (stiffener flow) calls
`shell.Proxy.execute(shell)` directly — "a direct drive is the only
reliable way inside another object's execute". The QI structural bypass
(D4) must therefore live **inside `CompositeShell.execute`** (check the
laminate flag before `_run_drape_sync`), not only in the protocol
functions — otherwise the stiffener flow's direct drive would re-enter
the drape path.

**Freshness/fingerprint.** `_flow_fingerprint` hashes the sweep shell
fingerprint plus the `Laminate`/`Rosette` **names**; a rosette-less QI
stiffener hashes `Rosette → "None"` — fine, but flipping a laminate's
QI declaration does **not** change the flow fingerprint (only the
laminate link name is hashed) — the laminate's own recompute (§5.1
validation) must propagate the change to dependent shells (it will,
since the shells link the laminate).

**Visibility order.** `ensure_stiffener_shells_visible` runs *after*
the creating recompute (visibility set in-execute is overridden when
the recompute settles); the foot shell only shows when the joint
exists. The QI variants must go through the same post-recompute
visibility path — no new visibility logic.

**Duplicate helper note:** `is_composite_shell` exists in both
`features/CompositeShell.py` and `features/PlaceDart.py` — the new
`is_isotropic_shell` helper should live next to the former (canonical)
and the D7 guards should import from there, not add a third copy.

### A.4 Examples and test infrastructure

**Registry/runner contract** (`compositeexamples/registry.py`,
`runner.py`): `EXAMPLES` is a plain dict of
`id → {"module": ".examples.<name>", "name": "<label>"}`; adding an
example is one dict entry (no CMakeLists change — that applies to the
build-dir sync, not the registry). `get_example_module` raises with the
available list on unknown ids. The runner contract is a single function:

```python
def build(doc=None, run_solver=False, **kwargs) -> result-dict
```

`runner.run(example_id, run_solver=..., doc=..., **build_kwargs)`
forwards keyword arguments straight to `build` — so the §8.2
`panel_qi` variant needs **no second example module and no registry
entry of its own**: tests call `runner.run("quasi_iso_stiffener_panel",
panel_qi=True)`. The existing `quasi_iso_laminate_plate.build` already
follows this contract (`_ensure_document` / `_maybe_run_solver`
helpers).

**`test_compositeexamples.py` conventions:**
`TestCompositeExamplesSmoke` builds real geometry per test and saves
`_saved_doc`; `test_all_examples_build` sweeps every registered example
(§8 entries are picked up automatically once registered). GUI-dependent
assertions follow the `GuiUp` guard idiom —
`if not getattr(FreeCAD, "GuiUp", False): self.skipTest("GUI not
available — scene graph requires MCP/GUI mode")` — so the same module
runs headless (GUI tests self-skip) and in MCP/GUI sessions. The
`test_conical_panel_full_pipeline_round_trip` test is the existing
example-level FEM pattern (`runner.run(..., run_solver=True)`) the §7.6
e2e follows.

**Provider-test headless pattern** (`test_drape_laminate_provider.py`):
registration is tested by **injecting a fake
`femtools.fem_extension_registry` module into `sys.modules`**, calling
`register_drape_laminate_providers()`, capturing the registered
provider callables, and restoring the module in a `finally`. The §7.5
QI provider tests follow the same pattern: capture the providers, then
exercise `shell_orientation_provider` / `shell_section_provider` with a
small real femmesh — the mock boundary is the FEM registry, never the
Composites objects.

**FEM entry to be exercised by §7.6:** the conical-panel example
(`examples/conical_panel_segment.py`) already drives drape → FEM →
CalculiX headless (`run_solver=True`); the QI e2e can reuse its
analysis-construction helpers rather than re-deriving them.

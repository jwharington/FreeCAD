# Orientation test audit — Composites workbench

**Date:** 2026-09-16 · **Branch:** `fem-unified` · **Repo:** `/home/jmw/opt/FreeCAD`
**Status:** read-only audit — no code changed.
**Trigger:** the mixed QI stiffener panel renders a fibre-orientation field
that is discontinuous across the web/foot, and the foot's orientation does
not match the panel's — while the whole test suite is green.
**Scope:** every test module in `src/Mod/Composites/compositestests/` that
touches orientation, draping, rosettes, or UV.

## 1. Method — assertion-strength taxonomy

| level | meaning | failure it can catch |
|---|---|---|
| **L0** presence | is it set / draped / is a keyword present | a missing feature, an unset property |
| **L1** provenance | where a frame came from; counts; structure | wrong routing, wrong object |
| **L2** value | numeric angle/frame vs an **independent** reference | a wrong *value* |
| **L3** correctness | spatial continuity, derived-vs-source agreement, invariance, export/field fidelity | a wrong *field* |

**L2 only counts when the expected value is independent of the code under
test.** If the expectation is read from the same object being asserted on,
the test is a **self-reference** and grades no better than L0 for
correctness purposes; it pins plumbing. Likewise set-then-get is a
**round-trip**, and `isfinite`/range checks are **plausibility** — an
arbitrary wrong angle passes both.

## 2. Per-module findings

### `test_mechanics.py` — L2, genuinely independent ✔
- `_independent_ply_Q` (`:1558`), `_independent_qbar` (`:1573`),
  `_independent_qi_equivalent` (`:1591`) build Q / Q̄ / QI equivalents from
  textbook formulas, explicitly *not* via `shell_model`.
- `test_qi_equiv_modulus_matches_independent_clt` (`:1628`) compares the
  merged equivalent constants against that reference.

This is the only module that establishes orientation **correctness** from
an independent model. It covers the CLT/rotation maths only — nothing about
the drape field, shells, or regions.

### `test_align_fibre_scenarios.py` — one genuine L2, rest round-trip
- ✔ `test_creation_helper_wires_and_solves` (`:87`) asserts the solved
  angle is `45.0 ± 0.5` for geometry where the warp passing through
  `(60, 60)` from the seed **must** be 45° — an independent geometric
  expectation. Genuine L2.
- ✗ `test_align_fibre_rosette_different_angles` (`:107`) sets `Angle` then
  reads it back — round-trip.
- ✗ `:184`, `:195`, `:206` — `isfinite` only.

### `test_stiffener_composite_shell.py` — L2 that is self-referential ✘
The strongest-looking orientation tests here. All read their expected value
from the object under test:

- `test_stack_order_stiffener_over_panel` (`:456–459`) and
  `test_offset_fabric_plies_carry_solved_angles` (`:520–523`):
  ```python
  panel_angle = scl.MasterTransfer.Angle.Value      # from the object…
  self.assertAlmostEqual(orientations[0], panel_angle, delta=1e-6)  # …asserted on the object
  ```
  The docstring concedes the intent: *"asserted via the report, so the test
  pins the machinery without assuming the auto rosette's frame
  orientation."* It cannot detect a wrong solved angle.
- `test_effective_offset_is_the_difference_of_solved_angles` (`:~500`):
  `EffectiveOffsetAngle == stiffener_angle - panel_angle`, both read from
  `scl`.
- `test_switching_combination_model_reverses_the_blocks` (`:478`):
  structural self-comparison before/after a switch.
- `assertFalse(web.DrapeValid)` (`:977`), `assertFalse(foot.DrapeValid)`
  (`:1000`) — L0.
- **Nothing** asserts that the foot's per-ply angle equals the panel's
  *field* angle, nor that the field is continuous across the cut.

### `test_compositeexamples.py` — L0 ✘
- `DrapeValid` booleans (`:387`, `:468–469`, `:566`, `:598`, `:647`).
- Stiffener: `web_rosette is None`, `combined_isotropic`,
  `web/foot/panel_draped`, and `TYPE=ISO` / `*ORIENTATION` **keyword
  presence**.
- `panel_draped`, `foot_draped` and `combined_isotropic` are *returned by
  the example* but asserted only in the QI-panel variant, never in the
  mixed variant that exhibits the defect.
- The `*ORIENTATION` assertion passes for **any** frame content.

### `test_seam_composite_laminate.py` — report-string compare + range
- `report["master_angle_at_seam"] == "10"` (`:226`),
  `== "25"` (`:227`), `== "n/a"` (`:531–532`) — string compare of a field
  produced by the machinery.
- `layer.orientation % 180.0 == 30.0 ± 2.0` (`:389`) — plausibility band.
- No check that the seam-region field agrees with either side's.

### `test_seam_extraction.py` — L0
- `assertIs(seam_shell.Rosette, rosette)` (`:141`).

### `test_drape_laminate_provider.py` — L1 / L0
- `called_orientation[0][0] == "compositeswb.drape"` (`:143`) — provenance.
- `"COMPOSITE,ORIENTATION=" in out["material"]` (`:175`) — keyword.
- `out == {"orientation": None}` (`:211`), `"ORIENTATION=" not in …`
  (`:240`) — absence for a QI shell.
- The frames are never value-checked.

### `test_rosette_scenarios.py`, `test_rosette_types.py`, `test_rosette_integration.py` — round-trip / plausibility
- `assertAlmostEqual(rosette.Angle, angle)` after setting it — round-trip
  (`scenarios :132`, `:179`, `:195`; `types :61`, `:82`).
- `assertGreater(abs(solved_angle), 1.0)` / `assertLess(…, 89.0)`
  (`integration :146–147`) — **any** angle in (1°, 89°) passes.
- `isfinite` (`types :129–131`, `:171`).

### `test_transfer_rosette.py`, `test_transfer_rosette_scenarios.py` — L0
- `get_draper().is_valid()`, `is_transfer_rosette`, `Proxy.Type`.
  `_scenarios.py` contains **zero** orientation assertions.

### `test_place_dart.py` — L1
- `DrapeCuts` counts/identity (`:65–218`). No effect of the dart on the
  field.

### `test_g7_persistence.py` — L0 round-trip
- `DrapeValid` before/after save (`:88`, `:111`, `:171`). The reloaded
  *field values* are never compared to the originals.

### `test_meshgrid_shader_binding.py` — round-trip
- `set_offset_angle(45.0)` → `≈ radians(45)` (`:59`);
  `attach(root, tex_coords, 30.0)` → `≈ radians(30)` (`:102`).
  The expected value is the argument, not the drape field.

### `test_vp_composite_shell_shader_reload.py` — literal-value check
- `get_offset_angle(feature) == 45.0` (`:85`) — display-layer angle against
  a literal.

### `test_uv_mapping.py` — L2 for **UV**, not fibre angle
- Bounds and NaN/Inf checks (`:309–310`, `:389–390`).

### No orientation correctness
`test_laminate.py`, `test_integration_freecad.py`, `test_composite_shell.py`,
`test_stiffener.py`, `test_shader_gui.py`, `test_shader_grid_diagnostic.py`,
`test_shader_glsl_capture.py` — presence/validity only.

## 3. The three failure patterns

Every orientation assertion in the suite reduces to one of:

1. **Round-trip** — set a value, read it back (`rosette.Angle`,
   `offset_angle`). Proves the property is wired.
2. **Self-reference** — read the expected value from the object under test
   (`MasterTransfer.Angle`, the seam report strings). Proves plumbing;
   *grades nothing* about correctness.
3. **Presence / plausibility** — `DrapeValid`, `is None`, keyword in deck,
   `isfinite`, `1° < θ < 89°`.

The two exceptions (`test_mechanics` CLT closures; the 45° align-fibre
geometry test) both sit **outside** the drape/shell/region path — the exact
path where the defect lives.

## 4. What is therefore invisible to the suite today

- **(a)** a fibre field that is discontinuous across a shell/region split;
- **(b)** a derived (foot) orientation that disagrees with its source
  (panel) orientation;
- **(c)** exported `*ORIENTATION` frames that do not match the frames
  actually rendered/used;
- **(d)** a QI component perturbing the orientation of a draped neighbour;
- **(e)** the rendered weave angle, or a rosette angle, disagreeing with
  the field.

## 5. Resulting gap list

| id | measure | should live in |
|---|---|---|
| **M1** | field continuity across the web/foot split | `test_stiffener_composite_shell` / `test_compositeexamples` |
| **M2** | derived (foot) == source (panel) orientation, elementwise | `test_stiffener_composite_shell` |
| **M3** | deck `*ORIENTATION` frames match the used frames | `test_drape_laminate_provider` |
| **M4** | a QI side does not perturb the draped side (mixed == non-QI baseline) — **primary reproduction** | `test_compositeexamples` |
| **M5** | rendered weave angle == field layer angle | `test_meshgrid_shader_binding` |
| **M6** | rosette angle == field angle at the rosette | `test_rosette_integration` / `test_stiffener_composite_shell` |

Each measure must be derived from an **independent** reference (analytic
frame, textbook CLT closure, or a raw frd/solver parse) and must be **red
on current code** before any fix.

## 6. Artifacts

- This audit: `docs/orientation-test-audit-2026-09-16.md` (read-only).
- Related but **separate** defect (not this audit): the ring-stiffener web
  *coverage* problem — `compositestests/inspect_ring_stiffener_web.py`,
  `docs/investigation-ring-stiffener-web-2026-09-10.html`.

# Plan: FreeCAD Integration — UV Quality Improvements

**Date:** 2026-07-15
**Scope:** FreeCAD-specific UV mapping improvements — ViewProvider rendering, shader attachment, geometry injection, UV clamping, UV continuity
**Separation:** This covers FreeCAD integration only. The k-d tree spatial index is in `ext/docs/plan-kdtree-performance.md`.

---

## 1. Integration Architecture

### 1.1 Data Flow Overview

```
nextdrape C++ solver
    ↓ (returns tex_coords: Nx2 array of UV coordinates per node)
NextDrapeBackend.get_tex_coords()
    ↓ (rotates by -offset_angle_deg)
CompositeShell._backend.get_tex_coords()
    ↓
VPCompositeShell.load_shader()
    ↓
MeshGridShader.attach(drape_host, tex_coords, offset_angle_deg)
    ↓
SoTextureCoordinate3 injected into shader_state group
    ↓
GLSL shader reads gl_MultiTexCoord0 → draws grid lines
```

**Support surface path:**

```
CompositeShell.execute()
    ↓ build_support_surface_coin(shape, draper=shell)
        ↓ _map_uv_to_support(draper, support_verts)
            ↓ tex_coord_at_point() — bilinear interpolation per vertex
                ↓ soft_clamp() — NEW: clamp extrapolated UVs
                ↓ shared-edge averaging — NEW: reduce discontinuities
            ↓ SoTextureCoordinate3 attached to support surface geometry
    ↓ MeshGridShader._find_coin_geometry() discovers SupportSurface
    ↓ Shader renders on support surface (not drape mesh)
```

### 1.2 Key Components

| Component | File | Role |
|-----------|------|------|
| `NextDrapeBackend` | `tools/drape_backend_nextdrape.py` | C++ solver wrapper. Produces `tex_coords` (Nx2 UV per node). |
| `_RehydratedBackend` | `features/CompositeShell.py` | Transient backend from persisted JSON. Same interface. |
| `CompositeShellFP` | `features/CompositeShell.py` | FeaturePython. Stores TexCoordsJSON, orchestrates solve/rehydrate. |
| `VPCompositeShell` | `features/VPCompositeShell.py` | ViewProvider. Hosts drape_host switch, manages shader lifecycle. |
| `MeshGridShader` | `shaders/MeshGridShader.py` | Coin3D shader state builder. Injects `SoTextureCoordinate3` into scene graph. |
| `coin_geometry` | `features/coin_geometry.py` | Builds Coin3D geometry (SupportSurface + DrapecdMesh). |
| `geometry_util` | `util/geometry_util.py` | `tex_coord_at_point()` — bilinear UV interpolation. **Primary change location.** |
| `drape_task` | `compositetools/drape_task.py` | Sync drape task runner. Calls `build_drapecd_coin(wireframe=True)`. |
| `Grid_fragment_shader.glsl` | `shaders/` | Fragment shader draws grid lines from texture coords. |

### 1.3 Rendering Target Selection

Shader renders on either **support surface** or **drape mesh**, determined by `MeshGridShader._find_coin_geometry()`:

1. First, searches node named `"SupportSurface"` (priority)
2. Falls back to finding any `Coordinate3` + `IndexedFaceSet` container
3. Drape mesh wireframe (rendered as `LINES`) is fallback when no support surface exists

### 1.4 Transparency Model

`VPCompositeShell._set_shell_transparency()` sets `SoTransparencyType BLEND` (value 0.5) for per-fragment alpha blending.

---

## 2. Edge UV Clamping Plan

### 2.1 Problem

Unbounded bilinear interpolation produces extreme UV values at mesh boundaries, causing distorted grid lines.

**Root cause:** In `geometry_util.py`'s `tex_coord_at_point()`, the bilinear refinement produces UVs outside `[0,1]` for points near mesh boundaries, and there is zero clamping anywhere in the pipeline. The comment `# Texture coords are in world-space, so we don't restrict to [0,1]` reveals the flawed design assumption.

### 2.2 Solution: Soft Clamp Utility

Instead of hard-clamping (which creates discontinuities), apply a **smooth soft-clamp** that gradually attenuates extrapolation near boundaries:

```python
def soft_clamp(value, lo=0.0, hi=1.0, margin=0.1):
    """
    Soft-clamp: values within [lo, hi] pass through unchanged.
    Values within margin of the boundary are allowed to pass through
    (allowing small excursions like -0.05 or 1.05).
    Values beyond the margin are hard-clamped to lo or hi.
    """
    if value < lo - margin:
        return lo
    if value > hi + margin:
        return hi
    return value
```

**Behavior:**

| Input range | Output |
|-------------|--------|
| `[lo, hi]` (e.g., `[0, 1]`) | Pass-through unchanged |
| `[lo-margin, lo)` (e.g., `[-0.1, 0)`) | Pass-through (allows small excursion) |
| `(hi, hi+margin]` (e.g., `(1, 1.1]`) | Pass-through (allows small excursion) |
| `< lo-margin` | Hard-clamped to `lo` |
| `> hi+margin` | Hard-clamped to `hi` |

This preserves the smooth gradient UV field while preventing runaway extrapolation.

### 2.3 Implementation Location

**Primary change:** `util/geometry_util.py` — `tex_coord_at_point()` function

Specifically, modify UV computation at three points:

1. **Inside quad containment loop** (line ~202): After computing bilinear UV interpolation, apply soft-clamp to stored `(best_u, best_v)`.
2. **In nearest-quad fallback path** (line ~280): After computing `best_u, best_v` via planar projection, apply soft-clamp.
3. **Final return** (before offset angle rotation): Apply soft-clamp to final UV values.

### 2.4 Parameterization

Add configurable parameter for clamping aggressiveness:

```python
def tex_coord_at_point(
    node_positions, quads, tex_coords, point,
    offset_angle_deg=0.0,
    uv_clamp_margin=0.1,  # NEW: soft-clamp margin
) -> list[float] | None:
```

Default value `0.1` gives 10% smooth transition zone at boundary.

### 2.5 Propagation Through Call Chain

`tex_coord_at_point` is called from:

1. `geometry_util.tex_coord_at_point()` — direct caller (unit tests)
2. `features/coin_geometry.py::_map_uv_to_support()` — maps support surface vertices
3. `tools/drape_backend_nextdrape.py:NextDrapeBackend.get_tex_coord_at_point()` — delegates to geometry_util
4. `features/CompositeShell.py:_RehydratedBackend.get_tex_coord_at_point()` — delegates to geometry_util

All callers pass through shared `geometry_util.tex_coord_at_point()`, so a single change propagates everywhere.

### 2.6 Backward Compatibility

`uv_clamp_margin` parameter defaults to `0.1` — pure improvement, no existing valid use case expects unbounded extrapolation. Function signature change is backward compatible (keyword argument with default).

---

## 3. UV Discontinuity Reduction Plan

### 3.1 Problem

At quad boundaries, bilinear interpolation produces **small UV jumps** due to:

1. **Quad selection ambiguity:** Query point lies near boundary of two adjacent quads; "best quad" selection can flip between them, causing a jump in returned UV.
2. **Bilinear warping:** Bilinear interpolation is not affine-invariant, so UV field has slight curvature within each quad. At shared edges, curvature of adjacent quads may not match perfectly.
3. **Triangulated faces amplify:** Each quad rendered as two triangles (`build_drapecd_coin`), with the shared diagonal (i0→i2) as a boundary where bilinear interpolation produces inconsistent UVs.
4. **_map_uv_to_support:** Every tessellated vertex on the support surface is queried independently. Adjacent tessellation vertices lie close together in physical space but may map to different quads, producing UV jumps.

### 3.2 Strategy A: Edge-Aware Quad Selection (Preferred)

Modify "best quad" selection criterion in `tex_coord_at_point()` to prefer the quad whose UV is closest to the **expected linear interpolation** along the shared edge.

**Mechanism:**

- After identifying candidate quad (minimum distance), compute its UV.
- For the winning quad, also check neighboring quads sharing an edge.
- If neighbor's predicted UV at the query point is within tolerance, average the UVs.

```python
# Inside tex_coord_at_point(), after finding best_quad:
if best_quad is not None:
    best_uv = bilinear_interpolation(best_quad, point)
    
    # Check neighboring quads
    for neighbor in get_neighbors(best_quad):
        neighbor_uv = bilinear_interpolation(neighbor, point)
        if uv_distance(best_uv, neighbor_uv) < threshold:
            # Average UVs — reduces jump
            best_uv = average(best_uv, neighbor_uv)
```

### 3.3 Strategy B: Lightweight UV Smoothing (Secondary)

One-pass Laplacian smoothing applied in `coin_geometry.py::_map_uv_to_support()`:

```python
def _smooth_uv_field(uvs, quads, node_positions, alpha=0.3):
    """One-pass Laplacian smoothing of UV field.
    
    For each unique vertex, average UVs of neighbors connected via quad edges.
    """
    smoothed = uvs.copy()
    for v in unique_vertices:
        neighbors = get_connected_vertices(v, quads)
        if neighbors:
            smoothed[v] = (1-alpha) * uvs[v] + alpha * mean(uvs[n] for n in neighbors)
    return smoothed
```

**Trade-off:** Adds O(N) post-processing pass. May slightly distort perfect node-to-node UV matching.

### 3.4 Recommended Approach

Implement **Strategy A** first (edge-aware selection). This directly addresses the root cause without adding overhead. Strategy B added later only if residual discontinuities are observed in practice.

### 3.5 Implementation Details for Strategy A

In `geometry_util.py`, within the quad containment loop:

1. Maintain `best_uv` alongside `best_quad` and `best_dist`.
2. When evaluating a new candidate quad:
   - Compute its UV via bilinear interpolation.
   - Compare `best_uv` using Euclidean distance in UV space.
   - Only replace if BOTH spatial distance AND UV distance improve.

This ensures that even if two quads are equally close in 3D space, the one producing the more consistent UV wins.

---

## 4. Implementation Steps

### Phase 1: Edge UV Clamping (Foundation)

**Files affected:** `util/geometry_util.py`

#### Step 1.1: Add `soft_clamp` utility function

```python
def soft_clamp(value, lo=0.0, hi=1.0, margin=0.1):
    """Allow small excursions beyond [lo, hi] within margin."""
    if value < lo - margin:
        return lo
    if value > hi + margin:
        return hi
    return value
```

#### Step 1.2: Integrate soft-clamp into `tex_coord_at_point()`

Apply at three locations:

1. After bilinear interpolation computes `uv` → `uv[0] = soft_clamp(uv[0]); uv[1] = soft_clamp(uv[1])`
2. In nearest-quad fallback path → same
3. Final return (before offset angle rotation) → `best_u = soft_clamp(best_u); best_v = soft_clamp(best_v)`

#### Step 1.3: Add `uv_clamp_margin` parameter

Add to function signature with default `0.1`. All callers pass through shared function, so no propagation needed.

---

### Phase 2: UV Discontinuity Reduction

**Files affected:** `util/geometry_util.py`, `features/coin_geometry.py`

#### Step 2.1: Edge-consistent quad selection

In `tex_coord_at_point()`, after finding the best quad by spatial distance:

1. Compute the UV for the best quad.
2. For each neighboring quad sharing an edge with the best quad:
   a. Check if the query point projects closer to that neighbor's edge.
   b. If so, compute the UV from the neighbor.
   c. Average the UVs from both quads weighted by proximity.

This ensures that points on shared edges get consistent UVs regardless of which quad is selected first.

#### Step 2.2: UV smoothing pass for support surface (optional)

In `coin_geometry.py::_map_uv_to_support()`:

```python
def _map_uv_to_support(draper, support_verts):
    # ... existing code to compute initial UVs ...
    
    # Optional: lightweight UV smoothing for continuity
    uv_smoothed = _smooth_uv_field(uv_coords, quads, node_positions)
    return uv_smoothed
```

---

### Phase 3: Shader Performance Optimization

**Files affected:** `features/VPCompositeShell.py`, `shaders/MeshGridShader.py`

#### Step 3.1: Reduce unnecessary shader reloads

Currently, `load_shader()` is called on many property changes. Optimize to only reload when necessary:

- `DisplayLayer` → only update `offset_angle` (already partially done)
- `Darken` → update shader parameter directly, no reload
- `ScreenSpaceGrid` → detach/load (current behavior, acceptable)

#### Step 3.2: Cache UV computation

The `get_tex_coords()` call in `load_shader()` is expensive. Cache the result and only recompute when:

- The underlying drape solve result changes
- The offset angle changes

---

### Phase 4: Testing

**Files affected:** New test file, existing `test_uv_mapping.py`

#### Step 4.1: Unit tests for soft-clamp

Add to `test_uv_mapping.py`:

```python
class TestSoftClamp(unittest.TestCase):
    def test_value_in_range_passthrough(self):
        self.assertEqual(soft_clamp(0.5, margin=0.1), 0.5)
    
    def test_value_at_boundary_passthrough(self):
        self.assertEqual(soft_clamp(0.0, margin=0.1), 0.0)
        self.assertEqual(soft_clamp(1.0, margin=0.1), 1.0)
    
    def test_small_excursion_allowed(self):
        self.assertAlmostEqual(soft_clamp(-0.05, margin=0.1), -0.05)
        self.assertAlmostEqual(soft_clamp(1.05, margin=0.1), 1.05)
    
    def test_large_excursion_clamped(self):
        self.assertEqual(soft_clamp(-0.5, margin=0.1), 0.0)
        self.assertEqual(soft_clamp(2.0, margin=0.1), 1.0)
```

#### Step 4.2: Edge UV extrapolation test

```python
def test_edge_uv_not_extreme(self):
    """UVs at mesh boundary should not extrapolate to extreme values."""
    draper = GridDraper(nx=3, ny=3)
    edge_points = [
        [0.0, 0.0, 0.0],   # corner
        [0.5, 0.0, 0.0],   # edge midpoint
        [0.0, 0.5, 0.0],   # edge midpoint
        [0.0, 1.0, 0.0],   # corner
        [1.0, 1.0, 0.0],   # corner
    ]
    result = _map_uv_to_support(draper, edge_points)
    max_abs_uv = max(abs(u) for uv in result for u in uv)
    self.assertLess(max_abs_uv, 1.1,  # margin=0.1
        f"Edge UV extrapolation too large: {max_abs_uv}")
```

#### Step 4.3: Discontinuity test

```python
def test_uv_discontinuity_at_shared_edge(self):
    """UV difference across shared edge should be minimal."""
    # Query points along shared edge from both sides
    uv_left = tex_coord_at_point(nodes, quads, tex_coords, [1.0, 0.49, 0.0])
    uv_right = tex_coord_at_point(nodes, quads, tex_coords, [1.0, 0.51, 0.0])
    diff = np.linalg.norm(np.array(uv_left) - np.array(uv_right))
    self.assertLess(diff, 0.05,
        f"UV discontinuity at shared edge: {diff}")
```

#### Step 4.4: Visual verification checklist

When testing manually in FreeCAD GUI:

1. **Create a composite shell** on a cylindrical support surface
2. **Observe grid lines** — they should follow warp (axial) and weft (circumferential) directions
3. **Check mesh edges** — grid lines should terminate cleanly, not wrap around or stretch
4. **Zoom in/out** — screen-space grid should maintain consistent pixel spacing
5. **Change display layer** — offset angle rotation should work correctly
6. **Toggle transparency** — shell should be semi-transparent when shader is active

---

### Phase 5: Integration with Existing Systems

#### Step 5.1: Update `_map_uv_to_support()` in `coin_geometry.py`

Ensure the support surface UV mapping also benefits from soft-clamping. Since `_map_uv_to_support()` calls `tex_coord_at_point()` internally, the soft-clamp from Phase 1 will propagate automatically.

#### Step 5.2: Verify shader rendering with clamped UVs

The GLSL fragment shader uses `mod(parameter, 1.0)` to create periodic grid lines. With clamped UVs near `[0,1]`, this should produce clean grid termination at mesh boundaries without wrapping artifacts.

Verify:

- Grid lines terminate cleanly at mesh edges
- No duplicate grid lines appear from UV wrapping
- Grid spacing remains consistent near boundaries

---

## 5. Gates (Verification Criteria)

### Gate 1: Edge UV Clamping

- [ ] All UVs at mesh boundary nodes are within `[-0.1, 1.1]` (margin=0.1)
- [ ] UVs far outside the mesh (≥0.5 units away) are clamped to `[0, 1]`
- [ ] Small excursions (≤0.1 units) are allowed to pass through
- [ ] No NaN or Inf values in UV arrays
- [ ] Existing tests in `test_uv_mapping.py` still pass

### Gate 2: UV Continuity

- [ ] UV difference between adjacent sample points ≤ grid spacing
- [ ] No UV jumps larger than 0.05 at shared quad edges
- [ ] Node UVs still match their `tex_coords` exactly (no regression)
- [ ] Warped quad continuity test still passes

### Gate 3: Shader Rendering

- [ ] Grid lines terminate cleanly at mesh boundaries
- [ ] No duplicate/wrapped grid lines near edges
- [ ] Grid spacing consistent within 10% near boundaries
- [ ] Shader attach/detach cycle works correctly after UV changes

### Gate 4: Performance

- [ ] `tex_coord_at_point()` execution time unchanged (±5%)
- [ ] `load_shader()` call count reduced (fewer unnecessary reloads)
- [ ] No memory leaks in shader attach/detach cycles

---

## 6. Commit Points

### Commit 1: Soft Clamp Foundation

**Message:** `feat(composites): add soft_clamp utility for UV boundary handling`

**Changes:**
- `util/geometry_util.py`: Add `soft_clamp()` function
- `util/geometry_util.py`: Integrate soft-clamp into `tex_coord_at_point()` at 3 locations
- `compositestests/test_uv_mapping.py`: Add `TestSoftClamp` unit tests

**Rationale:** Standalone utility addition, no behavioral change to existing callers yet.

---

### Commit 2: UV Clamping Applied

**Message:** `fix(composites): clamp UV extrapolation at mesh boundaries in tex_coord_at_point`

**Changes:**
- `util/geometry_util.py`: Apply soft-clamp to bilinear interpolation results
- `util/geometry_util.py`: Apply soft-clamp to nearest-quad fallback results
- `util/geometry_util.py`: Apply soft-clamp before offset angle rotation
- `util/geometry_util.py`: Add `uv_clamp_margin` parameter
- `compositestests/test_uv_mapping.py`: Add edge UV bound tests

**Rationale:** Core fix for edge UV extrapolation.

---

### Commit 3: UV Continuity Improvement

**Message:** `enhance(composites): improve UV continuity at quad boundaries`

**Changes:**
- `util/geometry_util.py`: Edge-aware quad selection in `tex_coord_at_point()`
- `util/geometry_util.py`: UV averaging for shared-edge points
- `compositestests/test_uv_mapping.py`: Add discontinuity tests

**Rationale:** Addresses UV jumps at shared edges.

---

### Commit 4: Shader Performance

**Message:** `perf(composites): reduce unnecessary shader reloads in VPCompositeShell`

**Changes:**
- `features/VPCompositeShell.py`: Optimize `onChanged()` to minimize `reload_shader()` calls
- `features/VPCompositeShell.py`: Cache UV computation results
- `compositestests/test_vp_composite_shell_shader_reload.py`: Update/add tests

**Rationale:** Addresses the 37× slowdown in GUI mode.

---

### Commit 5: Integration Tests

**Message:** `test(composites): add integration tests for UV mapping improvements`

**Changes:**
- New tests in `compositestests/test_integration_freecad.py`
- Visual verification checklist in test docstrings

**Rationale:** End-to-end verification of all changes.

---

## 7. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Soft-clamp breaks existing visual appearance | Low | Margin parameter allows tuning; gradual rollout |
| UV smoothing distorts node-to-node UV matching | Medium | Make smoothing optional (alpha=0); test node UV equality |
| Shader reload optimization introduces bugs | Medium | Thorough regression testing of attach/detach cycles |
| Performance gains insufficient | Medium | Profile-guided optimization; consider C++ path for UV lookup |

---

## 8. Critical Files for Implementation

1. **`src/Mod/Composites/util/geometry_util.py`** — `tex_coord_at_point()` is the central UV computation function. All UV clamping and continuity fixes originate here.

2. **`src/Mod/Composites/features/VPCompositeShell.py`** — ViewProvider managing shader lifecycle. Performance optimizations and reload reduction go here.

3. **`src/Mod/Composites/shaders/MeshGridShader.py`** — Shader state management. Understanding `_find_coin_geometry()` and attach/detach semantics is essential.

4. **`src/Mod/Composites/features/coin_geometry.py`** — `build_support_surface_coin()` and `_map_uv_to_support()` inject UVs into the support surface geometry.

5. **`src/Mod/Composites/compositestests/test_uv_mapping.py`** — Existing UV tests provide the test scaffolding for regression and new tests.

---

## 9. Appendix A: Current UV Pipeline Call Graph

```
CompositeShell.execute()
├── _run_drape_sync()
│   └── run_drape_task()
│       ├── NextDrapeBackend._run_solve()
│       │   └── C++ solver → tex_coords (Nx2)
│       ├── NextDrapeBackend.get_tex_coords()
│       │   └── rotate by -offset_angle
│       └── build_drapecd_coin(node_positions, quads, wireframe=True)
│
├── _inject_drape_geometry()
│   ├── build_support_surface_coin(shape, draper=shell)
│   │   └── _map_uv_to_support(draper, verts)
│   │       └── tex_coord_at_point() ← CLAMP HERE
│   └── vp.Proxy.reload_shader()
│       └── vp.Proxy.load_shader()
│           └── backend.get_tex_coords()
│               └── MeshGridShader.attach(drape_host, tex_coords, offset_angle)
│                   └── _find_coin_geometry(root) → SupportSurface or drape mesh
│
└── _persist_solve_data()
    └── save TexCoordsJSON, NodePositionsJSON, QuadsJSON, StrainsJSON
```

## Appendix B: Known Issues Documented in Code

1. **Double-attach bug** (fixed): Shader state groups accumulating across reloads
2. **Chevron artifact** (fixed): `SoTextureCoordinateBinding.PER_VERTEX` vs `PER_VERTEX_INDEXED`
3. **37× slowdown in GUI mode**: Shader attach/detach on every property change
4. **Edge UV extrapolation**: Unbounded bilinear interpolation at mesh boundaries
5. **UV discontinuity at quad boundaries**: Ambiguous quad selection near shared edges
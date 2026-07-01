# Texture Coordinate Mapping Debug Journal

**Started:** 2026-06-30  
**Status:** In Progress — Grid lines still diagonal

---

## Problem Statement

The GLSL shader renders on DrapeMesh geometry but texture coordinates don't align with mesh vertices — grid lines appear diagonal across the conical surface instead of following warp/weft directions (vertical along cone length, horizontal around circumference).

---

## Timeline of Investigation

### Phase 1: Initial Diagnosis (Handover Context)

**Background from handover document:**
- Mesh.Mesh.addFacet() deduplicates vertices (12,907 draper nodes → ~11,864 mesh points)
- This broke 1:1 correspondence between texcoords and mesh vertices
- Decision: Use Coin3D geometry directly to preserve 1:1 mapping

**Actions taken:**
- Rewrote `_build_drapecd_mesh()` to build Coin3D geometry (SoCoordinate3 + SoIndexedFaceSet) directly from node_positions/quads
- Removed position-based texcoord remapping from `load_shader()`
- Added DrapePitch property to CompositeShell (default 5.0mm)
- Wired DrapePitch through to drape backend via `_MeshWithPitch` wrapper
- Fixed import path from `.compositetools` to `..compositetools`
- Replaced threaded `DrapeTask` with synchronous `run_drape_task()` (Qt queued connection failures in headless mode)
- Updated `MeshGridShader.attach()` to find Coin3D geometry via `_find_coin_geometry()` and move it into shader state group
- Fixed SWIG compatibility issues (pointer comparison, type name matching, `getLength()` casting)

**Results:**
- Unit tests pass (3/3) — geometry building, shader attach, texcoord 1:1 mapping
- Full example runs — drape completes (163 rounds, 12907 nodes), shader activates
- BUT: Grid lines still diagonal

### Phase 2: Coin3D Geometry Placement Bug

**Discovery:**
The Coin3D geometry was being injected into the DrapeMesh ViewObject's RootNode by `_inject_coin_geometry()`, but the `attach()` method's reorder logic was placing it BACK at the root level instead of keeping it inside the shader state group.

**Root cause:**
1. `_inject_coin_geometry()` adds Coin3D to root at index N
2. `attach()` finds Coin3D, adds it to shader group (`self.grp.addChild(coin_geo)`)
3. `attach()` removes Coin3D from root (`_remove_node_from_parent`)
4. **BUG:** Reorder logic removes children after switch_idx, adds shader group, then RESTORES the removed children — including the Coin3D which was already moved

**Fix applied:**
Changed reorder logic to track WHICH children were actually removed (with their indices), so only those are restored. Children already moved (like Coin3D inside shader group) aren't in the `remaining` list and won't be restored.

```python
# Before: removed children, added shader group, restored ALL children after switch_idx
# After: only restore children that were ACTUALLY removed
remaining = []
for i in range(int(self.root.getNumChildren()) - 1, switch_idx, -1):
    c = self.root.getChild(i)
    if c is not None:
        self.root.removeChild(c)
        remaining.append((i, c))  # Track index + child
self.root.addChild(self.grp)
for _, c in sorted(remaining, key=lambda x: -x[0]):
    self.root.addChild(c)  # Only restore actually-removed children
```

### Phase 3: Double-Attach Bug

**Discovery:**
Every property change triggered `reload_shader()` → `remove_shader()` → `load_shader()`, which:
- Called `detach()` → reset `_attached = False`
- Deleted `grid_shader` attribute
- Created new `grid_shader` → attached again

This caused:
- Multiple shader state groups in the scene graph
- The first shader group (with Coin3D) was removed when the second was created
- The second shader group had no Coin3D (attach hadn't found it yet)

**Fixes applied:**

1. **Don't delete `grid_shader` in `remove_shader()`** — just detach. Preserves `_attached` flag between reloads.

```python
# Before: delattr(self, "grid_shader")  # Force recreation
# After: Just detach, keep grid_shader alive
```

2. **Added scene graph presence check in `load_shader()`** — skip attach if Coin3D is already inside shader group:

```python
if hasattr(self, "grid_shader") and self.grid_shader:
    grp = getattr(self.grid_shader, 'grp', None)
    if grp:
        has_coin = any(
            "Coordinate3" in str(c.getTypeId().getName())
            for i in range(int(grp.getNumChildren()))
            for c in [grp.getChild(i)] if c
        )
        if has_coin:
            return  # Already attached
```

### Phase 4: Texcoord Alignment Verification

**Verification results:**
- U vs Z correlation: **0.9998** (strong positive)
- V vs -Y correlation: **0.9969** (strong negative)
- textureCoordIndex matches coordIndex: **100%**
- No orphan Coordinate3 at root level: **Confirmed**
- Mesh topology: 50% U-edges, 50% V-edges, 0% mixed — **CORRECT**

**Detailed line tracing:**
- U-edge line from node 0: U varies monotonically (0→-150), V constant=0, nodes move along Z axis (455→306) ✓
- V-edge line from node 0: V varies monotonically (0→-150), U constant=0, nodes move along Y axis (0→144) ✓

**Conclusion:** Mesh topology IS aligned with texcoords. Grid lines SHOULD follow warp/weft directions.

### Phase 5: Current State — Grid Still Diagonal

**Scene graph structure (verified correct):**
```
Root children: 6
  [0] SoFCTransform
  [1] PickStyle
  [2] Switch (Mesh::Feature geometry)
  [3] Group (shader state)
      [0] MaterialBinding
      [1] Texture2
      [2] TextureCoordinateBinding
      [3] TextureCoordinate2  ← 12907 texcoords
      [4] TextureMatrixTransform
      [5] ShaderProgram
      [6] Separator (Coin3D geometry)
          [0] Coordinate3     ← 12907 vertices
          [1] IndexedFaceSet  ← 92841 coordIndices
  [4] Separator (annotation)
  [5] Group (old shader state — harmless leftover)
```

**TextureCoordinate2 values (PROBLEMATIC):**
```
[0]: (0.00, 0.00, -5.00)
[1]: (-5.00, 0.00, 0.00)
[2]: (0.00, -5.00, 0.00)
[3]: (0.00, 5.00, 5.00)
[4]: (5.00, 0.00, -5.00)
```

**Observation:** The third component (z) is varying (-5, 0, 0, 5, -5), which shouldn't be there for 2D texcoords. However, `SoTextureCoordinate2` uses `SoMFVec2f` internally (2D vectors), so the third component is an artifact of Python bindings returning SbVec3f instead of SbVec2f.

**Shader code:**
```glsl
vec2 uv = gl_TexCoord[0].st;  // Uses only s,t components
```

The shader only uses `st` components, so the garbage third component shouldn't affect rendering.

---

## Active Hypotheses

### H1: TextureMatrixTransform is corrupting texcoords
**Evidence:** There's a `TextureMatrixTransform` node at group[3][4] that might be applying unwanted transformations.

**Test:** Check the matrix values and temporarily remove/disable the node.

**Status:** Not yet tested

### H2: Shader uniforms (x_scale, y_scale, z_scale) are causing distortion
**Evidence:** Uniforms are all set to 0.2, which might be causing non-uniform scaling in the grid pattern.

**Test:** Try setting all scales to 1.0 or removing scale factors from the shader.

**Status:** Not yet tested

### H3: The fract() pattern in the shader creates diagonal lines for certain texcoord ranges
**Evidence:** The shader uses `fract(uv / spacing - 0.5)` which creates a diamond/rhombus pattern that can appear diagonal depending on texcoord orientation.

**Test:** Modify the shader to use `abs(fract(uv.x / spacing.x - 0.5) - 0.5)` and `abs(fract(uv.y / spacing.y - 0.5) - 0.5)` separately to force axis-aligned grid.

**Status:** Not yet tested

### H4: The Coordinate3 positions don't match the texcoords in the way we think
**Evidence:** While correlations are strong, the actual vertex-texcoord pairing might not produce axis-aligned grid lines when rendered.

**Test:** Export a small sample of (position, texcoord) pairs and plot them to visualize the mapping.

**Status:** Not yet tested

### H5: The IndexedFaceSet connectivity is scrambling the grid
**Evidence:** The coordIndex array defines face connectivity, and if vertices are shared between faces with different texcoords, the interpolation could be wrong.

**Test:** Check if any vertex index appears in the coordIndex with different texcoord indices in textureCoordIndex.

**Status:** Verified earlier — textureCoordIndex matches coordIndex 100%, so this is NOT the issue

---

## Test Results Summary

| Test | Result | Notes |
|------|--------|-------|
| Coin3D inside shader group | ✓ PASS | Coordinate3=12907 at group[3][6] |
| textureCoordIndex = coordIndex | ✓ PASS | 100% match |
| U vs Z correlation | ✓ PASS | 0.9998 |
| V vs -Y correlation | ✓ PASS | 0.9969 |
| Mesh topology (U/V edges) | ✓ PASS | 50%/50%/0% split |
| U-edge line monotonicity | ✓ PASS | U varies, V constant |
| V-edge line monotonicity | ✓ PASS | V varies, U constant |
| No orphan Coordinate3 | ✓ PASS | All coords inside shader group |
| Grid lines follow warp/weft | ✗ FAIL | Lines appear diagonal in screenshots |

---

## Files Modified

1. **`src/Mod/Composites/shaders/MeshGridShader.py`**
   - Fixed reorder logic in `attach()` to only restore actually-removed children
   - Scene graph presence check in `load_shader()` to prevent double-attach

2. **`src/Mod/Composites/features/CompositeShell.py`**
   - Removed `delattr(self, "grid_shader")` from `remove_shader()`
   - Added scene graph presence check in `load_shader()`

---

## Next Steps

1. ~~Investigate TextureMatrixTransform~~ — checked, matrix was garbage but resetting to identity didn't fix grid
2. ~~Try simplifying the shader grid pattern~~ — analyzed shader, fract()+min() creates diamond pattern but that's intentional
3. ~~Export sample (position, texcoord) pairs and visualize the mapping~~ — done, mesh topology is correct
4. **Consider using a simpler texture coordinate setup** — exploring old code approach

---

## Critical Discovery: Old vs New Code Architecture

### Old Code (Pre-NextDrape) — Working Version
- Used **support shape's existing triangles** (mesh.Topology[1]) directly
- mesh.Topology[1] contains triangle simplices: lists of 3 vertex indices
- fabric_points indexed by the SAME vertex indices as mesh.Points
- When rendering, each triangle (i,j,k) looks up:
  - 3D positions: mesh.Points[i], mesh.Points[j], mesh.Points[k]
  - Fabric coords: fabric_points[i], fabric_points[j], fabric_points[k]
- **Key insight**: Texture coordinates are tied to the SUPPORT SHAPE'S TRIANGLES, not created from scratch

### New Code (NextDrape) — Broken Version
- Creates **NEW quads** from draper solve result
- Splits each quad into two triangles: (i0,i1,i2) and (i0,i2,i3)
- Creates new Coordinate3 with one point per node
- Associates texture coordinates with each node index
- **Problem**: The new quad-to-triangle split may not match the old triangle structure

### User's Key Observation
> "the fact that the rendered view shows diagonal pattern says something about every second triangle making up the quad doesn't it?"

This suggests that when a quad [i0,i1,i2,i3] is split into:
- T1: (i0, i1, i2)
- T2: (i0, i2, i3)

The second triangle T2 might have its texture coordinates permuted relative to T1, causing alternating diagonal grid lines.

### Analysis Results (Contrary to User's Hypothesis)
- All quads have **UVUV** edge pattern ✓
- All triangles have both U and V edges ✓
- Zero bad triangles in 11,605 quads ✓
- Winding order is consistent (CCW) ✓

**BUT**: The analysis was done on the QUAD data, not the actual TRIANGLE rendering. The issue might be in HOW the triangles are rendered, not in their connectivity.

### Potential Root Cause
The old code's mesh came from `mesh_util.shape2Mesh()` which creates a mesh from the support shape. The triangles in that mesh have a specific topology that matches the fabric layout.

The new code creates quads from the draper solve, which may have a DIFFERENT topology than the original support shape mesh. Even though each quad individually has correct UVUV ordering, the GLOBAL arrangement of quads might cause texture coordinate interpolation issues when rendered.

### Next Investigation Direction
1. Compare the old mesh's triangle structure with the new code's quad split
2. Check if the old mesh used a different triangle split pattern (e.g., i0,i1,i3 and i1,i2,i3 instead of i0,i1,i2 and i0,i2,i3)
3. Consider reconstructing the mesh from the old triangle structure instead of creating new quads

---

## CRITICAL DISCOVERY: Shader Differences (2026-06-30)

### Old Shader vs New Shader Comparison

| Aspect | OLD Shader (Working) | NEW Shader (Broken) |
|--------|---------------------|---------------------|
| **Texture coord type** | `SoTextureCoordinate3()` — 3D (s,t,r) | `SoTextureCoordinate2()` — 2D (s,t) |
| **Tex coord source** | `fabric_points` — 3D Vectors (x,y,z) | `get_tex_coords()` — 2D lists (u,v) |
| **Shader uses** | `.s`, `.t`, **.r** (all 3!) | `.st` only (2D) |
| **Scaling** | Fixed: x=16, y=8, z=2 | Adaptive: `spacing = fwidth(uv) * 20.0` |
| **Pattern** | `mod(param, 1.0)` | `fract(uv/spacing - 0.5)` |
| **Grid** | 3D grid (x,y,z) separate | 2D grid (x,y) combined via `min()` |
| **Base color** | `gl_Color` (vertex colors from strain) | Hardcoded `vec3(0.92, 0.92, 0.92)` |
| **Blending** | `mixcol(gl_Color.r, grid.x)` per channel | `mix(baseColor, lineColor, grid)` |

### Key Finding: Old Shader Used 3D Texture Coordinates
- Old code: `SoTextureCoordinate3()` with (s, t, r) from `fabric_points` (3D Vectors)
- Old shader: `vec3 coord = vec3(x_scale * gl_TexCoord[0].s, y_scale * gl_TexCoord[0].t, z_scale * gl_TexCoord[0].r)`
- Old shader drew THREE SEPARATE 1D grids (one per component) blended with vertex colors

### Key Finding: New Shader Uses 2D Texture Coordinates
- New code: `SoTextureCoordinate2()` with (s, t) from 2D lists
- New shader: `vec2 uv = gl_TexCoord[0].st` (ignores .r)
- New shader draws ONE 2D grid combined via `min(nearest.x, nearest.y)`

### Leading Hypothesis: Adaptive Spacing Causing Diagonal Lines
The new shader uses `spacing = fwidth(uv) * 20.0` where `fwidth(uv)` is the screen-space derivative. If texture coordinates vary differently in x and y directions (U≈Z, V≈-Y), spacing differs, causing diagonal grid lines.

The old shader used FIXED scale factors (16, 8, 2) creating a fixed grid regardless of texture coordinate variation.

### Next Steps
1. Try reverting to old shader pattern: fixed scales + 3D texcoords
2. Or: Replace adaptive spacing with fixed spacing like old code
3. Or: Use `SoTextureCoordinate3()` with 3D texcoords like old code

---

## Debugging Strategy: Binary Search via Component Swap (2026-06-30)

### Principle
The old shader worked. The new one doesn't. The differences are now known (see table above). The strategy is **binary search** — swap components between old and new to isolate which change broke it.

### Test Matrix

| # | Shader Code | Texcoord Type | Texcoord Data | Expected | Purpose |
|---|------------|---------------|---------------|----------|---------|
| 1 | OLD | OLD (3D, `SoTextureCoordinate3`) | OLD (`fabric_points`) | ✓ works | Baseline (known good) |
| 2 | NEW | NEW (2D, `SoTextureCoordinate2`) | NEW (`get_tex_coords`) | ✗ broken | Current state (known bad) |
| 3 | OLD | NEW (2D) | NEW | ? | Isolates: is the shader code the culprit? |
| 4 | NEW | OLD (3D) | OLD | ? | Isolates: is the texcoord data the culprit? |

### Most Direct Test First
Restore the old fragment shader + `SoTextureCoordinate3` + 3D texcoords (test #1). If grid lines become correct → the issue was in the shader rewrite. If still diagonal → the issue is in the mesh/texcoord data from nextdrape.

### Complication: Vertex Colors
The old shader uses `gl_Color` (vertex colors from strain). Two options:
1. Set up vertex colors like the old code did (full restoration), OR
2. Modify the old shader to use hardcoded colors (minimal change to isolate the grid pattern logic)

### Recommended Approach
Start with option 2 — restore the old fragment shader but replace `gl_Color` with a hardcoded color. This isolates the grid pattern logic (fixed scales + `mod()` + 3D texcoords) from the vertex color setup. If the grid lines straighten out, we know the shader rewrite is the culprit and can incrementally port the old logic.

### Specific Changes Needed for Test #1 (Minimal Old Shader Restoration)

1. **`MeshGridShader.py` — `get_texture_coords()`:**
   - Change `SoTextureCoordinate2()` → `SoTextureCoordinate3()`
   - Change `set1Value(idx, pt[0], pt[1])` → `set1Value(idx, pt[0], pt[1], 0.0)` (add third component)

2. **`Grid_fragment_shader.glsl`:**
   - Restore old shader body but replace `gl_Color` with hardcoded color:
     ```glsl
     vec4 baseColor = vec4(0.5, 0.5, 0.5, 1.0);
     // ... old gridFactor logic ...
     gl_FragColor = vec4(mixcol(baseColor.r, grid.x),
                         mixcol(baseColor.g, grid.y),
                         mixcol(baseColor.b, grid.z),
                         baseColor.a);
     ```

3. **Shader uniforms:**
   - Restore old default values: x_scale=16, y_scale=8, z_scale=2

### Success Criteria
- Grid lines appear vertical/horizontal (following warp/weft) in Front view
- Grid lines appear as concentric/radial in Top view
- No diagonal pattern across the conical surface

### If Test #1 Fails (Still Diagonal)
The issue is NOT in the shader — it's in the mesh/texcoord data from nextdrape. Next step: compare nextdrape's texcoords with the old draper's `fabric_points` to see if they're fundamentally different.

### New Finding from User Screenshots (Chevron Pattern)
The provided close-up screenshots show a **triangle-local zig-zag/chevron** pattern, not just global diagonal drift. This is a strong indicator of a **texcoord binding/indexing issue** at triangle level.

Hypothesis: `SoTextureCoordinateBinding` mode is wrong for `SoIndexedFaceSet` with `textureCoordIndex`.

- Current code had: `PER_VERTEX`
- For indexed faces with explicit `textureCoordIndex`, correct mode should be: `PER_VERTEX_INDEXED`
- Old code did not force binding explicitly, likely using correct default indexed behavior.

Applied fix:
- In `MeshGridShader.py`, changed:
  - `SoTextureCoordinateBinding.PER_VERTEX`
  - → `SoTextureCoordinateBinding.PER_VERTEX_INDEXED`

Status:
- Code patched and synced to build copy.
- Needs clean reattach/reload pass in live document to validate visual impact.

### Validation after PER_VERTEX_INDEXED fix + old-shader test
- Loaded `build/pixi-debug/Composites_Conical_Panel.FCStd`
- Reattached shader with:
  - `SoTextureCoordinate3`
  - old fragment shader logic (`mod()` gridFactor)
  - old spacing defaults (`Spacing=[20,2,10]` => x=0.05, y=0.5, z=0.1)
  - binding fix: `SoTextureCoordinateBinding.PER_VERTEX_INDEXED`

Observed result:
- Chevron/per-triangle reset artifact from close-up screenshots appears resolved.
- Remaining pattern is now coherent but still diagonal in front view (continuous diagonal stripes, no per-triangle zig-zag resets).

Interpretation:
- The user's triangle-level suspicion was valid for one layer of the bug (binding/indexing mode).
- After fixing binding, remaining issue likely in shader pattern/orientation/scaling (not raw topology/index mismatch).

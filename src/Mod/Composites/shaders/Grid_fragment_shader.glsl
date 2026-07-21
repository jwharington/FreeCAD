#version 130

uniform float darken = 0.5;
uniform float screen_space = 1.0;
uniform float grid_spacing_mm = 10.0;

// Selection-highlight tint, driven from the ViewProvider's
// SelectionObserver callbacks via SoShaderParameter (vec3 + 1f). sel_state
// = 0 => neutral grey grid; = 1 => fully sel_color (green on select,
// blue on hover). Declared AND used so the GLSL linker keeps them in the
// program (an unused/default-only uniform is eliminated and never
// reaches the GPU — that was the earlier "dead uniform" pitfall).
uniform vec3 sel_color;
uniform float sel_state;

// Grid rotation angle (radians) for the selected layer's fibre
// orientation. Driven by SoShaderParameter from the VP
// (get_offset_angle -> set_offset_angle). Declared AND used so the
// linker keeps it in the program.
uniform float offset_angle;


// https://github.com/rreusser/glsl-solid-wireframe?tab=readme-ov-file

float gridFactor (float parameter, float width, float feather) {
  float w1 = width - feather * 0.5;
  float d = fwidth(parameter);
  float looped = 0.5 - abs(mod(parameter, 1.0) - 0.5);
  return smoothstep(d * w1, d * (w1 + feather), looped);
}

float gridFactor (float parameter, float width) {
  float d = fwidth(parameter);
  float looped = 0.5 - abs(mod(parameter, 1.0) - 0.5);
  return smoothstep(d * (width - 0.5), d * (width + 0.5), looped);
}


float gridFactor (vec2 parameter, float width, float feather) {
  float w1 = width - feather * 0.5;
  vec2 d = fwidth(parameter);
  vec2 looped = 0.5 - abs(mod(parameter, 1.0) - 0.5);
  vec2 a2 = smoothstep(d * w1, d * (w1 + feather), looped);
  return min(a2.x, a2.y);
}


float gridFactor (vec2 parameter, float width) {
  vec2 d = fwidth(parameter);
  vec2 looped = 0.5 - abs(mod(parameter, 1.0) - 0.5);
  vec2 a2 = smoothstep(d * (width - 0.5), d * (width + 0.5), looped);
  return min(a2.x, a2.y);
}


float gridFactor (vec3 parameter, float width, float feather) {
  float w1 = width - feather * 0.5;
  vec3 d = fwidth(parameter);
  vec3 looped = 0.5 - abs(mod(parameter, 1.0) - 0.5);
  vec3 a2 = smoothstep(d * w1, d * (w1 + feather), looped);
  return min(a2.x, a2.y);
}


float gridFactor (vec3 parameter, float width) {
  vec3 d = fwidth(parameter);
  vec3 looped = 0.5 - abs(mod(parameter, 1.0) - 0.5);
  vec3 a2 = smoothstep(d * (width - 0.5), d * (width + 0.5), looped);
  return min(a2.x, a2.y);
}


void main() {
  // Neutral grid base color. Selection tint mixes toward sel_color
  // when sel_state > 0 (driven by SoShaderParameter from the VP's
  // SelectionObserver callbacks).
  vec3 baseColor = vec3(0.5);
  vec3 lineColor = mix(baseColor, sel_color, clamp(sel_state, 0.0, 1.0));

  float spacing = max(grid_spacing_mm, 1e-6);
  vec3 coord = gl_TexCoord[0].xyz / spacing;

  // Rotate the grid UV by offset_angle so the grid aligns with the
  // selected layer's fibre orientation.
  float ca = cos(offset_angle);
  float sa = sin(offset_angle);
  vec2 rcoord = vec2(ca * coord.x - sa * coord.y,
                     sa * coord.x + ca * coord.y);

  // screen_space: 1.0 = zoom-stable ~1px lines via fwidth (default),
  // 0.0 = wider fixed screen-space width. Blend the line width so the
  // toggle actually does something (it was previously declared but
  // never referenced in main()).
  float sw = clamp(screen_space, 0.0, 1.0);
  float pixel_width = mix(2.5, 1.0, sw);
  // Non-zero feather gives smoothstep a real transition band (was 0.0,
  // which degenerated into a hard step at the Nyquist limit → moiré).
  float feather = 1.0;

  float gridX = gridFactor(rcoord.x, pixel_width, feather);
  float gridY = gridFactor(rcoord.y, pixel_width, feather);
  // gridFactor: 0 at a grid line, 1 between lines. A fragment is on a
  // line if EITHER axis is on a line, so combine with min (not max —
  // max only hits zero at X∩Y intersections, which is why only dots
  // rendered before).
  float between = min(gridX, gridY);   // 0 on any line, 1 between
  float line = 1.0 - between;          // 1 at lines, 0 between

  // Anti-moiré: when the grid is denser than the screen can resolve
  // (>~1–2 lines per pixel), fade the lines out instead of aliasing.
  // This is the standard fix for dense-grid moiré at low zoom.
  float density = max(fwidth(rcoord.x), fwidth(rcoord.y));
  float fade = 1.0 - smoothstep(1.0, 2.0, density);
  line *= fade;

  // Uniform line color (darken scales line darkness); alpha follows
  // line intensity so background stays transparent.
  vec3 col = lineColor * (1.0 - darken * line);
  gl_FragColor = vec4(col, line);
}

#version 130

uniform float darken = 0.5;
uniform float screen_space = 1.0;
uniform float grid_spacing_mm = 10.0;


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


float mixcol(float col, float amount) {
  return col*(1.0-darken*amount);
}

void main() {
  // Hardcoded color (replaces old gl_Color from per-vertex strain coloring)
  vec4 baseColor = vec4(0.5, 0.5, 0.5, 0.0);
  float pixel_width = 1.0;
  float feather = 0.0;

  // Texture coordinates are already in physical units (mm).
  // Divide by the requested physical spacing so the shader draws
  // one repeat every grid_spacing_mm in world space.
  float spacing = max(grid_spacing_mm, 1e-6);
  vec3 coord = gl_TexCoord[0].xyz / spacing;
  float gridX = gridFactor(coord.x, pixel_width, feather);
  float gridY = gridFactor(coord.y, pixel_width, feather);
  float gridMax = max(gridX, gridY);
  // gridFactor returns 0 at grid lines, 1 between them.
  // We want lines opaque (a=1) and background transparent (a=0),
  // so invert: alpha is high where gridMax is low.
  float a = mix(1.0, baseColor.a, gridMax);
  gl_FragColor = vec4(mixcol(baseColor.r, gridX),
                      mixcol(baseColor.g, gridY),
                      baseColor.b,
                      a);
}

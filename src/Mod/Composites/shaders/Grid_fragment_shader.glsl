#version 130
precision mediump float;

uniform float darken = 0.5;
uniform float x_scale = 16.0;
uniform float y_scale = 8.0;
uniform float z_scale = 2.0;
uniform float offset_angle = 0.0;  // rosette rotation, radians


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
  vec4 baseColor = vec4(0.5, 0.5, 0.5, 0.2);
  float pixel_width = 1.0;
  float feather = 0.0;

  // Rotate warp/weft grid by the rosette offset angle in the UV plane.
  // The third component (r) is left unrotated — it tracks thickness drift.
  float c = cos(offset_angle);
  float s = sin(offset_angle);
  vec2 uv = vec2(c * gl_TexCoord[0].s - s * gl_TexCoord[0].t,
                s * gl_TexCoord[0].s + c * gl_TexCoord[0].t);

  vec3 coord = vec3(x_scale * uv.x,
                    y_scale * uv.y,
                    z_scale * gl_TexCoord[0].r);
  vec3 grid = vec3(gridFactor(coord.x, pixel_width, feather),
                   gridFactor(coord.y, pixel_width, feather),
                   gridFactor(coord.z, pixel_width, feather));
  float gridMax = max(grid.x, max(grid.y, grid.z));
  // gridFactor returns 0 at grid lines, 1 between them.
  // We want lines opaque (a=1) and background transparent (a=0),
  // so invert: alpha is high where gridMax is low.
  float a = mix(1.0, baseColor.a, gridMax);
  gl_FragColor = vec4(mixcol(baseColor.r, grid.x),
                      mixcol(baseColor.g, grid.y),
                      mixcol(baseColor.b, grid.z),
                      a);
}

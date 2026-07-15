#version 130
precision mediump float;

uniform float darken = 0.5;
uniform float screen_space = 1.0;


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

  // Compute screen-space scale from dFdx/dFdy of texture coordinates.
  // dFdx/dFdy give the rate of change of texcoords per screen pixel.
  // Inverse gives texcoords per screen pixel → multiply by target_cycles
  // to get the scale that produces ~20px grid spacing.
  vec2 ds_dt = vec2(dFdx(gl_TexCoord[0].s), dFdy(gl_TexCoord[0].s));
  vec2 dt_dt = vec2(dFdx(gl_TexCoord[0].t), dFdy(gl_TexCoord[0].t));
  vec2 dr_dr = vec2(dFdx(gl_TexCoord[0].r), dFdy(gl_TexCoord[0].r));

  // Magnitude of texcoord change per screen pixel.
  float ds_per_px = length(ds_dt);
  float dt_per_px = length(dt_dt);
  float dr_per_px = length(dr_dr);

  // Avoid division by zero.
  ds_per_px = max(ds_per_px, 1e-6);
  dt_per_px = max(dt_per_px, 1e-6);
  dr_per_px = max(dr_per_px, 1e-6);

  // Target: ~25 grid cycles across the texcoord range → ~20px spacing.
  // scale = 1 / (texcoords_per_pixel * target_cycles)
  // = (pixels_per_texcoord_unit) / target_cycles
  float target_cycles = 25.0;
  float px_per_unit_x = 1.0 / (ds_per_px * target_cycles);
  float px_per_unit_y = 1.0 / (dt_per_px * target_cycles);
  float px_per_unit_z = 1.0 / (dr_per_px * target_cycles);

  vec3 coord = vec3(px_per_unit_x * gl_TexCoord[0].s,
                    px_per_unit_y * gl_TexCoord[0].t,
                    px_per_unit_z * gl_TexCoord[0].r);
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

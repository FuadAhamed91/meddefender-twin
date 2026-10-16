import { Color, DoubleSide, type Material, MeshStandardMaterial, ShaderMaterial, UniformsLib, UniformsUtils } from "three";

// Shared vertex stage: world-space position and normal for view-dependent effects, plus fog.
const WORLD_VERT = /* glsl */ `
  #include <fog_pars_vertex>
  varying vec3 vNormalW;
  varying vec3 vPosW;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vPosW = world.xyz;
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vec4 mvPosition = viewMatrix * world;
    gl_Position = projectionMatrix * mvPosition;
    #include <fog_vertex>
  }`;

// Hologram surface: faint where it faces the viewer, brighter at grazing angles (fresnel rim)
// and toward the top edge, so walls read as glowing outlines rather than solid slabs.
const HOLOGRAM_FRAG = /* glsl */ `
  #include <fog_pars_fragment>
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uRim;
  uniform float uTop;
  uniform float uHeight;
  varying vec3 vNormalW;
  varying vec3 vPosW;
  void main() {
    vec3 viewDir = normalize(cameraPosition - vPosW);
    // Clamped: pow() of a tiny negative base is NaN on D3D/ANGLE, and bloom would smear it.
    float facing = clamp(abs(dot(normalize(vNormalW), viewDir)), 0.0, 1.0);
    float rim = pow(1.0 - facing, 2.0);
    float topBand = pow(clamp(vPosW.y / uHeight, 0.0, 1.0), 4.0);
    vec3 color = uColor * (0.35 + uRim * rim + uTop * topBand);
    float alpha = clamp(uOpacity * (0.55 + 0.9 * rim + 0.7 * topBand), 0.0, 1.0);
    gl_FragColor = vec4(color, alpha);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    #include <fog_fragment>
  }`;

// Floor plate: dark base with an anti-aliased metric grid (1 m minor, 4 m major lines).
const FLOOR_FRAG = /* glsl */ `
  #include <fog_pars_fragment>
  uniform vec3 uBase;
  uniform vec3 uLine;
  varying vec3 vNormalW;
  varying vec3 vPosW;
  float gridLine(vec2 p, float scale, float width) {
    vec2 coord = p / scale;
    vec2 g = abs(fract(coord - 0.5) - 0.5) / max(fwidth(coord), vec2(1e-4));
    return 1.0 - min(min(g.x, g.y) / width, 1.0);
  }
  void main() {
    float minor = gridLine(vPosW.xz, 1.0, 1.0);
    float major = gridLine(vPosW.xz, 4.0, 1.3);
    vec3 color = uBase + uLine * max(minor * 0.16, major * 0.34);
    gl_FragColor = vec4(color, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    #include <fog_fragment>
  }`;

export interface HologramOptions {
  opacity: number;
  /** Brightness added at grazing angles. */
  rim: number;
  /** Brightness added toward the top edge. */
  top: number;
  /** Height (m) at which the top band peaks. */
  height: number;
}

export function hologramMaterial(color: string, options: HologramOptions): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: UniformsUtils.merge([
      UniformsLib.fog,
      {
        uColor: { value: new Color(color) },
        uOpacity: { value: options.opacity },
        uRim: { value: options.rim },
        uTop: { value: options.top },
        uHeight: { value: options.height },
      },
    ]),
    vertexShader: WORLD_VERT,
    fragmentShader: HOLOGRAM_FRAG,
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
    fog: true,
  });
}

/**
 * Realistic view: give the exported floor materials 600 mm tiles (grout lines plus a slight
 * per-tile tone variation) for a sense of scale. Patched in place, once; lines fade out where
 * tiles become too small on screen to avoid moire.
 */
export function addFloorTiles(material: Material, tileSize = 0.6): void {
  if (!(material instanceof MeshStandardMaterial) || material.userData.tiled) return;
  material.userData.tiled = true;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uTileSize = { value: tileSize };
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vTileWorld;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvTileWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vTileWorld;\nuniform float uTileSize;")
      .replace(
        "#include <color_fragment>",
        /* glsl */ `#include <color_fragment>
        {
          vec2 p = vTileWorld.xz / uTileSize;
          vec2 edge = min(fract(p), 1.0 - fract(p));
          vec2 w = max(fwidth(p), vec2(1e-4));
          float gw = 0.012 / uTileSize;
          vec2 l = 1.0 - smoothstep(vec2(gw) - w, vec2(gw) + w, edge);
          float fade = 1.0 - smoothstep(0.08, 0.2, max(w.x, w.y));
          float grout = max(l.x, l.y) * fade;
          float n = fract(sin(dot(floor(p), vec2(12.9898, 78.233))) * 43758.5453);
          diffuseColor.rgb *= (1.0 - 0.16 * grout) * (0.97 + 0.05 * n * fade);
        }`,
      );
  };
  material.customProgramCacheKey = () => "meddefender-floor-tiles";
  material.needsUpdate = true;
}

export function floorGridMaterial(base: string, line: string): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: UniformsUtils.merge([UniformsLib.fog, { uBase: { value: new Color(base) }, uLine: { value: new Color(line) } }]),
    vertexShader: WORLD_VERT,
    fragmentShader: FLOOR_FRAG,
    fog: true,
  });
}

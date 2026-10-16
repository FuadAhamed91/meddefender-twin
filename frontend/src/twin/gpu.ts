// Renderers without GPU acceleration (headless browsers, virtual machines, remote desktops).
const SOFTWARE_RENDERER = /swiftshader|llvmpipe|softpipe|software|basic render/i;

/**
 * Whether WebGL would run on a CPU rasteriser. Probed once with a throwaway context, before
 * the 3D view exists, so the twin can start in reduced quality instead of compiling the full
 * post-processing pipeline and then switching (which would compile everything twice).
 */
export function isSoftwareRenderer(): boolean {
  // Not a browser with WebGL 2 (for example the jsdom test environment): nothing to detect.
  if (typeof window === "undefined" || !("WebGL2RenderingContext" in window)) return false;
  try {
    const context = document.createElement("canvas").getContext("webgl2");
    if (!context) return false;
    const info = context.getExtension("WEBGL_debug_renderer_info");
    const name = String(context.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : context.RENDERER));
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return SOFTWARE_RENDERER.test(name);
  } catch {
    return false;
  }
}

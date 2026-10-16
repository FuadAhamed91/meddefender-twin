import { type RootState, useThree } from "@react-three/fiber";
import { useEffect } from "react";

declare global {
  interface Window {
    /** Dev builds only: render `frames` frames synchronously and return the last one as a PNG data URL. */
    __twinCapture?: (frames?: number) => string;
    /** Dev builds only: the live react-three-fiber state, for inspection from the console. */
    __twinState?: () => RootState;
  }
}

/**
 * Development aid for visual checks (and future screenshot tests): renders frames on demand,
 * which also works while the tab is in the background and requestAnimationFrame is paused.
 */
export function DevCapture() {
  const advance = useThree((s) => s.advance);
  const gl = useThree((s) => s.gl);
  const get = useThree((s) => s.get);
  useEffect(() => {
    window.__twinCapture = (frames = 1) => {
      for (let i = 0; i < frames; i++) advance(performance.now());
      // Read back in the same task as the render, before the drawing buffer is presented.
      return gl.domElement.toDataURL("image/png");
    };
    window.__twinState = get;
    return () => {
      delete window.__twinCapture;
      delete window.__twinState;
    };
  }, [advance, gl, get]);
  return null;
}

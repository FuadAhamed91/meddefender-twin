import type { Object3D } from "three";

/** Asset id -> scene node of the loaded hospital model (filled by HospitalModel). Used by
 *  effects that need real scene objects (selection outline). Never a source of state. */
export const assetNodeRegistry = new Map<string, Object3D>();

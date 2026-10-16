import { CameraControls, Environment as EnvironmentMap, Grid, Html, Lightformer, useProgress } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Component, type ReactNode, Suspense, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { BackSide, Box3, Color, type DirectionalLight, type Mesh, type PerspectiveCamera, ShaderMaterial, Sphere, Vector3 } from "three";
import { useZones } from "../api/queries";
import { FLOOR_BOUNDS, planToWorld } from "../lib/coords";
import { useTwinStore } from "../state/twin";
import { AssetMarkers } from "./AssetMarkers";
import { DevCapture } from "./DevCapture";
import { Effects } from "./Effects";
import { HospitalModel } from "./HospitalModel";
import { AttackPathOverlay, NetworkOverlay, StatusBeams, TransientFlows, ZoneOverlay } from "./Overlays";
import { ProceduralHospital } from "./ProceduralHospital";
import { RoomLabels } from "./RoomLabels";

// Three-quarter view from the south-west, like an architectural cutaway.
const OVERVIEW = { position: new Vector3(4, 30, 22), target: new Vector3(28, 0, -17) };
// Establishing shot for the one-time intro: high above the site, looking north.
const INTRO = { position: new Vector3(18, 80, 77), target: new Vector3(28, 0, -18) };
const SITE_CENTER = new Vector3((FLOOR_BOUNDS.min[0] + FLOOR_BOUNDS.max[0]) / 2, 0, -(FLOOR_BOUNDS.min[1] + FLOOR_BOUNDS.max[1]) / 2);

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// The establishing shot plays once per page load, after the model has loaded.
let introPending = true;

function overviewSphere(aspect: number): Sphere {
  // fitToBox snaps angles to 90-degree steps, so fit a bounding sphere instead to keep the
  // three-quarter view.
  const floor = new Box3(planToWorld(FLOOR_BOUNDS.min[0], FLOOR_BOUNDS.max[1], 0), planToWorld(FLOOR_BOUNDS.max[0], FLOOR_BOUNDS.min[1], 3));
  const sphere = floor.getBoundingSphere(new Sphere());
  // The floor is much wider than it is deep. On wide canvases the height limits the fit and a
  // smaller sphere fills the view; on squarer canvases the width limits it, so fit the full
  // floor instead of cropping its sides.
  const t = Math.min(1, Math.max(0, (aspect - 1) / 0.6));
  sphere.radius *= 0.95 - 0.19 * t;
  // Aim slightly south of the floor's centre: from the south-west viewpoint the near half of
  // the building looks larger, so this centres it visually instead of leaving empty sky above.
  sphere.center.z += 2.5;
  return sphere;
}

function aspectOf(controls: CameraControls): number {
  return (controls.camera as PerspectiveCamera).aspect || 1.6;
}

function CameraRig() {
  const ref = useRef<CameraControls>(null);
  const focus = useTwinStore((s) => s.focus);
  const { data: zones = [] } = useZones();
  const invalidate = useThree((s) => s.invalidate);

  useEffect(() => {
    const controls = ref.current;
    if (!controls) return;
    const assets = useTwinStore.getState().assets;
    if (focus.kind === "overview") {
      if (focus.nonce === 0 && introPending && !reducedMotion()) {
        // Park the camera at the establishing shot; IntroFlight glides in once the model loads.
        void controls.setLookAt(...INTRO.position.toArray(), ...INTRO.target.toArray(), false);
        invalidate();
        return;
      }
      const animate = focus.nonce > 0;
      void controls.setLookAt(...OVERVIEW.position.toArray(), ...OVERVIEW.target.toArray(), animate);
      void controls.fitToSphere(overviewSphere(aspectOf(controls)), animate);
      invalidate();
      return;
    }
    if (focus.kind === "asset") {
      const asset = assets[focus.ids[0]];
      if (!asset?.position) return;
      const target = planToWorld(asset.position.x, asset.position.y, 1);
      void controls.setLookAt(target.x + 5, 8.5, target.z + 9, target.x, target.y, target.z, true);
      return;
    }
    const box = new Box3();
    if (focus.kind === "zone") {
      const zone = zones.find((z) => z.id === focus.ids[0]);
      if (!zone) return;
      box.expandByPoint(planToWorld(zone.bounds.min[0], zone.bounds.min[1], 0));
      box.expandByPoint(planToWorld(zone.bounds.max[0], zone.bounds.max[1], 2.5));
    } else {
      for (const id of focus.ids) {
        const a = assets[id];
        if (a?.position) {
          box.expandByPoint(planToWorld(a.position.x - 2, a.position.y - 2, 0));
          box.expandByPoint(planToWorld(a.position.x + 2, a.position.y + 2, 2.5));
        }
      }
      if (box.isEmpty()) return;
    }
    const center = box.getCenter(new Vector3());
    const size = box.getSize(new Vector3());
    const distance = Math.max(size.x, size.z) * 1.05 + 8;
    void controls.setLookAt(center.x, distance * 0.95, center.z + distance * 0.62, center.x, 0, center.z, true);
  }, [focus, zones, invalidate]);

  return (
    <CameraControls
      ref={ref}
      makeDefault
      minDistance={3}
      maxDistance={140}
      maxPolarAngle={Math.PI * 0.46}
      dollySpeed={0.6}
      smoothTime={0.35}
    />
  );
}

/** Mounted once the model (or its fallback) is ready: a slow glide from the establishing shot. */
function IntroFlight() {
  const controls = useThree((s) => s.controls) as unknown as CameraControls | null;
  useEffect(() => {
    if (!controls || !introPending) return;
    introPending = false;
    const focus = useTwinStore.getState().focus;
    if (focus.kind !== "overview" || focus.nonce !== 0 || reducedMotion()) return;
    controls.smoothTime = 1.1;
    void controls.setLookAt(...OVERVIEW.position.toArray(), ...OVERVIEW.target.toArray(), true);
    void controls.fitToSphere(overviewSphere(aspectOf(controls)), true);
    // Restore normal responsiveness after the glide (not tied to unmount: StrictMode re-runs effects).
    window.setTimeout(() => {
      controls.smoothTime = 0.35;
    }, 2600);
  }, [controls]);
  return null;
}

function Loader() {
  const { progress } = useProgress();
  return (
    <Html center>
      <div role="status" className="rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink-muted">
        Loading hospital model… {progress.toFixed(0)}%
      </div>
    </Html>
  );
}

class ModelBoundary extends Component<{ children: ReactNode; fallback: ReactNode; onError: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

// ---- atmosphere ------------------------------------------------------------------------------

const SKY = {
  holographic: { top: "#010309", horizon: "#0a2140", bottom: "#02050d", fog: "#061428" },
  realistic: { top: "#060b15", horizon: "#1b2b45", bottom: "#0a101b", fog: "#121e33" },
} as const;

/** Gradient sky dome that follows the camera: a horizon glow gives the scene depth. */
function Backdrop({ holo }: { holo: boolean }) {
  const ref = useRef<Mesh>(null);
  const invalidate = useThree((s) => s.invalidate);
  const material = useMemo(
    () =>
      new ShaderMaterial({
        uniforms: { uTop: { value: new Color() }, uHorizon: { value: new Color() }, uBottom: { value: new Color() } },
        vertexShader: /* glsl */ `
          varying vec3 vDir;
          void main() {
            vDir = position;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: /* glsl */ `
          uniform vec3 uTop;
          uniform vec3 uHorizon;
          uniform vec3 uBottom;
          varying vec3 vDir;
          void main() {
            float h = normalize(vDir).y;
            vec3 color = h >= 0.0
              ? mix(uHorizon, uTop, pow(clamp(h / 0.6, 0.0, 1.0), 0.6))
              : mix(uHorizon, uBottom, clamp(-h / 0.15, 0.0, 1.0));
            gl_FragColor = vec4(color, 1.0);
            #include <colorspace_fragment>
          }`,
        side: BackSide,
        depthWrite: false,
        depthTest: false,
        fog: false,
      }),
    [],
  );
  useEffect(() => {
    const sky = holo ? SKY.holographic : SKY.realistic;
    material.uniforms.uTop.value.set(sky.top);
    material.uniforms.uHorizon.value.set(sky.horizon);
    material.uniforms.uBottom.value.set(sky.bottom);
    invalidate();
  }, [holo, material, invalidate]);
  useEffect(() => () => material.dispose(), [material]);
  useFrame(({ camera }) => ref.current?.position.copy(camera.position));
  return (
    <mesh ref={ref} material={material} renderOrder={-1000} frustumCulled={false} raycast={() => undefined}>
      <sphereGeometry args={[350, 48, 24]} />
    </mesh>
  );
}

/** Key light for the realistic view; casts soft shadows from walls and equipment. */
function SunLight({ shadows }: { shadows: boolean }) {
  const ref = useRef<DirectionalLight>(null);
  const gl = useThree((s) => s.gl);
  // Nothing that casts a shadow ever moves, so render the 4096² shadow map on demand (when the
  // model or view changes; HospitalModel requests it) instead of on every frame.
  useLayoutEffect(() => {
    gl.shadowMap.autoUpdate = false;
    gl.shadowMap.needsUpdate = true;
    return () => {
      gl.shadowMap.autoUpdate = true;
    };
  }, [gl, shadows]);
  useLayoutEffect(() => {
    const light = ref.current;
    if (!light) return;
    // The target is not part of the scene graph, so place it and update its matrix by hand.
    light.target.position.copy(SITE_CENTER);
    light.target.updateMatrixWorld();
  }, []);
  return (
    <directionalLight
      ref={ref}
      castShadow={shadows}
      position={[SITE_CENTER.x + 32, 34, SITE_CENTER.z + 30]}
      intensity={1.35}
      color="#fff1dc"
      shadow-mapSize={[4096, 4096]}
      shadow-camera-left={-46}
      shadow-camera-right={46}
      shadow-camera-top={42}
      shadow-camera-bottom={-42}
      shadow-camera-near={10}
      shadow-camera-far={150}
      shadow-bias={-0.0004}
      shadow-normalBias={0.035}
      shadow-radius={2.5}
    />
  );
}

/** Lights, sky and ground. `full` adds shadow maps and image-based lighting (both costly on a CPU renderer). */
function Atmosphere({ full }: { full: boolean }) {
  const mode = useTwinStore((s) => s.viewMode);
  const holo = mode === "holographic";
  const sky = holo ? SKY.holographic : SKY.realistic;
  const ground = new Vector3(SITE_CENTER.x, -0.32, SITE_CENTER.z);
  const gl = useThree((s) => s.gl);
  // Read by the tone-mapping pass: the light interior needs a little less exposure on a dark UI.
  const invalidate = useThree((s) => s.invalidate);
  useLayoutEffect(() => {
    gl.toneMappingExposure = holo ? 1 : 0.82;
    invalidate();
  }, [gl, holo, invalidate]);
  return (
    <>
      <color attach="background" args={[sky.top]} />
      <fog attach="fog" args={[sky.fog, 95, 210]} />
      <Backdrop holo={holo} />
      {/* Image-based lighting from procedural light panels: soft reflections, no HDR download. */}
      {full ? (
        <EnvironmentMap key={mode} resolution={256} frames={1} environmentIntensity={holo ? 0.45 : 0.25}>
          {holo ? (
            <>
              <Lightformer form="rect" intensity={2.2} color="#3b82f6" position={[0, 12, 0]} rotation-x={Math.PI / 2} scale={[40, 40, 1]} />
              <Lightformer form="ring" intensity={3} color="#22d3ee" position={[30, 8, 30]} scale={12} />
              <Lightformer form="rect" intensity={1.2} color="#6366f1" position={[-30, 6, -10]} rotation-y={Math.PI / 2} scale={[30, 8, 1]} />
            </>
          ) : (
            <>
              <Lightformer form="rect" intensity={3.2} color="#ffffff" position={[0, 14, 0]} rotation-x={Math.PI / 2} scale={[60, 40, 1]} />
              <Lightformer form="rect" intensity={1.4} color="#dbeafe" position={[-35, 8, 0]} rotation-y={Math.PI / 2} scale={[40, 10, 1]} />
              <Lightformer form="rect" intensity={1.0} color="#fff7ed" position={[35, 8, 10]} rotation-y={-Math.PI / 2} scale={[40, 10, 1]} />
            </>
          )}
        </EnvironmentMap>
      ) : null}
      {holo ? (
        <>
          <hemisphereLight args={["#9cc9ff", "#020617", 0.65]} />
          <directionalLight position={[20, 60, 30]} intensity={0.8} color="#cfe3ff" />
          <Grid
            position={ground}
            args={[240, 240]}
            cellSize={1}
            cellThickness={0.55}
            cellColor="#0c3654"
            sectionSize={8}
            sectionThickness={1.1}
            sectionColor="#1d74b8"
            fadeDistance={170}
            fadeStrength={1.6}
            infiniteGrid
          />
        </>
      ) : (
        <>
          {/* Cool sky fill against a warm sun: shadows read slightly blue, lit areas warm. */}
          <hemisphereLight args={["#b3c8f0", "#1c2430", 0.6]} />
          <SunLight shadows={full} />
          <directionalLight position={[-30, 30, -40]} intensity={0.25} color="#b8d4ff" />
          {/* Unlit dark ground: a calm backdrop that never competes with the building. */}
          <mesh position={ground} rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[210, 64]} />
            <meshBasicMaterial color="#0a111d" />
          </mesh>
        </>
      )}
    </>
  );
}

/**
 * The canvas renders on demand: frames are drawn when something changes (camera movement,
 * state updates), and never while the scene is idle. Ambient animation (live-flow comets,
 * alert pulses) exists only for a few seconds after live events; while it does, this keeps
 * requesting frames at a modest rate. On a CPU rasteriser the rate is lower still.
 */
function AnimationDriver({ intervalMs }: { intervalMs: number }) {
  const invalidate = useThree((s) => s.invalidate);
  const animating = useTwinStore((s) => s.transientEdges.length > 0 || Object.keys(s.flashes).length > 0);
  useEffect(() => {
    if (!animating) return;
    const timer = window.setInterval(() => invalidate(), intervalMs);
    return () => window.clearInterval(timer);
  }, [animating, intervalMs, invalidate]);
  return null;
}

export function TwinCanvas({ onModelFallback }: { onModelFallback: () => void }) {
  const select = useTwinStore((s) => s.select);
  const full = useTwinStore((s) => s.renderQuality === "full");
  const cpu = useTwinStore((s) => s.cpuRenderer);
  return (
    <Canvas
      camera={{ position: INTRO.position.toArray(), fov: 42, near: 0.3, far: 400 }}
      // Render only when something changes (see AnimationDriver). Fewer pixels on a CPU renderer.
      frameloop="demand"
      dpr={cpu ? 0.6 : full ? Math.min(1.5, window.devicePixelRatio || 1) : 1}
      shadows="percentage"
      // Full quality anti-aliases in the effect composer (MSAA); context options are fixed at
      // creation, so native anti-aliasing applies when the session starts in reduced mode.
      gl={{ antialias: !full, powerPreference: "high-performance", stencil: false }}
      onPointerMissed={() => select(null)}
      // Clip rather than hide overflow: a hidden-overflow box still scrolls to reveal a focused
      // element, so clicking or tabbing to an off-screen device chip slid the canvas out of view.
      style={{ overflow: "clip" }}
      aria-label="3D digital twin of the simulated hospital"
      role="img"
    >
      <AnimationDriver intervalMs={cpu ? 100 : 33} />
      <Atmosphere full={full} />
      <Suspense fallback={<Loader />}>
        <ModelBoundary
          fallback={
            <>
              <ProceduralHospital />
              <IntroFlight />
            </>
          }
          onError={onModelFallback}
        >
          <HospitalModel />
          <IntroFlight />
        </ModelBoundary>
      </Suspense>
      <ZoneOverlay />
      <RoomLabels />
      <StatusBeams />
      <NetworkOverlay />
      <AttackPathOverlay />
      <TransientFlows />
      <AssetMarkers />
      <CameraRig />
      {full ? <Effects /> : null}
      {import.meta.env.DEV ? <DevCapture /> : null}
    </Canvas>
  );
}

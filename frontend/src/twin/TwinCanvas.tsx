import { CameraControls, Html, useProgress } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Component, type ReactNode, Suspense, useEffect, useRef } from "react";
import { Box3, Vector3 } from "three";
import { useZones } from "../api/queries";
import { FLOOR_BOUNDS, planToWorld } from "../lib/coords";
import { useTwinStore } from "../state/twin";
import { AssetMarkers } from "./AssetMarkers";
import { HospitalModel } from "./HospitalModel";
import { AttackPathOverlay, DependencyOverlay, NetworkOverlay, TransientFlows, ZoneOverlay } from "./Overlays";
import { ProceduralHospital } from "./ProceduralHospital";

const OVERVIEW = { position: new Vector3(28, 46, 24), target: new Vector3(28, 0, -17) };

function CameraRig() {
  const ref = useRef<CameraControls>(null);
  const focus = useTwinStore((s) => s.focus);
  const { data: zones = [] } = useZones();

  useEffect(() => {
    const controls = ref.current;
    if (!controls) return;
    const assets = useTwinStore.getState().assets;
    if (focus.kind === "overview") {
      // Fit the whole floor plate, then tilt for a readable three-quarter view.
      const floor = new Box3(planToWorld(FLOOR_BOUNDS.min[0], FLOOR_BOUNDS.max[1], 0), planToWorld(FLOOR_BOUNDS.max[0], FLOOR_BOUNDS.min[1], 3));
      void controls.setLookAt(...OVERVIEW.position.toArray(), ...OVERVIEW.target.toArray(), false);
      void controls.fitToBox(floor, focus.nonce > 0, { paddingLeft: 1, paddingRight: 1, paddingTop: 2, paddingBottom: 2 });
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
  }, [focus, zones]);

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

export function TwinCanvas({ onModelFallback }: { onModelFallback: () => void }) {
  const select = useTwinStore((s) => s.select);
  const ground = new Vector3((FLOOR_BOUNDS.max[0] - FLOOR_BOUNDS.min[0]) / 2, -0.2, -(FLOOR_BOUNDS.max[1] - FLOOR_BOUNDS.min[1]) / 2);
  return (
    <Canvas
      camera={{ position: OVERVIEW.position.toArray(), fov: 42, near: 0.3, far: 400 }}
      dpr={[1, 2]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onPointerMissed={() => select(null)}
      aria-label="3D digital twin of the simulated hospital"
      role="img"
    >
      <color attach="background" args={["#0b1324"]} />
      <fog attach="fog" args={["#0b1324", 80, 170]} />
      <hemisphereLight args={["#d6e6ff", "#0b1324", 0.9]} />
      <directionalLight position={[20, 60, 30]} intensity={1.3} />
      <directionalLight position={[-30, 25, -40]} intensity={0.35} color="#9fc6ff" />
      <mesh position={ground} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[400, 400]} />
        <meshBasicMaterial color="#0a1120" />
      </mesh>
      <Suspense fallback={<Loader />}>
        <ModelBoundary fallback={<ProceduralHospital />} onError={onModelFallback}>
          <HospitalModel />
        </ModelBoundary>
      </Suspense>
      <ZoneOverlay />
      <NetworkOverlay />
      <DependencyOverlay />
      <AttackPathOverlay />
      <TransientFlows />
      <AssetMarkers />
      <CameraRig />
    </Canvas>
  );
}

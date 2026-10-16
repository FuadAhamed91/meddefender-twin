import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { X } from "lucide-react";
import { useMemo, useRef } from "react";
import {
  AdditiveBlending,
  Color,
  CylinderGeometry,
  type Mesh,
  MeshBasicMaterial,
  NormalBlending,
  type QuadraticBezierCurve3,
  Quaternion,
  ShaderMaterial,
  SphereGeometry,
  Vector3,
} from "three";
import type { Line2 } from "three/addons/lines/Line2.js";
import { useNetworkGraph, useZones } from "../api/queries";
import type { AssetSummary, PolicyOutcome } from "../api/types";
import { planToWorld } from "../lib/coords";
import { OUTCOME, PATH_CLASS } from "../lib/status";
import { EDGE_TTL_MS, type TransientEdge, useTwinStore } from "../state/twin";
import { anchorOf, arc, LINK_HEIGHT } from "./curves";
import { FatLine } from "./FatLine";

const ARC_SEGMENTS = 24;

/**
 * Arc between two assets. Keyed on their plan positions rather than on the asset objects,
 * which are replaced on every live state update, so the line geometry stays put.
 */
function useAssetArc(source: AssetSummary | undefined, destination: AssetSummary | undefined, lift: number) {
  const sx = source?.position?.x;
  const sy = source?.position?.y;
  const dx = destination?.position?.x;
  const dy = destination?.position?.y;
  return useMemo(() => {
    if (sx === undefined || sy === undefined || dx === undefined || dy === undefined) return null;
    const curve = arc(planToWorld(sx, sy, LINK_HEIGHT), planToWorld(dx, dy, LINK_HEIGHT), lift);
    return { curve, points: curve.getPoints(ARC_SEGMENTS) };
  }, [sx, sy, dx, dy, lift]);
}

const UP = new Vector3(0, 1, 0);
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

const OUTCOME_LINE: Record<PolicyOutcome, { color: string; dashed: boolean; width: number }> = {
  PERMITTED: { color: OUTCOME.PERMITTED.color, dashed: false, width: 1.4 },
  BLOCKED: { color: OUTCOME.BLOCKED.color, dashed: true, width: 1.6 },
  ALLOWED_MONITOR_ONLY: { color: OUTCOME.ALLOWED_MONITOR_ONLY.color, dashed: true, width: 1.6 },
  TOPOLOGY: { color: "#64748b", dashed: false, width: 0.8 },
};

function Arrow({ start, mid, end, color, opacity }: { start: Vector3; mid: Vector3; end: Vector3; color: string; opacity: number }) {
  const t = 0.8;
  const position = new Vector3()
    .addScaledVector(start, (1 - t) * (1 - t))
    .addScaledVector(mid, 2 * (1 - t) * t)
    .addScaledVector(end, t * t);
  const tangent = mid.clone().sub(start).multiplyScalar(2 * (1 - t)).add(end.clone().sub(mid).multiplyScalar(2 * t)).normalize();
  const quaternion = new Quaternion().setFromUnitVectors(UP, tangent);
  return (
    <mesh position={position} quaternion={quaternion}>
      <coneGeometry args={[0.12, 0.34, 10]} />
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  );
}

function FlowArc({
  source,
  destination,
  color,
  dashed,
  width,
  opacity,
  lift = 0.9,
  arrow = true,
  dotted = false,
}: {
  source: AssetSummary | undefined;
  destination: AssetSummary | undefined;
  color: string;
  dashed: boolean;
  width: number;
  opacity: number;
  lift?: number;
  arrow?: boolean;
  dotted?: boolean;
}) {
  const geometry = useAssetArc(source, destination, lift);
  if (!geometry) return null;
  const { curve, points } = geometry;
  return (
    <group>
      <FatLine
        points={points}
        color={color}
        width={width}
        dashed={dashed}
        dashSize={dotted ? 0.1 : 0.35}
        gapSize={dotted ? 0.22 : 0.25}
        opacity={opacity}
      />
      {arrow ? <Arrow start={curve.v0} mid={curve.v1} end={curve.v2} color={color} opacity={opacity} /> : null}
    </group>
  );
}

// ---- zones ----------------------------------------------------------------------------------

export function ZoneOverlay() {
  const { data: zones = [] } = useZones();
  const visible = useTwinStore((s) => s.overlays.zones);
  if (!visible) return null;
  return (
    <group>
      {zones.map((zone) => {
        const [x0, y0] = zone.bounds.min;
        const [x1, y1] = zone.bounds.max;
        const corners = [
          planToWorld(x0 + 0.15, y0 + 0.15, 0.02),
          planToWorld(x1 - 0.15, y0 + 0.15, 0.02),
          planToWorld(x1 - 0.15, y1 - 0.15, 0.02),
          planToWorld(x0 + 0.15, y1 - 0.15, 0.02),
          planToWorld(x0 + 0.15, y0 + 0.15, 0.02),
        ];
        // Outline only: a tinted floor reads like an alert state, which a zone is not.
        return <FatLine key={zone.id} points={corners} color={zone.color} width={1.2} opacity={0.55} />;
      })}
    </group>
  );
}

// ---- network relationships ------------------------------------------------------------------

export function NetworkOverlay() {
  const { data } = useNetworkGraph();
  const assets = useTwinStore((s) => s.assets);
  const overlays = useTwinStore((s) => s.overlays);
  const selectedId = useTwinStore((s) => s.selectedId);
  const attackActive = useTwinStore((s) => s.attackPath !== null);
  const holo = useTwinStore((s) => s.viewMode === "holographic");
  if (!data || !overlays.network) return null;
  return (
    <group>
      {data.edges.map((edge) => {
        // L2 uplinks are physical attachment, not permission: listed in the inspector instead.
        if (edge.relationship_type === "L2_UPLINK") return null;
        const style = OUTCOME_LINE[edge.policy_status];
        const dotted = holo && edge.policy_status === "PERMITTED";
        const related = selectedId !== null && (edge.source === selectedId || edge.destination === selectedId);
        const dim = (selectedId !== null && !related) || attackActive;
        const observedPath = edge.origin === "OBSERVED";
        const color = observedPath && edge.policy_status === "PERMITTED" ? "#f5b945" : style.color;
        return (
          <FlowArc
            key={edge.id}
            source={assets[edge.source]}
            destination={assets[edge.destination]}
            color={color}
            dashed={style.dashed || observedPath || dotted}
            dotted={dotted}
            width={related ? style.width + 1 : style.width}
            opacity={dim ? 0.1 : related ? 0.95 : 0.55}
          />
        );
      })}
    </group>
  );
}

// ---- attack paths -------------------------------------------------------------------------

function Ring({ at, color, dashed = false, radius = 0.95 }: { at: Vector3; color: string; dashed?: boolean; radius?: number }) {
  return (
    <mesh position={[at.x, 0.035, at.z]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[radius - 0.08, radius, dashed ? 14 : 48]} />
      <meshBasicMaterial color={color} transparent opacity={0.9} depthWrite={false} />
    </mesh>
  );
}

export function AttackPathOverlay() {
  const result = useTwinStore((s) => s.attackPath);
  const plan = useTwinStore((s) => s.planPreview);
  const assets = useTwinStore((s) => s.assets);
  const hops = useMemo(() => {
    if (!result) return [];
    const seen = new Map<string, { source: string; destination: string; index: number; observed: boolean }>();
    for (const path of result.paths) {
      path.hops.forEach((hop, index) => {
        const key = `${hop.source}>${hop.destination}`;
        const prev = seen.get(key);
        if (!prev || index < prev.index) seen.set(key, { source: hop.source, destination: hop.destination, index, observed: hop.observed });
      });
    }
    return [...seen.values()];
  }, [result]);
  if (!result) return null;
  const entry = assets[result.entry_asset_id];
  const entryPos = anchorOf(entry, 0);
  const reachable = new Map(result.reachable_assets.map((r) => [r.asset_id, r]));
  return (
    <group>
      {entryPos ? (
        <>
          <Ring at={entryPos} color="#f04452" radius={1.15} />
          <Html position={[entryPos.x, 4.4, entryPos.z]} center zIndexRange={[25, 0]} style={{ pointerEvents: "none" }}>
            <div className="rounded border border-crit/60 bg-canvas/95 px-1.5 py-0.5 text-[10.5px] font-semibold whitespace-nowrap text-crit">
              Entry (assumed compromised)
            </div>
          </Html>
        </>
      ) : null}
      {hops.map((hop) => {
        const first = hop.index === 0;
        const cls = first ? (hop.observed ? PATH_CLASS.DEMONSTRATED : PATH_CLASS.PERMITTED) : PATH_CLASS.HYPOTHETICAL;
        return (
          <FlowArc
            key={`${hop.source}>${hop.destination}`}
            source={assets[hop.source]}
            destination={assets[hop.destination]}
            color={cls.color}
            dashed={!first}
            width={first ? 3 : 2}
            opacity={0.95}
            lift={1.4}
          />
        );
      })}
      {result.blocked_edges_from_entry.map((edge) => {
        const dst = anchorOf(assets[edge.destination]);
        return dst ? (
          <group key={`blocked-${edge.destination}-${edge.service}`}>
            <FlowArc source={entry} destination={assets[edge.destination]} color="#f04452" dashed width={1.6} opacity={0.75} lift={1.1} arrow={false} />
            <Html position={[dst.x, dst.y + 0.6, dst.z]} center zIndexRange={[24, 0]} style={{ pointerEvents: "none" }}>
              <span className="flex items-center gap-0.5 rounded border border-crit/60 bg-canvas/95 px-1 text-[10px] text-crit">
                <X aria-hidden className="size-3" />
                {edge.service} blocked
              </span>
            </Html>
          </group>
        ) : null;
      })}
      {result.reachable_assets.map((r) => {
        const p = anchorOf(assets[r.asset_id], 0);
        const cls = PATH_CLASS[r.classification];
        return p ? <Ring key={`reach-${r.asset_id}`} at={p} color={cls.color} dashed={r.classification === "HYPOTHETICAL"} /> : null;
      })}
      {result.nearby_unreachable
        .filter((n) => !reachable.has(n.asset_id))
        .map((n) => {
          const p = anchorOf(assets[n.asset_id], 0);
          return p ? (
            <group key={`near-${n.asset_id}`}>
              <Ring at={p} color="#64748b" dashed radius={0.85} />
              <Html position={[p.x, 0.25, p.z + 0.9]} center zIndexRange={[18, 0]} style={{ pointerEvents: "none" }}>
                <span className="rounded bg-canvas/85 px-1 text-[10px] whitespace-nowrap text-ink-muted">nearby · unreachable</span>
              </Html>
            </group>
          ) : null;
        })}
      {plan
        ? plan.analysis.blocked_flows.map((edge) => (
            <FlowArc
              key={`plan-${edge.source}-${edge.destination}-${edge.service}`}
              source={assets[edge.source]}
              destination={assets[edge.destination]}
              color="#f04452"
              dashed
              width={2.4}
              opacity={0.9}
              lift={0.6}
            />
          ))
        : null}
    </group>
  );
}

// ---- live flow pulses -------------------------------------------------------------------------

// A comet: bright head plus a short fading tail, so direction reads at a glance.
const TRAIL = [0, 0.035, 0.07, 0.105];
const BLOCK_POINT = 0.55;

// Comets come and go with every live event: they share one geometry and a few long-lived
// materials (one set per outcome color) instead of creating and disposing them each time.
const COMET_GEOMETRY = new SphereGeometry(0.15, 14, 14);
const cometMaterialCache = new Map<string, MeshBasicMaterial[]>();

function cometMaterials(color: string): MeshBasicMaterial[] {
  let materials = cometMaterialCache.get(color);
  if (!materials) {
    // HDR color (above 1.0) so the bloom pass gives the head a soft glow.
    const glow = new Color(color).multiplyScalar(2.4);
    materials = TRAIL.map(
      (_, i) => new MeshBasicMaterial({ color: glow, toneMapped: false, transparent: true, opacity: 1 - i * 0.27, depthWrite: false }),
    );
    cometMaterialCache.set(color, materials);
  }
  return materials;
}

function Comet({ curve, color, bornAt, blocked }: { curve: QuadraticBezierCurve3; color: string; bornAt: number; blocked: boolean }) {
  const refs = useRef<(Mesh | null)[]>([]);
  const reduced = useMemo(reducedMotion, []);
  const materials = cometMaterials(color);
  useFrame(() => {
    const age = (Date.now() - bornAt) / 1000;
    const stop = blocked ? BLOCK_POINT : 1;
    // A blocked flow travels to the enforcement point and halts there; permitted flows loop.
    const head = reduced ? stop : Math.min((age % 1.6) / 1.6, stop);
    TRAIL.forEach((lag, i) => {
      const mesh = refs.current[i];
      if (!mesh) return;
      const t = head - lag;
      mesh.visible = t >= 0 && (i === 0 || !reduced);
      if (mesh.visible) curve.getPoint(t, mesh.position);
    });
  });
  return (
    <>
      {TRAIL.map((lag, i) => (
        <mesh
          key={lag}
          ref={(mesh) => {
            refs.current[i] = mesh;
          }}
          geometry={COMET_GEOMETRY}
          material={materials[i]}
          scale={1 - i * 0.2}
          raycast={() => undefined}
        />
      ))}
    </>
  );
}

function TransientFlow({ edge, source, destination }: { edge: TransientEdge; source: AssetSummary; destination: AssetSummary }) {
  const line = useRef<Line2>(null);
  const geometry = useAssetArc(source, destination, 1.2);
  // Fade the arc out over its lifetime instead of letting it vanish abruptly.
  useFrame(() => {
    const material = line.current?.material;
    if (material) material.opacity = 0.85 * Math.max(0, 1 - (Date.now() - edge.at) / EDGE_TTL_MS);
  });
  if (!geometry) return null;
  const color = OUTCOME_LINE[edge.outcome]?.color ?? "#22c3d6";
  return (
    <group>
      <FatLine
        ref={line}
        points={geometry.points}
        color={color}
        width={2.2}
        dashed={edge.outcome !== "PERMITTED"}
        dashSize={0.3}
        gapSize={0.2}
        opacity={0.85}
      />
      <Comet curve={geometry.curve} color={color} bornAt={edge.at} blocked={edge.outcome === "BLOCKED"} />
    </group>
  );
}

/** Flows observed in the last few seconds (from the live event stream), drawn as moving comets. */
export function TransientFlows() {
  const edges = useTwinStore((s) => s.transientEdges);
  const assets = useTwinStore((s) => s.assets);
  return (
    <group>
      {edges.map((edge) => {
        const source = assets[edge.source];
        const destination = assets[edge.destination];
        return source && destination ? <TransientFlow key={edge.key} edge={edge} source={source} destination={destination} /> : null;
      })}
    </group>
  );
}


// ---- status beams ---------------------------------------------------------------------------

const BEAM_VERT = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;
  void main() {
    vUv = uv;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vPosW = world.xyz;
    vNormalW = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

// Soft light pillar: brightest along the axis facing the viewer, fading toward the top.
// pow() bases are clamped: a negative base returns NaN on D3D/ANGLE, and the bloom blur
// would spread a single NaN pixel across the whole frame.
const BEAM_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;
  void main() {
    float facing = clamp(abs(dot(normalize(vNormalW), normalize(cameraPosition - vPosW))), 0.0, 1.0);
    float core = pow(facing, 2.5);
    float fade = pow(clamp(1.0 - vUv.y, 0.0, 1.0), 1.1);
    gl_FragColor = vec4(uColor * (0.8 + 1.2 * core), uOpacity * (0.25 + 0.75 * core) * fade);
  }`;

// Beams appear and disappear with selection and state changes; like comets they share one
// geometry and cached materials so their shader program is compiled once.
const BEAM_GEOMETRY = new CylinderGeometry(0.32, 0.32, 4.5, 24, 1, true);
const beamMaterialCache = new Map<string, ShaderMaterial>();

function beamMaterial(color: string, opacity: number, additive: boolean): ShaderMaterial {
  const key = `${color}/${opacity}/${additive}`;
  let material = beamMaterialCache.get(key);
  if (!material) {
    material = new ShaderMaterial({
      uniforms: { uColor: { value: new Color(color) }, uOpacity: { value: opacity } },
      vertexShader: BEAM_VERT,
      fragmentShader: BEAM_FRAG,
      transparent: true,
      depthWrite: false,
      // Light adds up nicely on the dark holographic floor but vanishes on the bright
      // realistic one, where the pillar is drawn as an ordinary translucent column.
      blending: additive ? AdditiveBlending : NormalBlending,
    });
    beamMaterialCache.set(key, material);
  }
  return material;
}

function Beam({ at, color, opacity, additive }: { at: Vector3; color: string; opacity: number; additive: boolean }) {
  return (
    <mesh
      position={[at.x, 2.25, at.z]}
      geometry={BEAM_GEOMETRY}
      material={beamMaterial(color, opacity, additive)}
      raycast={() => undefined}
      renderOrder={3}
    />
  );
}

/**
 * A light pillar over the selected device and over devices whose backend state needs
 * attention, so they can be spotted from across the floor. It is the one state marker in the
 * scene besides the device tint. Static on purpose; motion stays reserved for live alerts.
 */
export function StatusBeams() {
  const assets = useTwinStore((s) => s.assets);
  const selectedId = useTwinStore((s) => s.selectedId);
  const holo = useTwinStore((s) => s.viewMode === "holographic");
  const beams: { id: string; at: Vector3; color: string; opacity: number }[] = [];
  for (const asset of Object.values(assets)) {
    if (!asset.position || asset.is_logical || !asset.is_active) continue;
    const at = planToWorld(asset.position.x, asset.position.y, 0);
    if (asset.id === selectedId) {
      beams.push({ id: asset.id, at, color: "#22c3d6", opacity: 0.8 });
      continue;
    }
    const contained = asset.containment_state === "ISOLATED" || asset.trust_state === "QUARANTINED";
    const state = asset.trust_state ?? "";
    if (contained) beams.push({ id: asset.id, at, color: "#f04452", opacity: 0.75 });
    else if (BEAM_STATES[state]) beams.push({ id: asset.id, at, color: BEAM_STATES[state], opacity: 0.65 });
    else if (asset.containment_state === "RESTRICTED") beams.push({ id: asset.id, at, color: "#f5b945", opacity: 0.65 });
  }
  return (
    <group>
      {beams.map((b) => (
        <Beam key={b.id} at={b.at} color={b.color} opacity={b.opacity} additive={holo} />
      ))}
    </group>
  );
}

const BEAM_STATES: Record<string, string> = {
  SUSPICIOUS: "#f5b945",
  REVOKED: "#d0647a",
  UNREGISTERED: "#c084fc",
};

import { Html, Line, QuadraticBezierLine } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Boxes, X } from "lucide-react";
import { useMemo, useRef } from "react";
import { type Mesh, Quaternion, Vector3 } from "three";
import { useDependencyGraph, useNetworkGraph, useZones } from "../api/queries";
import type { AssetSummary, PolicyOutcome } from "../api/types";
import { boundsCenter, planToWorld } from "../lib/coords";
import { OUTCOME, PATH_CLASS } from "../lib/status";
import { useTwinStore } from "../state/twin";
import { anchorOf, arc } from "./curves";

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
}: {
  source: AssetSummary | undefined;
  destination: AssetSummary | undefined;
  color: string;
  dashed: boolean;
  width: number;
  opacity: number;
  lift?: number;
  arrow?: boolean;
}) {
  const geometry = useMemo(() => {
    const a = anchorOf(source);
    const b = anchorOf(destination);
    if (!a || !b || !source || !destination) return null;
    const curve = arc(a, b, lift, source.id, destination.id);
    return { start: curve.v0, mid: curve.v1, end: curve.v2 };
  }, [source, destination, lift]);
  if (!geometry) return null;
  return (
    <group>
      <QuadraticBezierLine
        start={geometry.start}
        end={geometry.end}
        mid={geometry.mid}
        color={color}
        lineWidth={width}
        dashed={dashed}
        dashSize={0.35}
        gapSize={0.25}
        transparent
        opacity={opacity}
        depthWrite={false}
      />
      {arrow ? <Arrow {...geometry} color={color} opacity={opacity} /> : null}
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
        const center = boundsCenter(zone.bounds, 0.015);
        return (
          <group key={zone.id}>
            <mesh position={center} rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[x1 - x0, y1 - y0]} />
              <meshBasicMaterial color={zone.color} transparent opacity={0.05} depthWrite={false} />
            </mesh>
            <Line points={corners} color={zone.color} lineWidth={1} transparent opacity={0.45} depthWrite={false} />
            <Html
              transform
              position={planToWorld(x0 + 0.6, y0 + 0.9, 0.05)}
              rotation={[-Math.PI / 2, 0, 0]}
              distanceFactor={9}
              style={{ pointerEvents: "none" }}
            >
              <div className="origin-bottom-left whitespace-nowrap select-none" style={{ transform: "translate(50%, -50%)" }}>
                <div className="text-[13px] font-semibold tracking-[0.12em] uppercase" style={{ color: zone.color }}>
                  {zone.name}
                </div>
                <div className="font-mono text-[10px] text-ink-muted">
                  VLAN {zone.vlan_id} · {zone.subnet}
                </div>
              </div>
            </Html>
          </group>
        );
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
  if (!data || (!overlays.network && !overlays.topology)) return null;
  return (
    <group>
      {data.edges.map((edge) => {
        const l2 = edge.relationship_type === "L2_UPLINK";
        if (l2 ? !overlays.topology : !overlays.network) return null;
        const style = OUTCOME_LINE[edge.policy_status];
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
            dashed={style.dashed || observedPath}
            width={related ? style.width + 1 : style.width}
            opacity={dim ? 0.1 : related ? 0.95 : l2 ? 0.35 : 0.55}
            lift={l2 ? 0.2 : 0.9}
            arrow={!l2}
          />
        );
      })}
    </group>
  );
}

// ---- operational dependencies -----------------------------------------------------------------

export function DependencyOverlay() {
  const { data } = useDependencyGraph();
  const assets = useTwinStore((s) => s.assets);
  const visible = useTwinStore((s) => s.overlays.dependencies);
  const selectedId = useTwinStore((s) => s.selectedId);
  const select = useTwinStore((s) => s.select);

  // Logical services have no physical location: float them above the centroid of what
  // they depend on, so their dependency arcs stay readable.
  const servicePositions = useMemo(() => {
    const out: Record<string, Vector3> = {};
    if (!data) return out;
    const services = data.nodes.filter((n) => n.is_logical);
    for (let pass = 0; pass < 3; pass++) {
      for (const svc of services) {
        const points = data.edges
          .filter((e) => e.dependent === svc.id)
          .map((e) => (assets[e.provider]?.position ? planToWorld(assets[e.provider].position!.x, assets[e.provider].position!.y, 0) : out[e.provider]))
          .filter((p): p is Vector3 => Boolean(p));
        if (points.length) {
          const c = points.reduce((acc, p) => acc.add(p), new Vector3()).multiplyScalar(1 / points.length);
          out[svc.id] = new Vector3(c.x, 7.5, c.z);
        }
      }
    }
    return out;
  }, [data, assets]);

  if (!data || !visible) return null;
  const pos = (id: string): Vector3 | null => {
    const asset = assets[id];
    if (asset?.position) return planToWorld(asset.position.x, asset.position.y, 3.2);
    return servicePositions[id] ?? null;
  };
  return (
    <group>
      {data.edges.map((edge) => {
        const a = pos(edge.dependent);
        const b = pos(edge.provider);
        if (!a || !b) return null;
        const related = selectedId !== null && (edge.dependent === selectedId || edge.provider === selectedId);
        const dim = selectedId !== null && !related;
        const mid = a.clone().add(b).multiplyScalar(0.5).add(new Vector3(0, 2.2, 0));
        return (
          <QuadraticBezierLine
            key={edge.id}
            start={a}
            end={b}
            mid={mid}
            color="#a78bfa"
            lineWidth={related ? 2 : 1}
            dashed
            dashSize={0.12}
            gapSize={0.18}
            transparent
            opacity={dim ? 0.08 : related ? 0.95 : 0.45}
            depthWrite={false}
          />
        );
      })}
      {data.nodes
        .filter((n) => n.is_logical && servicePositions[n.id])
        .map((svc) => (
          <Html key={svc.id} position={servicePositions[svc.id]} center zIndexRange={[19, 0]}>
            <button
              type="button"
              onClick={() => select(svc.id)}
              aria-label={`${svc.display_name} (logical service)`}
              className={`flex cursor-pointer items-center gap-1 rounded-md border bg-canvas/90 px-1.5 py-0.5 text-[11px] whitespace-nowrap shadow-lg ${
                selectedId === svc.id ? "border-dep text-ink" : "border-dep/50 text-ink-muted hover:text-ink"
              }`}
            >
              <Boxes aria-hidden className="size-3 text-dep" />
              {svc.display_name}
            </button>
          </Html>
        ))}
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
          <Html position={[entryPos.x, 3.3, entryPos.z]} center zIndexRange={[25, 0]} style={{ pointerEvents: "none" }}>
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

function Pulse({ start, mid, end, color, bornAt, blocked }: { start: Vector3; mid: Vector3; end: Vector3; color: string; bornAt: number; blocked: boolean }) {
  const ref = useRef<Mesh>(null);
  const reduced = useMemo(reducedMotion, []);
  useFrame(() => {
    if (!ref.current) return;
    const age = (Date.now() - bornAt) / 1000;
    let t = reduced ? (blocked ? 0.55 : 1) : (age % 1.6) / 1.6;
    if (blocked) t = Math.min(t, 0.55);
    const p = new Vector3()
      .addScaledVector(start, (1 - t) * (1 - t))
      .addScaledVector(mid, 2 * (1 - t) * t)
      .addScaledVector(end, t * t);
    ref.current.position.copy(p);
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.16, 12, 12]} />
      <meshBasicMaterial color={color} />
    </mesh>
  );
}

export function TransientFlows() {
  const edges = useTwinStore((s) => s.transientEdges);
  const assets = useTwinStore((s) => s.assets);
  return (
    <group>
      {edges.map((edge) => {
        const src = assets[edge.source];
        const dst = assets[edge.destination];
        const a = anchorOf(src);
        const b = anchorOf(dst);
        if (!a || !b || !src || !dst) return null;
        const curve = arc(a, b, 1.2, src.id, dst.id);
        const color = OUTCOME_LINE[edge.outcome]?.color ?? "#22c3d6";
        return (
          <group key={edge.key}>
            <QuadraticBezierLine start={curve.v0} end={curve.v2} mid={curve.v1} color={color} lineWidth={2.2} dashed={edge.outcome !== "PERMITTED"} dashSize={0.3} gapSize={0.2} transparent opacity={0.85} depthWrite={false} />
            <Pulse start={curve.v0} mid={curve.v1} end={curve.v2} color={color} bornAt={edge.at} blocked={edge.outcome === "BLOCKED"} />
          </group>
        );
      })}
    </group>
  );
}

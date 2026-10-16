import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Siren } from "lucide-react";
import { memo, useMemo, useRef } from "react";
import type { Mesh } from "three";
import type { AssetSummary } from "../api/types";
import { cx } from "../components/ui/primitives";
import { planToWorld } from "../lib/coords";
import { SEVERITY, trustStyle } from "../lib/status";
import { useTwinStore } from "../state/twin";

const prefersReducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
const ABNORMAL_TRUST = ["SUSPICIOUS", "QUARANTINED", "REVOKED", "UNREGISTERED"];

/** Floor ring under the selected asset, or pulsing under one that just raised an alert. */
function GroundRing({ asset, color, pulse }: { asset: AssetSummary; color: string; pulse: boolean }) {
  const ref = useRef<Mesh>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const s = pulse && !reduced ? 1 + 0.18 * (0.5 + 0.5 * Math.sin(clock.elapsedTime * 4)) : 1;
    ref.current.scale.set(s, s, s);
  });
  const p = asset.position!;
  return (
    <mesh ref={ref} position={planToWorld(p.x, p.y, 0.03)} rotation={[-Math.PI / 2, 0, 0]} raycast={() => undefined}>
      <ringGeometry args={[0.62, 0.78, 40]} />
      <meshBasicMaterial color={color} transparent opacity={0.85} depthWrite={false} />
    </mesh>
  );
}

/**
 * One device. Only the devices that matter right now (selected, hovered, recently alerting,
 * or in an abnormal trust or containment state) get a labelled chip; the others are a small
 * dot, which keeps the floor readable. Every device stays reachable from the asset list,
 * the model itself and its dot.
 */
const Marker = memo(function Marker({
  asset,
  selected,
  hovered,
  flash,
  dimmed,
}: {
  asset: AssetSummary;
  selected: boolean;
  hovered: boolean;
  flash: { severity: keyof typeof SEVERITY } | undefined;
  dimmed: boolean;
}) {
  const select = useTwinStore((s) => s.select);
  const hover = useTwinStore((s) => s.hover);
  const trust = trustStyle(asset.trust_state);
  const Icon = trust.icon;
  const abnormal = ABNORMAL_TRUST.includes(asset.trust_state ?? "") || asset.containment_state !== "NONE";
  const incident = asset.open_incident_count > 0;
  const p = asset.position!;
  const anchor = planToWorld(p.x, p.y, asset.label_height ?? 2);
  const sev = flash ? SEVERITY[flash.severity] : null;
  const chip = selected || hovered || flash !== undefined || abnormal || asset.discovered;
  const label = `${asset.id}, ${asset.display_name}. ${trust.label}${incident ? `, ${asset.open_incident_count} open incident(s)` : ""}${asset.containment_state !== "NONE" ? `, ${asset.containment_state.toLowerCase()}` : ""}`;

  return (
    <>
      {selected ? <GroundRing asset={asset} color="#22c3d6" pulse={false} /> : flash ? <GroundRing asset={asset} color={sev?.color ?? trust.color} pulse /> : null}
      {asset.discovered ? (
        // A rogue endpoint has no geometry in the model: draw a placeholder where it was seen.
        <mesh position={planToWorld(p.x, p.y, 0.6)} raycast={() => undefined}>
          <boxGeometry args={[0.5, 1.2, 0.5]} />
          <meshBasicMaterial color="#c084fc" wireframe transparent opacity={0.8} />
        </mesh>
      ) : null}
      {chip ? (
        <Html position={anchor} center zIndexRange={[20, 0]} style={{ pointerEvents: "auto" }}>
          <button
            type="button"
            aria-label={label}
            aria-pressed={selected}
            onClick={(e) => {
              e.stopPropagation();
              select(asset.id);
            }}
            onMouseEnter={() => hover(asset.id)}
            onMouseLeave={() => hover(null)}
            className={cx(
              "flex cursor-pointer items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap shadow-lg backdrop-blur-sm transition-opacity duration-150 select-none",
              selected ? "border-accent bg-canvas/95 text-ink" : "border-line-strong bg-canvas/85 text-ink-muted hover:text-ink",
              dimmed && !selected && "opacity-35",
            )}
            style={{ borderColor: selected ? undefined : abnormal ? `${trust.color}aa` : undefined }}
          >
            <Icon aria-hidden className="size-3 shrink-0" style={{ color: trust.color }} />
            <span className="font-mono text-[10.5px] text-ink">{asset.id}</span>
            {abnormal ? <span style={{ color: trust.color }}>{asset.containment_state !== "NONE" ? asset.containment_state.toLowerCase() : trust.label}</span> : null}
            {incident ? (
              <span className="flex items-center gap-0.5 rounded bg-high/20 px-1 text-high" title={`${asset.open_incident_count} open incident(s)`}>
                <Siren aria-hidden className={cx("size-3", flash && "animate-pulse")} />
                <span className="tabular">{asset.open_incident_count}</span>
              </span>
            ) : null}
          </button>
        </Html>
      ) : (
        <mesh
          position={anchor}
          onClick={(e) => {
            e.stopPropagation();
            select(asset.id);
          }}
          // Hovering a dot only changes the cursor: swapping it for a chip under the pointer
          // would steal the hover and flicker.
          onPointerOver={(e) => {
            e.stopPropagation();
            document.body.style.cursor = "pointer";
          }}
          onPointerOut={() => {
            document.body.style.cursor = "";
          }}
        >
          <sphereGeometry args={[0.11, 12, 12]} />
          <meshBasicMaterial color="#67e0ec" transparent opacity={dimmed ? 0.25 : 0.85} depthWrite={false} />
        </mesh>
      )}
    </>
  );
});

export function AssetMarkers() {
  const assets = useTwinStore((s) => s.assets);
  const selectedId = useTwinStore((s) => s.selectedId);
  const hoveredId = useTwinStore((s) => s.hoveredId);
  const flashes = useTwinStore((s) => s.flashes);
  const highlight = useTwinStore((s) => s.highlight);
  const list = Object.values(assets).filter((a) => a.position && !a.is_logical && a.is_active);
  const focusSet = highlight ? new Set(highlight.assets) : null;
  return (
    <group>
      {list.map((asset) => (
        <Marker
          key={asset.id}
          asset={asset}
          selected={asset.id === selectedId}
          hovered={asset.id === hoveredId}
          flash={flashes[asset.id] as { severity: keyof typeof SEVERITY } | undefined}
          dimmed={Boolean(focusSet && !focusSet.has(asset.id))}
        />
      ))}
    </group>
  );
}

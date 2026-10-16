import { useRooms, useZones } from "../api/queries";
import { FLOOR_BOUNDS } from "../lib/coords";
import { trustStyle } from "../lib/status";
import { useTwinStore } from "../state/twin";

const W = FLOOR_BOUNDS.max[0];
const H = FLOOR_BOUNDS.max[1];

/** 2D floor plan for orientation: rooms, devices (trust state) and incident markers.
 *  Rooms focus the camera on their zone; dots select the asset. */
export function Minimap() {
  const { data: rooms = [] } = useRooms();
  const { data: zones = [] } = useZones();
  const assets = useTwinStore((s) => s.assets);
  const selectedId = useTwinStore((s) => s.selectedId);
  const select = useTwinStore((s) => s.select);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const zoneColor = (id: string | null) => zones.find((z) => z.id === id)?.color ?? "#64748b";
  const list = Object.values(assets).filter((a) => a.position && !a.is_logical && a.is_active);
  return (
    <figure className="pointer-events-auto w-56 rounded-md border border-line bg-canvas/90 p-1.5 shadow-xl">
      <svg viewBox={`-1 -1 ${W + 2} ${H + 2}`} className="block w-full" role="group" aria-label="Floor plan minimap">
        {rooms.map((room) => {
          const [x0, y0] = room.bounds.min;
          const [x1, y1] = room.bounds.max;
          return (
            <rect
              key={room.id}
              x={x0 + 0.15}
              y={H - y1 + 0.15}
              width={x1 - x0 - 0.3}
              height={y1 - y0 - 0.3}
              rx={0.4}
              fill={room.area_zone_id ? `${zoneColor(room.area_zone_id)}22` : "#94a3b80f"}
              stroke={room.area_zone_id ? `${zoneColor(room.area_zone_id)}99` : "#94a3b855"}
              strokeWidth={0.18}
              className="cursor-pointer hover:opacity-80"
              onClick={() => room.area_zone_id && requestFocus("zone", [room.area_zone_id])}
            >
              <title>{room.name}</title>
            </rect>
          );
        })}
        {list.map((a) => {
          const style = trustStyle(a.trust_state);
          const x = a.position!.x;
          const y = H - a.position!.y;
          const alert = a.open_incident_count > 0 || ["SUSPICIOUS", "QUARANTINED", "UNREGISTERED", "REVOKED"].includes(a.trust_state ?? "");
          return (
            <g key={a.id} className="cursor-pointer" onClick={() => select(a.id)}>
              <title>{`${a.id}: ${style.label}${a.open_incident_count ? `, ${a.open_incident_count} open incident(s)` : ""}`}</title>
              {alert ? <circle cx={x} cy={y} r={1.45} fill="none" stroke={a.open_incident_count ? "#f2803a" : style.color} strokeWidth={0.3} /> : null}
              {a.id === selectedId ? <circle cx={x} cy={y} r={1.2} fill="none" stroke="#67e0ec" strokeWidth={0.35} /> : null}
              <circle cx={x} cy={y} r={a.trust_state ? 0.65 : 0.45} fill={a.trust_state ? style.color : "#64748b"} />
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-0.5 flex justify-between text-[10px] text-ink-muted">
        <span>Floor plan</span>
        <span>N ↑</span>
      </figcaption>
    </figure>
  );
}

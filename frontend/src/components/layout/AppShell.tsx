import { useQueryClient } from "@tanstack/react-query";
import {
  Box,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Pause,
  Play,
  ScrollText,
  ShieldCheck,
  Siren,
  Waypoints,
} from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router";
import { api, errorMessage, setCsrfToken } from "../../api/client";
import { qk, useIncidents, useSimulationStatus, useToggleGenerator } from "../../api/queries";
import type { User } from "../../api/types";
import { LiveConnection } from "../../state/live";
import { useTwinStore } from "../../state/twin";
import { cx } from "../ui/primitives";
import { toast } from "../ui/toast";

const NAV = [
  { to: "/", label: "Twin", icon: Box, end: true },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/incidents", label: "Incidents", icon: Siren },
  { to: "/scenarios", label: "Scenarios", icon: FlaskConical },
  { to: "/policies", label: "Policies", icon: Waypoints },
  { to: "/audit", label: "Audit", icon: ScrollText },
];

const CONNECTION = {
  connecting: { label: "Connecting", className: "text-ink-muted", dot: "bg-ink-faint" },
  live: { label: "Live", className: "text-ok", dot: "bg-ok" },
  reconnecting: { label: "Reconnecting", className: "text-warn", dot: "bg-warn animate-pulse" },
  offline: { label: "Offline", className: "text-crit", dot: "bg-crit" },
};

export function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const queryClient = useQueryClient();
  const live = useRef<LiveConnection | null>(null);
  const connection = useTwinStore((s) => s.connection);
  const { data: status } = useSimulationStatus();
  const toggle = useToggleGenerator();
  const { data: open = [] } = useIncidents({ open_only: true });
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const conn = CONNECTION[connection];
  const canOperate = user.permissions.includes("toggle_generator");

  useEffect(() => {
    const connectionInstance = new LiveConnection(queryClient);
    live.current = connectionInstance;
    void connectionInstance.start();
    return () => connectionInstance.stop();
  }, [queryClient]);

  // Move focus to the main region on navigation (screen-reader friendly).
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  const logout = async () => {
    try {
      await api.post("/api/v1/auth/logout");
    } catch {
      /* the session may already be gone */
    }
    setCsrfToken(null);
    live.current?.stop();
    queryClient.setQueryData(qk.me, null);
    queryClient.clear();
  };

  return (
    <div className="flex h-dvh min-h-0 flex-col">
      <a href="#main" className="sr-only z-50 rounded bg-accent px-3 py-2 text-canvas focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to main content
      </a>
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-3">
        <div className="flex items-center gap-2">
          <ShieldCheck aria-hidden className="size-5 text-accent" />
          <span className="text-[15px] font-semibold tracking-tight">MedDefender Twin</span>
        </div>
        <span
          className="hidden rounded border border-warn/40 bg-warn/10 px-1.5 py-0.5 text-[11px] font-semibold tracking-wider text-warn uppercase sm:inline"
          title="Every asset, flow, value and attack in this application is synthetic."
        >
          Simulation · synthetic data
        </span>
        <div className="ml-auto flex items-center gap-2 text-[12px]">
          {status ? (
            <span className="hidden text-ink-muted md:inline" title="Simulation baseline epoch (increments on reset)">
              Baseline <span className="font-mono text-ink">#{status.epoch}</span>
            </span>
          ) : null}
          {status ? (
            <button
              type="button"
              disabled={!canOperate || toggle.isPending}
              onClick={() =>
                toggle.mutate(!status.generator_enabled, {
                  onError: (e) => toast.error(errorMessage(e)),
                })
              }
              className="flex cursor-pointer items-center gap-1 rounded-md border border-line-strong px-2 py-1 text-ink-muted hover:text-ink disabled:cursor-default disabled:opacity-70"
              aria-label={status.generator_enabled ? "Pause the telemetry generator" : "Resume the telemetry generator"}
              title={canOperate ? "Toggle simulated device telemetry" : "Operator role required"}
            >
              {status.generator_enabled ? <Pause aria-hidden className="size-3.5" /> : <Play aria-hidden className="size-3.5" />}
              <span>Generator {status.generator_enabled ? "on" : "paused"}</span>
            </button>
          ) : null}
          <span className={cx("flex items-center gap-1.5 rounded-md border border-line px-2 py-1", conn.className)} role="status" aria-live="polite">
            <span aria-hidden className={cx("size-2 rounded-full", conn.dot)} />
            {conn.label}
          </span>
          <span className="hidden items-center gap-1.5 border-l border-line pl-3 text-ink-muted lg:flex">
            <span className="text-ink">{user.display_name}</span>
            <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10.5px] font-semibold tracking-wide">{user.role.replace("_", " ")}</span>
          </span>
          <button
            type="button"
            aria-label="Sign out"
            onClick={logout}
            className="flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-ink-muted hover:bg-surface-2 hover:text-ink"
          >
            <LogOut aria-hidden className="size-3.5" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Primary" className="flex w-16 shrink-0 flex-col items-stretch gap-1 border-r border-line bg-surface py-2 md:w-20">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cx(
                  "relative mx-1.5 flex flex-col items-center gap-0.5 rounded-md py-2 text-[11px] font-medium transition-colors",
                  isActive ? "bg-accent-soft text-accent-strong" : "text-ink-muted hover:bg-surface-2 hover:text-ink",
                )
              }
            >
              <item.icon aria-hidden className="size-5" />
              {item.label}
              {item.to === "/incidents" && open.length > 0 ? (
                <span className="absolute top-1 right-1.5 rounded-full bg-high px-1 text-[10px] leading-4 font-semibold text-canvas tabular" aria-label={`${open.length} open incidents`}>
                  {open.length}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <main id="main" ref={mainRef} tabIndex={-1} className="min-h-0 min-w-0 flex-1 overflow-hidden focus:outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}

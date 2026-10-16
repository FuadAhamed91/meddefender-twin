import { Siren } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { errorMessage } from "../api/client";
import { useIncidents } from "../api/queries";
import { EmptyState, ErrorNote, Panel, Spinner, StatusBadge } from "../components/ui/primitives";
import { ago, titleCase } from "../lib/format";
import { INCIDENT_STATUS, SEVERITY } from "../lib/status";

export default function IncidentsPage() {
  const [openOnly, setOpenOnly] = useState(false);
  const [previous, setPrevious] = useState(false);
  const { data = [], isPending, error, refetch } = useIncidents({ open_only: openOnly, include_previous_epochs: previous });
  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-[1400px] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">Incidents</h1>
          <div className="flex items-center gap-4 text-[12.5px]">
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} className="accent-[#22c3d6]" />
              Open only
            </label>
            <label className="flex cursor-pointer items-center gap-1.5" title="Incidents from earlier simulation baselines are kept read-only">
              <input type="checkbox" checked={previous} onChange={(e) => setPrevious(e.target.checked)} className="accent-[#22c3d6]" />
              Include previous baselines
            </label>
          </div>
        </div>
        <Panel bodyClassName="overflow-x-auto p-0">
          {isPending ? (
            <Spinner label="Loading incidents" />
          ) : error ? (
            <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />
          ) : data.length === 0 ? (
            <EmptyState icon={Siren} title="No incidents">
              Incidents open automatically when detection rules fire. Run a scenario to exercise them.
            </EmptyState>
          ) : (
            <table className="w-full text-[13px]">
              <caption className="sr-only">Incidents</caption>
              <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Reference</th>
                  <th scope="col" className="px-3 py-2 font-medium">Title</th>
                  <th scope="col" className="px-3 py-2 font-medium">Severity</th>
                  <th scope="col" className="px-3 py-2 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 font-medium">Category</th>
                  <th scope="col" className="px-3 py-2 font-medium">Alerts</th>
                  <th scope="col" className="px-3 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {data.map((incident) => (
                  <tr key={incident.id} className="border-t border-line hover:bg-surface-2">
                    <td className="px-3 py-2 whitespace-nowrap">
                      <Link to={`/incidents/${incident.id}`} className="font-mono text-[12px] text-accent-strong hover:underline">
                        {incident.reference}
                      </Link>
                      {previous ? <span className="ml-1 text-[11px] text-ink-faint">b#{incident.epoch}</span> : null}
                    </td>
                    <td className="px-3 py-2">
                      <Link to={`/incidents/${incident.id}`} className="hover:underline">
                        {incident.title}
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge size="xs" status={SEVERITY[incident.severity]} />
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge size="xs" status={INCIDENT_STATUS[incident.status]} />
                    </td>
                    <td className="px-3 py-2 text-ink-muted">{titleCase(incident.category)}</td>
                    <td className="px-3 py-2 tabular">{incident.alert_count}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-ink-muted">{ago(incident.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
}

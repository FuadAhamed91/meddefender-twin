import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";
import { useMe } from "./api/queries";
import { AppShell } from "./components/layout/AppShell";
import { Spinner } from "./components/ui/primitives";
import { Toaster } from "./components/ui/toast";
import { LoginPage } from "./pages/LoginPage";

const TwinPage = lazy(() => import("./pages/TwinPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const IncidentsPage = lazy(() => import("./pages/IncidentsPage"));
const IncidentDetailPage = lazy(() => import("./pages/IncidentDetailPage"));
const ScenariosPage = lazy(() => import("./pages/ScenariosPage"));
const PoliciesPage = lazy(() => import("./pages/PoliciesPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));

export function App() {
  const me = useMe();
  if (me.isPending) return <Spinner label="Checking session" />;
  if (!me.data) {
    return (
      <>
        <LoginPage />
        <Toaster />
      </>
    );
  }
  return (
    <>
      <AppShell user={me.data}>
        <Suspense fallback={<Spinner label="Loading view" />}>
          <Routes>
            <Route path="/" element={<TwinPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
            <Route path="/scenarios" element={<ScenariosPage />} />
            <Route path="/policies" element={<PoliciesPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AppShell>
      <Toaster />
    </>
  );
}

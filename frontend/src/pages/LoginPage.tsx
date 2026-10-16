import { useQueryClient } from "@tanstack/react-query";
import { LogIn, ShieldCheck } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { api, errorMessage, setCsrfToken } from "../api/client";
import { qk } from "../api/queries";
import type { User } from "../api/types";
import { Button } from "../components/ui/primitives";

export function LoginPage() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const userId = useId();
  const passId = useId();
  const errId = useId();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ user: User; csrf_token: string }>("/api/v1/auth/login", { username, password });
      setCsrfToken(result.csrf_token);
      queryClient.setQueryData(qk.me, result.user);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <ShieldCheck aria-hidden className="size-7 text-accent" />
          <div>
            <h1 className="text-lg font-semibold tracking-tight">MedDefender Twin</h1>
            <p className="text-[13px] text-ink-muted">Healthcare IoT security simulation</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-line bg-surface p-5" aria-describedby={error ? errId : undefined}>
          <div className="space-y-1">
            <label htmlFor={userId} className="block text-[13px] font-medium">
              Username
            </label>
            <input
              id={userId}
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="h-10 w-full rounded-md border border-line-strong bg-canvas px-3 text-sm focus:border-accent focus:outline-none"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor={passId} className="block text-[13px] font-medium">
              Password
            </label>
            <input
              id={passId}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 w-full rounded-md border border-line-strong bg-canvas px-3 text-sm focus:border-accent focus:outline-none"
            />
          </div>
          {error ? (
            <p id={errId} role="alert" className="rounded-md border border-crit/40 bg-crit/10 px-3 py-2 text-[13px]">
              {error}
            </p>
          ) : null}
          <Button type="submit" variant="primary" icon={LogIn} loading={busy} className="w-full">
            Sign in
          </Button>
        </form>
        <div className="mt-4 rounded-lg border border-warn/30 bg-warn/5 p-3 text-[12px] leading-relaxed text-ink-muted">
          <p className="font-semibold text-warn">Simulation only</p>
          <p>
            All assets, telemetry, network traffic and attacks are synthetic. Demo accounts (viewer, operator, secadmin) are created by the seed
            command from the passwords in your local <span className="font-mono">.env</span>.
          </p>
        </div>
      </div>
    </main>
  );
}

"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Cpu,
  Database,
  RefreshCw,
  Server,
  Zap,
} from "lucide-react";
import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { apiClient, ApiError } from "@/lib/api-client";
import { parseReadiness, type Readiness, type ServiceKey, type CheckStatus } from "@/lib/health";
import { cn } from "@/lib/utils";

const SERVICES = [
  {
    key: "database",
    name: "PostgreSQL / pgvector",
    description: "Critical database SELECT 1; extension functionality is not probed",
    icon: Database,
  },
  { key: "redis", name: "Redis", description: "Critical Redis ping", icon: Zap },
  {
    key: "llm",
    name: "LLM provider",
    description: "Configuration only; no Provider request",
    icon: Cpu,
  },
  {
    key: "embedding",
    name: "Embedding provider",
    description: "Configuration only; no embedding request",
    icon: Cpu,
  },
  {
    key: "worker",
    name: "Background worker",
    description: "Broker configuration only; Worker connectivity not checked",
    icon: Activity,
  },
  {
    key: "knowledge_agent",
    name: "Knowledge Agent",
    description: "Enablement and required Provider configuration only",
    icon: Server,
  },
] satisfies { key: ServiceKey; name: string; description: string; icon: typeof Server }[];
const LABEL: Record<CheckStatus, string> = {
  healthy: "Healthy",
  unhealthy: "Unhealthy",
  configured: "Configured",
  not_configured: "Not configured",
  unknown: "Unknown",
};

export default function SystemHealthPage() {
  const [resp, setResp] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState(false);
  const [auto, setAuto] = useState(true);
  const active = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const load = useCallback(async () => {
    if (active.current || !mounted.current) return;
    const controller = new AbortController();
    active.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 8000);
    setLoading(true);
    try {
      let value: unknown;
      try {
        value = await apiClient.get<unknown>("/health/ready", {
          signal: controller.signal,
          cache: "no-store",
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 503) value = err.data;
        else throw err;
      }
      const data = parseReadiness(value);
      if (!data) throw new Error("Invalid readiness response");
      if (mounted.current && active.current === controller && !controller.signal.aborted) {
        setResp(data);
        setError(false);
      }
    } catch {
      if (mounted.current && active.current === controller) {
        setResp(null);
        setError(true);
      }
    } finally {
      window.clearTimeout(timer);
      if (mounted.current && active.current === controller) {
        setLoading(false);
        setLastChecked(new Date());
        active.current = null;
      }
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      active.current?.abort();
      active.current = null;
    };
  }, [load]);
  useEffect(() => {
    if (!auto) return;
    const id = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(id);
  }, [auto, load]);
  const ready = resp?.status === "ready";
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => setAuto((a) => !a)}>
          Auto-refresh {auto ? "on" : "off"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>
      <section className="border-border bg-card rounded-xl border p-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {ready ? <CheckCircle2 className="h-5 w-5" /> : <AlertCircle className="h-5 w-5" />}
            <div>
              <p className="text-muted-foreground text-xs">API readiness</p>
              <p className="text-foreground font-semibold" role="status">
                {resp
                  ? ready
                    ? "API dependencies ready"
                    : "API not ready"
                  : "Readiness unavailable"}
              </p>
            </div>
          </div>
          {lastChecked && (
            <span className="text-muted-foreground text-xs">
              Checked {lastChecked.toLocaleTimeString()}
            </span>
          )}
        </div>
      </section>
      {loading && !resp && !error ? (
        <LoadingState variant="stats" rows={6} />
      ) : (
        <section className="border-border bg-card rounded-xl border">
          <div className="border-border border-b px-5 py-4">
            <h2 className="text-foreground text-sm font-semibold">Services</h2>
            <p className="text-muted-foreground text-xs">
              {error
                ? "Readiness check failed or is unavailable."
                : "Critical dependency probes and optional configuration status. Auto-refresh every 30s."}
            </p>
          </div>
          <ul className="divide-border divide-y">
            {SERVICES.map((service) => {
              const check = resp?.checks[service.key];
              const status = check?.status ?? "unknown";
              return (
                <li key={service.key} className="flex items-center gap-3 px-5 py-4">
                  <service.icon className="text-muted-foreground h-4 w-4" />
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground text-sm font-medium">{service.name}</p>
                    <p className="text-muted-foreground text-xs">{service.description}</p>
                    {check?.error && <p className="text-destructive text-xs">{check.error}</p>}
                    {check?.connectivity_checked === false && (
                      <p className="text-muted-foreground text-xs">Connectivity not checked</p>
                    )}
                    {service.key === "knowledge_agent" && check?.enabled === false && (
                      <p className="text-muted-foreground text-xs">Disabled</p>
                    )}
                  </div>
                  {typeof check?.latency_ms === "number" && (
                    <span className="text-muted-foreground text-xs">
                      Single probe: {check.latency_ms}ms
                    </span>
                  )}
                  <span
                    className={cn(
                      "text-xs font-medium",
                      status === "unhealthy" ? "text-destructive" : "text-muted-foreground",
                    )}
                  >
                    {LABEL[status]}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      <p className="text-muted-foreground text-xs">
        Readiness covers PostgreSQL and Redis. Optional configuration does not establish Worker task
        execution, Provider connectivity or historical availability.
      </p>
    </div>
  );
}

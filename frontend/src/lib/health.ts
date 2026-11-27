/** Bounded allowlist for public readiness data, shared by proxy and system page. */
export const SERVICE_KEYS = [
  "database",
  "redis",
  "llm",
  "embedding",
  "worker",
  "knowledge_agent",
] as const;
export type ServiceKey = (typeof SERVICE_KEYS)[number];
export type CheckStatus = "healthy" | "unhealthy" | "configured" | "not_configured" | "unknown";
export interface ServiceCheck {
  status: CheckStatus;
  latency_ms?: number;
  error?: string;
  type?: "postgresql";
  connectivity_checked?: false;
  enabled?: boolean;
}
export interface Readiness {
  status: "ready" | "not_ready";
  timestamp: string;
  service: string;
  checks: Partial<Record<ServiceKey, ServiceCheck>> & {
    database: ServiceCheck;
    redis: ServiceCheck;
  };
}
const ERRORS = new Set([
  "DATABASE_CONNECTION_FAILED",
  "DATABASE_TIMEOUT",
  "DATABASE_CLEANUP_TIMEOUT",
  "DATABASE_CLEANUP_FAILED",
  "REDIS_UNAVAILABLE",
  "REDIS_PING_FAILED",
  "REDIS_TIMEOUT",
  "REDIS_CONNECTION_FAILED",
]);
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
export function parseReadiness(value: unknown): Readiness | null {
  if (
    !object(value) ||
    !object(value.checks) ||
    typeof value.status !== "string" ||
    !["ready", "not_ready"].includes(value.status)
  )
    return null;
  if (
    typeof value.timestamp !== "string" ||
    value.timestamp.length > 40 ||
    !/^\d{4}-\d{2}-\d{2}T[\d:.+Z-]+$/.test(value.timestamp) ||
    !Number.isFinite(Date.parse(value.timestamp))
  )
    return null;
  if (typeof value.service !== "string" || !/^[A-Za-z0-9 ._-]{1,80}$/.test(value.service))
    return null;
  const checks: Partial<Record<ServiceKey, ServiceCheck>> = {};
  for (const key of SERVICE_KEYS) {
    const raw = value.checks[key];
    if (raw === undefined && key !== "database" && key !== "redis") continue;
    if (!object(raw)) return null;
    const critical = key === "database" || key === "redis";
    const statuses = critical
      ? ["healthy", "unhealthy"]
      : ["configured", "not_configured", "unknown"];
    if (typeof raw.status !== "string" || !statuses.includes(raw.status)) return null;
    const check: ServiceCheck = { status: raw.status as CheckStatus };
    if (
      typeof raw.latency_ms === "number" &&
      Number.isFinite(raw.latency_ms) &&
      raw.latency_ms >= 0 &&
      raw.latency_ms <= 60_000
    )
      check.latency_ms = raw.latency_ms;
    if (typeof raw.error === "string")
      check.error = ERRORS.has(raw.error) ? raw.error : "DEPENDENCY_CHECK_FAILED";
    if (key === "database") check.type = "postgresql";
    if (!critical) check.connectivity_checked = false;
    if (key === "knowledge_agent" && typeof raw.enabled === "boolean") check.enabled = raw.enabled;
    checks[key] = check;
  }
  if (!checks.database || !checks.redis) return null;
  const ready = checks.database.status === "healthy" && checks.redis.status === "healthy";
  if (ready !== (value.status === "ready")) return null;
  return {
    status: value.status as Readiness["status"],
    timestamp: value.timestamp,
    service: value.service,
    checks: checks as Readiness["checks"],
  };
}

import { NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";
import { parseReadiness } from "@/lib/health";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store" };
export async function GET() {
  try {
    const value = await backendFetch<unknown>("/api/v1/health/ready", {
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(6000),
    });
    const data = parseReadiness(value);
    if (!data || data.status !== "ready")
      return NextResponse.json({ detail: "Invalid readiness response" }, { status: 502, headers });
    return NextResponse.json({ ...data, ...data.checks }, { headers });
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 503) {
      const data = parseReadiness(error.data);
      if (data?.status === "not_ready")
        return NextResponse.json({ ...data, ...data.checks }, { status: 503, headers });
      return NextResponse.json({ detail: "Invalid readiness response" }, { status: 502, headers });
    }
    return NextResponse.json({ detail: "Readiness service unavailable" }, { status: 503, headers });
  }
}

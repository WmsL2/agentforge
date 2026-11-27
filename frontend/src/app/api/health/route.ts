import { NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";
import type { HealthResponse } from "@/types";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store" };
export async function GET() {
  try {
    const data = await backendFetch<HealthResponse & { max_upload_size_mb?: number }>(
      "/api/v1/health",
      { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(3000) },
    );
    if (!data || data.status !== "healthy")
      return NextResponse.json({ detail: "Invalid health response" }, { status: 502, headers });
    return NextResponse.json(
      {
        status: data.status,
        ...(typeof data.max_upload_size_mb === "number"
          ? { max_upload_size_mb: data.max_upload_size_mb }
          : {}),
      },
      { headers },
    );
  } catch (error) {
    if (error instanceof BackendApiError)
      return NextResponse.json(
        { detail: "Backend service unavailable" },
        { status: error.status >= 400 && error.status <= 599 ? error.status : 502, headers },
      );
    return NextResponse.json({ detail: "Internal server error" }, { status: 500, headers });
  }
}

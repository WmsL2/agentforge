import { NextRequest } from "next/server";

import { proxyPlatformApi } from "@/lib/platform-api-proxy";

const QUERY = ["workspace_id", "skip", "limit"] as const;

export function GET(request: NextRequest) {
  return proxyPlatformApi(request, { path: "/api/v1/workflows", query: QUERY });
}

export function POST(request: NextRequest) {
  return proxyPlatformApi(request, {
    path: "/api/v1/workflows",
    method: "POST",
    query: ["workspace_id"],
    successStatus: 201,
  });
}

import { NextRequest } from "next/server";

import { proxyPlatformApi } from "@/lib/platform-api-proxy";

export function GET(request: NextRequest) {
  return proxyPlatformApi(request, { path: "/api/v1/workspaces" });
}

export function POST(request: NextRequest) {
  return proxyPlatformApi(request, {
    path: "/api/v1/workspaces",
    method: "POST",
    successStatus: 201,
  });
}

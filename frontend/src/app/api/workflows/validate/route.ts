import { NextRequest } from "next/server";

import { proxyPlatformApi } from "@/lib/platform-api-proxy";

export function POST(request: NextRequest) {
  return proxyPlatformApi(request, { path: "/api/v1/workflows/validate", method: "POST" });
}

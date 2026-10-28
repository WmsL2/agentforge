import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workflowId: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { workflowId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workflows/${encodePathSegment(workflowId)}/runs`,
    query: ["skip", "limit"],
  });
}

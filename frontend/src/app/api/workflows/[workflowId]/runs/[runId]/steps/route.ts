import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workflowId: string; runId: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { workflowId, runId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workflows/${encodePathSegment(workflowId)}/runs/${encodePathSegment(runId)}/steps`,
  });
}

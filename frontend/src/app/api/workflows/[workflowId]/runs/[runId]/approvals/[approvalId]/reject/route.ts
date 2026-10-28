import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workflowId: string; runId: string; approvalId: string }>;
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { workflowId, runId, approvalId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workflows/${encodePathSegment(workflowId)}/runs/${encodePathSegment(runId)}/approvals/${encodePathSegment(approvalId)}/reject`,
    method: "POST",
  });
}

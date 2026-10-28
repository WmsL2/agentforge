import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workflowId: string; runId: string; approvalId: string }>;
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { workflowId, runId, approvalId } = await params;
  const workflow = encodePathSegment(workflowId);
  const run = encodePathSegment(runId);
  return proxyPlatformApi(request, {
    path: `/api/v1/workflows/${workflow}/runs/${run}/approvals/${encodePathSegment(approvalId)}/approve/async`,
    method: "POST",
    successStatus: 202,
    location: () => `/api/workflows/${workflow}/runs/${run}`,
  });
}

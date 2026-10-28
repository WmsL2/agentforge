import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workflowId: string }>;
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { workflowId } = await params;
  const encodedWorkflowId = encodePathSegment(workflowId);
  return proxyPlatformApi(request, {
    path: `/api/v1/workflows/${encodedWorkflowId}/runs/async`,
    method: "POST",
    successStatus: 202,
    location: (data) => {
      if (
        data === null ||
        typeof data !== "object" ||
        typeof (data as { id?: unknown }).id !== "string"
      ) {
        return undefined;
      }
      return `/api/workflows/${encodedWorkflowId}/runs/${encodePathSegment((data as { id: string }).id)}`;
    },
  });
}

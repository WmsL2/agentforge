import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workspaceId: string; userId: string }>;
}

async function path(params: RouteParams["params"]) {
  const { workspaceId, userId } = await params;
  return `/api/v1/workspaces/${encodePathSegment(workspaceId)}/members/${encodePathSegment(userId)}`;
}

export async function PATCH(request: NextRequest, { params }: RouteParams) {
  return proxyPlatformApi(request, { path: await path(params), method: "PATCH" });
}

export async function DELETE(request: NextRequest, { params }: RouteParams) {
  return proxyPlatformApi(request, {
    path: await path(params),
    method: "DELETE",
    successStatus: 204,
  });
}

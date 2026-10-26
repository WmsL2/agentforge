import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workspaceId: string }>;
}

async function path(params: RouteParams["params"]) {
  return `/api/v1/workspaces/${encodePathSegment((await params).workspaceId)}`;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  return proxyPlatformApi(request, { path: await path(params) });
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

import { NextRequest } from "next/server";

import { encodePathSegment, proxyPlatformApi } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workspaceId: string }>;
}

async function path(params: RouteParams["params"]) {
  return `/api/v1/workspaces/${encodePathSegment((await params).workspaceId)}/members`;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  return proxyPlatformApi(request, { path: await path(params) });
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  return proxyPlatformApi(request, {
    path: await path(params),
    method: "POST",
    successStatus: 201,
  });
}

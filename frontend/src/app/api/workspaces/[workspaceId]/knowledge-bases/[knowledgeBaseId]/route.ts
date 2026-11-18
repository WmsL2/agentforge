import { NextRequest } from "next/server";
import { proxyPlatformApi, encodePathSegment } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workspaceId: string; knowledgeBaseId: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { workspaceId, knowledgeBaseId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workspaces/${encodePathSegment(workspaceId)}/knowledge-bases/${encodePathSegment(knowledgeBaseId)}`,
    method: "GET",
    successStatus: 200,
    knowledge: true,
  });
}

export async function PATCH(request: NextRequest, { params }: RouteParams) {
  const { workspaceId, knowledgeBaseId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workspaces/${encodePathSegment(workspaceId)}/knowledge-bases/${encodePathSegment(knowledgeBaseId)}`,
    method: "PATCH",
    successStatus: 200,
    knowledge: true,
  });
}

export async function DELETE(request: NextRequest, { params }: RouteParams) {
  const { workspaceId, knowledgeBaseId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workspaces/${encodePathSegment(workspaceId)}/knowledge-bases/${encodePathSegment(knowledgeBaseId)}`,
    method: "DELETE",
    successStatus: 204,
    knowledge: true,
  });
}

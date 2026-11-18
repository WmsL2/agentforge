import { NextRequest } from "next/server";
import { proxyPlatformApi, encodePathSegment } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workspaceId: string; knowledgeBaseId: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { workspaceId, knowledgeBaseId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workspaces/${encodePathSegment(workspaceId)}/knowledge-bases/${encodePathSegment(knowledgeBaseId)}/documents`,
    method: "GET",
    successStatus: 200,
    knowledge: true,
    query: ["skip", "limit"],
  });
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { workspaceId, knowledgeBaseId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workspaces/${encodePathSegment(workspaceId)}/knowledge-bases/${encodePathSegment(knowledgeBaseId)}/documents`,
    method: "POST",
    successStatus: 201,
    knowledge: true,
    multipart: true,
  });
}

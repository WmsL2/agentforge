import { NextRequest } from "next/server";
import { proxyPlatformApi, encodePathSegment } from "@/lib/platform-api-proxy";

interface RouteParams {
  params: Promise<{ workspaceId: string; knowledgeBaseId: string; documentId: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { workspaceId, knowledgeBaseId, documentId } = await params;
  return proxyPlatformApi(request, {
    path: `/api/v1/workspaces/${encodePathSegment(workspaceId)}/knowledge-bases/${encodePathSegment(knowledgeBaseId)}/documents/${encodePathSegment(documentId)}/content`,
    method: "GET",
    successStatus: 200,
    knowledge: true,
  });
}

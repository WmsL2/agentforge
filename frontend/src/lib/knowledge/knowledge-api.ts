import { apiClient, ApiError, type RequestOptions } from "@/lib/api-client";
import { authIdentity } from "@/lib/auth-identity";
import { confirmedKnowledgeWorkspaceLoss, knowledgeRequest } from "./knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import type * as K from "@/types/knowledge";

export interface KnowledgeOptions {
  signal?: AbortSignal;
  userId?: string;
}
export interface KnowledgePagination {
  skip?: number;
  limit?: number;
}
const base = (workspaceId: string, knowledgeBaseId?: string) =>
  `/workspaces/${encodeURIComponent(workspaceId)}/knowledge-bases${knowledgeBaseId === undefined ? "" : `/${encodeURIComponent(knowledgeBaseId)}`}`;
const document = (workspaceId: string, knowledgeBaseId: string, documentId: string) =>
  `${base(workspaceId, knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}`;
const page = (pagination: KnowledgePagination) =>
  Object.fromEntries(
    Object.entries({ skip: pagination.skip, limit: pagination.limit })
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  );
function request<T>(
  workspaceId: string,
  knowledgeBaseId: string | undefined,
  documentId: string | undefined,
  options: KnowledgeOptions | undefined,
  run: (options: RequestOptions) => Promise<T>,
) {
  const userId = options?.userId ?? authIdentity().userId ?? "";
  const key =
    documentId !== undefined
      ? qk.knowledge.document(userId, workspaceId, knowledgeBaseId!, documentId)
      : knowledgeBaseId !== undefined
        ? qk.knowledge.base(userId, workspaceId, knowledgeBaseId)
        : qk.knowledge.workspace(userId, workspaceId);
  return knowledgeRequest(key, options?.signal, async (signal, identityGuard) => {
    const opts: RequestOptions = { signal, identityGuard, cache: "no-store" };
    try {
      return await run(opts);
    } catch (error) {
      // A resource 404/403 alone proves nothing about workspace membership.
      if (
        error instanceof ApiError &&
        (error.status === 403 || error.status === 404) &&
        identityGuard()
      ) {
        try {
          await apiClient.get(`/workspaces/${encodeURIComponent(workspaceId)}`, opts);
        } catch (membershipError) {
          if (
            identityGuard() &&
            membershipError instanceof ApiError &&
            (membershipError.status === 403 || membershipError.status === 404)
          )
            confirmedKnowledgeWorkspaceLoss(userId, workspaceId);
        }
      }
      throw error;
    }
  });
}
export const knowledgeApi = {
  listKnowledgeBases: (
    workspaceId: string,
    pagination: KnowledgePagination = {},
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, undefined, undefined, options, (opts) =>
      apiClient.get<K.KnowledgeBaseList>(base(workspaceId), {
        ...opts,
        params: Object.keys(page(pagination)).length ? page(pagination) : undefined,
      }),
    ),
  createKnowledgeBase: (
    workspaceId: string,
    payload: K.KnowledgeBaseCreate,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, undefined, undefined, options, (opts) =>
      apiClient.post<K.KnowledgeBaseRead>(
        base(workspaceId),
        {
          name: payload.name,
          ...(payload.description !== undefined ? { description: payload.description } : {}),
        },
        opts,
      ),
    ),
  getKnowledgeBase: (workspaceId: string, knowledgeBaseId: string, options?: KnowledgeOptions) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) =>
      apiClient.get<K.KnowledgeBaseRead>(base(workspaceId, knowledgeBaseId), opts),
    ),
  updateKnowledgeBase: (
    workspaceId: string,
    knowledgeBaseId: string,
    payload: K.KnowledgeBaseUpdate,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) =>
      apiClient.patch<K.KnowledgeBaseRead>(
        base(workspaceId, knowledgeBaseId),
        {
          ...(payload.name !== undefined ? { name: payload.name } : {}),
          ...(payload.description !== undefined ? { description: payload.description } : {}),
        },
        opts,
      ),
    ),
  deleteKnowledgeBase: (workspaceId: string, knowledgeBaseId: string, options?: KnowledgeOptions) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) =>
      apiClient.delete<null>(base(workspaceId, knowledgeBaseId), opts),
    ),
  listDocuments: (
    workspaceId: string,
    knowledgeBaseId: string,
    pagination: KnowledgePagination = {},
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) =>
      apiClient.get<K.KnowledgeDocumentList>(`${base(workspaceId, knowledgeBaseId)}/documents`, {
        ...opts,
        params: Object.keys(page(pagination)).length ? page(pagination) : undefined,
      }),
    ),
  uploadDocument: (
    workspaceId: string,
    knowledgeBaseId: string,
    file: File,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) => {
      const form = new FormData();
      form.append("file", file, file.name);
      return apiClient.post<K.KnowledgeDocumentRead>(
        `${base(workspaceId, knowledgeBaseId)}/documents`,
        form,
        opts,
      );
    }),
  getDocument: (
    workspaceId: string,
    knowledgeBaseId: string,
    documentId: string,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, documentId, options, (opts) =>
      apiClient.get<K.KnowledgeDocumentRead>(
        document(workspaceId, knowledgeBaseId, documentId),
        opts,
      ),
    ),
  getDocumentContent: (
    workspaceId: string,
    knowledgeBaseId: string,
    documentId: string,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, documentId, options, (opts) =>
      apiClient.get<K.KnowledgeDocumentContent>(
        `${document(workspaceId, knowledgeBaseId, documentId)}/content`,
        opts,
      ),
    ),
  downloadDocument: (
    workspaceId: string,
    knowledgeBaseId: string,
    documentId: string,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, documentId, options, (opts) =>
      apiClient.download(`${document(workspaceId, knowledgeBaseId, documentId)}/download`, opts),
    ),
  deleteDocument: (
    workspaceId: string,
    knowledgeBaseId: string,
    documentId: string,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, documentId, options, (opts) =>
      apiClient.delete<null>(document(workspaceId, knowledgeBaseId, documentId), opts),
    ),
  requestIndex: (
    workspaceId: string,
    knowledgeBaseId: string,
    documentId: string,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, documentId, options, (opts) =>
      apiClient.post<K.KnowledgeIndexJobRead>(
        `${document(workspaceId, knowledgeBaseId, documentId)}/index`,
        undefined,
        opts,
      ),
    ),
  getIndexStatus: (
    workspaceId: string,
    knowledgeBaseId: string,
    documentId: string,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, documentId, options, (opts) =>
      apiClient.get<K.KnowledgeIndexStatusRead>(
        `${document(workspaceId, knowledgeBaseId, documentId)}/index`,
        opts,
      ),
    ),
  search: (
    workspaceId: string,
    knowledgeBaseId: string,
    payload: K.KnowledgeSearchRequest,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) =>
      apiClient.post<K.KnowledgeSearchResponse>(
        `${base(workspaceId, knowledgeBaseId)}/search`,
        {
          query: payload.query,
          ...(payload.top_k !== undefined ? { top_k: payload.top_k } : {}),
          ...(payload.min_score !== undefined ? { min_score: payload.min_score } : {}),
        },
        opts,
      ),
    ),
  ask: (
    workspaceId: string,
    knowledgeBaseId: string,
    payload: K.KnowledgeAskRequest,
    options?: KnowledgeOptions,
  ) =>
    request(workspaceId, knowledgeBaseId, undefined, options, (opts) =>
      apiClient.post<K.KnowledgeAskResponse>(
        `${base(workspaceId, knowledgeBaseId)}/ask`,
        { question: payload.question },
        opts,
      ),
    ),
};

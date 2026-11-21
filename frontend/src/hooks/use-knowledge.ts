"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { aborted, authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { knowledgeApi, type KnowledgePagination } from "@/lib/knowledge/knowledge-api";
import { clearKnowledgeScope, onKnowledgeClear, within } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import type * as K from "@/types/knowledge";

function useIdentity(userId?: string) {
  const actual = useAuthStore((s) => (s.isAuthenticated ? s.user?.id : undefined));
  return Boolean(userId && actual === userId);
}
const readPolicy = {
  staleTime: 0,
  gcTime: 0,
  retry: false,
  refetchOnMount: "always" as const,
  refetchOnReconnect: "always" as const,
  refetchOnWindowFocus: true,
};
export function useKnowledgeBases(
  userId?: string,
  workspaceId?: string,
  pagination: KnowledgePagination = {},
) {
  const identity = useIdentity(userId);
  return useQuery({
    ...readPolicy,
    queryKey: qk.knowledge.list(userId ?? "", workspaceId ?? "", pagination.skip, pagination.limit),
    enabled: identity && Boolean(workspaceId),
    queryFn: ({ signal }) => {
      if (!identity || !workspaceId) aborted();
      return knowledgeApi.listKnowledgeBases(workspaceId!, pagination, { signal, userId: userId });
    },
  });
}
export function useKnowledgeBase(userId?: string, workspaceId?: string, knowledgeBaseId?: string) {
  const identity = useIdentity(userId);
  return useQuery({
    ...readPolicy,
    queryKey: qk.knowledge.base(userId ?? "", workspaceId ?? "", knowledgeBaseId ?? ""),
    enabled: identity && Boolean(workspaceId && knowledgeBaseId),
    queryFn: ({ signal }) => {
      if (!identity || !workspaceId || !knowledgeBaseId) aborted();
      return knowledgeApi.getKnowledgeBase(workspaceId!, knowledgeBaseId!, {
        signal,
        userId: userId,
      });
    },
  });
}
export function useKnowledgeDocuments(
  userId?: string,
  workspaceId?: string,
  knowledgeBaseId?: string,
  pagination: KnowledgePagination = {},
) {
  const identity = useIdentity(userId);
  return useQuery({
    ...readPolicy,
    queryKey: qk.knowledge.documents(
      userId ?? "",
      workspaceId ?? "",
      knowledgeBaseId ?? "",
      pagination.skip,
      pagination.limit,
    ),
    enabled: identity && Boolean(workspaceId && knowledgeBaseId),
    queryFn: ({ signal }) => {
      if (!identity || !workspaceId || !knowledgeBaseId) aborted();
      return knowledgeApi.listDocuments(workspaceId!, knowledgeBaseId!, pagination, {
        signal,
        userId: userId,
      });
    },
  });
}
export function useKnowledgeDocument(
  userId?: string,
  workspaceId?: string,
  knowledgeBaseId?: string,
  documentId?: string,
) {
  const identity = useIdentity(userId);
  return useQuery({
    ...readPolicy,
    queryKey: qk.knowledge.document(
      userId ?? "",
      workspaceId ?? "",
      knowledgeBaseId ?? "",
      documentId ?? "",
    ),
    enabled: identity && Boolean(workspaceId && knowledgeBaseId && documentId),
    queryFn: ({ signal }) => {
      if (!identity || !workspaceId || !knowledgeBaseId || !documentId) aborted();
      return knowledgeApi.getDocument(workspaceId!, knowledgeBaseId!, documentId!, {
        signal,
        userId: userId,
      });
    },
  });
}
export function useKnowledgeDocumentContent(
  userId?: string,
  workspaceId?: string,
  knowledgeBaseId?: string,
  documentId?: string,
  enabled = false,
) {
  const identity = useIdentity(userId);
  return useQuery({
    ...readPolicy,
    queryKey: qk.knowledge.content(
      userId ?? "",
      workspaceId ?? "",
      knowledgeBaseId ?? "",
      documentId ?? "",
    ),
    enabled: enabled && identity && Boolean(workspaceId && knowledgeBaseId && documentId),
    queryFn: ({ signal }) => {
      if (!identity || !workspaceId || !knowledgeBaseId || !documentId) aborted();
      return knowledgeApi.getDocumentContent(workspaceId!, knowledgeBaseId!, documentId!, {
        signal,
        userId: userId,
      });
    },
  });
}
export function useKnowledgeIndexStatus(
  userId?: string,
  workspaceId?: string,
  knowledgeBaseId?: string,
  documentId?: string,
  options: {
    pollActive?: boolean;
    awaitJob?: { id: string; until: number };
    isCurrent?: () => boolean;
  } = {},
) {
  const identity = useIdentity(userId);
  const pollingIdentity = authIdentity();
  return useQuery<K.KnowledgeIndexStatusRead>({
    ...readPolicy,
    ...(options.pollActive ? { refetchOnWindowFocus: false, refetchOnReconnect: false } : {}),
    refetchIntervalInBackground: false,
    refetchInterval: options.pollActive
      ? (query) => {
          const data = query.state.data;
          if (
            !identity ||
            !sameAuthIdentity(pollingIdentity) ||
            options.isCurrent?.() === false ||
            pollingIdentity.userId !== userId ||
            query.state.status !== "success" ||
            !data ||
            data.document_id !== documentId ||
            !["not_indexed", "pending", "running", "succeeded", "failed"].includes(data.status)
          )
            return false;
          if (options.awaitJob && data.job_id !== options.awaitJob.id)
            return Date.now() < options.awaitJob.until ? 3000 : false;
          return data.status === "pending" || data.status === "running" ? 3000 : false;
        }
      : false,
    queryKey: qk.knowledge.index(
      userId ?? "",
      workspaceId ?? "",
      knowledgeBaseId ?? "",
      documentId ?? "",
    ),
    enabled: identity && Boolean(workspaceId && knowledgeBaseId && documentId),
    queryFn: ({ signal }) => {
      if (
        !identity ||
        !workspaceId ||
        !knowledgeBaseId ||
        !documentId ||
        (options.pollActive && !sameAuthIdentity(pollingIdentity)) ||
        options.isCurrent?.() === false
      )
        aborted();
      return knowledgeApi.getIndexStatus(workspaceId!, knowledgeBaseId!, documentId!, {
        signal,
        userId: userId,
      });
    },
  });
}

/** Invocation captures scope and callback. Render masks old results before effects run. */
function useOperation<I, T>(
  key: QueryKey,
  enabled: boolean,
  run: (input: I, signal: AbortSignal) => Promise<T>,
  success?: (data: T, input: I) => void,
  resourceKey?: (input: I) => QueryKey,
  latest = false,
  completedKey?: (data: T, input: I) => QueryKey,
) {
  const stamp = JSON.stringify(key);
  const current = useRef(stamp);
  current.current = stamp;
  const active = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const inFlight = useRef<Promise<T> | null>(null);
  const inFlightInput = useRef<I | undefined>(undefined);
  const resultKey = useRef(key);
  const [visible, setVisible] = useState<{ stamp: string; sequence: number } | null>(null);
  const mutation = useMutation({
    mutationKey: key,
    gcTime: 0,
    retry: false,
    mutationFn: async (v: {
      resourceKey: QueryKey;
      input: I;
      stamp: string;
      sequence: number;
      controller: AbortController;
      identity: ReturnType<typeof authIdentity>;
      run: typeof run;
      success: typeof success;
      completedKey: typeof completedKey;
    }) => {
      const valid = () =>
        !v.controller.signal.aborted &&
        sameAuthIdentity(v.identity) &&
        current.current === v.stamp &&
        sequence.current === v.sequence;
      if (!valid()) aborted();
      const data = await v.run(v.input, v.controller.signal);
      if (!valid()) aborted();
      if (v.completedKey) {
        v.resourceKey = v.completedKey(data, v.input);
        resultKey.current = v.resourceKey;
      }
      v.success?.(data, v.input);
      return data;
    },
  });
  const { reset } = mutation;
  useEffect(
    () => () => {
      active.current?.abort();
      sequence.current++;
      reset();
    },
    [stamp, reset],
  );
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        if (within(resultKey.current, prefix) || within(JSON.parse(stamp) as QueryKey, prefix)) {
          active.current?.abort();
          sequence.current++;
          setVisible(null);
          reset();
        }
      }),
    [stamp, reset],
  );
  const mutateAsync = (input: I) => {
    if (!enabled) return Promise.reject(new DOMException("Request cancelled", "AbortError"));
    if (!latest && inFlight.current && !active.current?.signal.aborted) {
      const previous = inFlightInput.current;
      const sameInput =
        Object.is(previous, input) ||
        (!(previous instanceof Blob) &&
          !(input instanceof Blob) &&
          JSON.stringify(previous) === JSON.stringify(input));
      if (sameInput) return inFlight.current;
      return Promise.reject(
        new DOMException("Another operation is in progress", "InvalidStateError"),
      );
    }
    active.current?.abort();
    resultKey.current = resourceKey?.(input) ?? key;
    const controller = new AbortController();
    active.current = controller;
    const seq = ++sequence.current;
    setVisible({ stamp, sequence: seq });
    const promise = mutation.mutateAsync({
      resourceKey: resultKey.current,
      input,
      stamp,
      sequence: seq,
      controller,
      identity: authIdentity(),
      run,
      success,
      completedKey,
    });
    inFlight.current = promise;
    inFlightInput.current = input;
    void promise
      .finally(() => {
        if (inFlight.current === promise) inFlight.current = null;
      })
      .catch(() => {});
    return promise;
  };
  const matches =
    enabled &&
    visible?.stamp === stamp &&
    visible?.sequence === sequence.current &&
    mutation.variables?.sequence === visible?.sequence &&
    mutation.variables?.stamp === stamp;
  const cancel = () => {
    active.current?.abort();
    sequence.current++;
    setVisible(null);
    reset();
  };
  return {
    data: matches ? mutation.data : undefined,
    error: matches ? mutation.error : null,
    isPending: matches && mutation.isPending,
    isSuccess: matches && mutation.isSuccess,
    isError: matches && mutation.isError,
    status: matches ? mutation.status : ("idle" as const),
    mutateAsync,
    mutate: (input: I) => {
      void mutateAsync(input).catch(() => {});
    },
    cancel,
    reset: cancel,
  };
}
export function useKnowledgeBaseMutations(userId: string, workspaceId: string) {
  const client = useQueryClient();
  const valid = useIdentity(userId) && Boolean(workspaceId);
  const key = qk.knowledge.workspace(userId, workspaceId);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: qk.knowledge.lists(userId, workspaceId) });
  };
  const create = useOperation(
    key,
    valid,
    (payload: K.KnowledgeBaseCreate, signal) =>
      knowledgeApi.createKnowledgeBase(workspaceId, payload, { signal, userId: userId }),
    refresh,
    undefined,
    false,
    (data) => (data.id ? qk.knowledge.base(userId, workspaceId, data.id) : key),
  );
  const update = useOperation(
    key,
    valid,
    (
      { knowledgeBaseId, payload }: { knowledgeBaseId: string; payload: K.KnowledgeBaseUpdate },
      signal,
    ) =>
      knowledgeApi.updateKnowledgeBase(workspaceId, knowledgeBaseId, payload, {
        signal,
        userId: userId,
      }),
    (_data, input) => {
      refresh();
      void client.invalidateQueries({
        queryKey: qk.knowledge.base(userId, workspaceId, input.knowledgeBaseId),
        exact: true,
      });
    },
    (input) => qk.knowledge.base(userId, workspaceId, input.knowledgeBaseId),
  );
  const remove = useOperation(
    key,
    valid,
    (knowledgeBaseId: string, signal) =>
      knowledgeApi.deleteKnowledgeBase(workspaceId, knowledgeBaseId, { signal, userId: userId }),
    (_data, knowledgeBaseId) => {
      clearKnowledgeScope(client, qk.knowledge.base(userId, workspaceId, knowledgeBaseId));
      refresh();
    },
  );
  return { create, update, remove };
}
export function useKnowledgeDocumentMutations(
  userId: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  const client = useQueryClient();
  const valid = useIdentity(userId) && Boolean(workspaceId && knowledgeBaseId);
  const key = qk.knowledge.base(userId, workspaceId, knowledgeBaseId);
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: qk.knowledge.documentLists(userId, workspaceId, knowledgeBaseId),
    });
  };
  const upload = useOperation(
    key,
    valid,
    (file: File, signal) =>
      knowledgeApi.uploadDocument(workspaceId, knowledgeBaseId, file, { signal, userId: userId }),
    refresh,
    undefined,
    false,
    (data) =>
      data.id ? qk.knowledge.document(userId, workspaceId, knowledgeBaseId, data.id) : key,
  );
  const remove = useOperation(
    key,
    valid,
    (documentId: string, signal) =>
      knowledgeApi.deleteDocument(workspaceId, knowledgeBaseId, documentId, {
        signal,
        userId: userId,
      }),
    (_data, documentId) => {
      clearKnowledgeScope(
        client,
        qk.knowledge.document(userId, workspaceId, knowledgeBaseId, documentId),
      );
      refresh();
    },
  );
  const download = useOperation(
    key,
    valid,
    (documentId: string, signal) =>
      knowledgeApi.downloadDocument(workspaceId, knowledgeBaseId, documentId, {
        signal,
        userId: userId,
      }),
    undefined,
    (documentId) => qk.knowledge.document(userId, workspaceId, knowledgeBaseId, documentId),
    true,
  );
  return { upload, remove, download };
}
export function useKnowledgeIndexMutation(
  userId: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
) {
  const client = useQueryClient();
  const valid = useIdentity(userId) && Boolean(workspaceId && knowledgeBaseId && documentId);
  return useOperation(
    qk.knowledge.document(userId, workspaceId, knowledgeBaseId, documentId),
    valid,
    (_input: void, signal) =>
      knowledgeApi.requestIndex(workspaceId, knowledgeBaseId, documentId, {
        signal,
        userId: userId,
      }),
    () => {
      void client.invalidateQueries({
        queryKey: qk.knowledge.index(userId, workspaceId, knowledgeBaseId, documentId),
      });
    },
  );
}
export function useKnowledgeSearch(userId: string, workspaceId: string, knowledgeBaseId: string) {
  const valid = useIdentity(userId) && Boolean(workspaceId && knowledgeBaseId);
  return useOperation(
    qk.knowledge.base(userId, workspaceId, knowledgeBaseId),
    valid,
    (payload: K.KnowledgeSearchRequest, signal) =>
      knowledgeApi.search(workspaceId, knowledgeBaseId, payload, { signal, userId: userId }),
    undefined,
    undefined,
    true,
  );
}
export function useKnowledgeAsk(userId: string, workspaceId: string, knowledgeBaseId: string) {
  const valid = useIdentity(userId) && Boolean(workspaceId && knowledgeBaseId);
  return useOperation(
    qk.knowledge.base(userId, workspaceId, knowledgeBaseId),
    valid,
    (payload: K.KnowledgeAskRequest, signal) =>
      knowledgeApi.ask(workspaceId, knowledgeBaseId, payload, { signal, userId: userId }),
    undefined,
    undefined,
    true,
  );
}

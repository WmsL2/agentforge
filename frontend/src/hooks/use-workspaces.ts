"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { clearKnowledgeScope, within } from "@/lib/knowledge/knowledge-lifecycle";
import { aborted, authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { useAuthStore } from "@/stores/auth-store";
import { ApiError } from "@/lib/api-client";

import { qk } from "@/lib/query-keys";
import { workspaceApi } from "@/lib/workflow/workspace-api";
import type {
  WorkspaceCreate,
  WorkspaceMemberCreate,
  WorkspaceMemberUpdate,
  WorkspaceRead,
  WorkspaceUpdate,
} from "@/types";

/** Opt-in policy for Knowledge authorization. Workflow defaults remain unchanged. */
export interface WorkspaceQueryOptions {
  authorizationFresh?: boolean;
}
function useAuthorizationQuery(userId: string | undefined, options: WorkspaceQueryOptions) {
  useAuthStore((s) => s.user);
  const identity = authIdentity();
  return {
    identity,
    enabled: !options.authorizationFresh || Boolean(userId && identity.userId === userId),
    suffix: options.authorizationFresh
      ? ["knowledge-access", identity.generation, identity.transitionEpoch]
      : [],
    policy: options.authorizationFresh
      ? {
          staleTime: 0,
          gcTime: 0,
          retry: false as const,
          refetchOnMount: "always" as const,
          refetchOnWindowFocus: true,
          refetchOnReconnect: "always" as const,
        }
      : {},
  };
}
export function useWorkspaces(userId?: string, options: WorkspaceQueryOptions = {}) {
  const client = useQueryClient();
  const access = useAuthorizationQuery(userId, options);
  const key = [...qk.workspaces.list(userId ?? "anonymous"), ...access.suffix];
  return useQuery({
    ...access.policy,
    queryKey: key,
    queryFn: async ({ signal }) => {
      const valid = () =>
        !signal.aborted && sameAuthIdentity(access.identity) && access.identity.userId === userId;
      if (options.authorizationFresh && (!userId || !valid())) aborted();
      const items = (
        await workspaceApi.listWorkspaces(
          options.authorizationFresh
            ? { signal, identityGuard: valid, cache: "no-store" }
            : undefined,
        )
      ).items;
      if (options.authorizationFresh) {
        if (!valid()) aborted();
        const previous = client.getQueryData<WorkspaceRead[]>(key) ?? [];
        const prefix = qk.knowledge.user(userId!);
        const cachedScopes = client
          .getQueryCache()
          .findAll({ queryKey: prefix })
          .map((query) => query.queryKey[2]);
        const mutationScopes = client
          .getMutationCache()
          .getAll()
          .flatMap((mutation) => {
            const key = mutation.options.mutationKey ?? [];
            return within(key, prefix) ? [key[2]] : [];
          });
        const known = new Set(
          [...previous.map((workspace) => workspace.id), ...cachedScopes, ...mutationScopes].filter(
            (id): id is string => typeof id === "string",
          ),
        );
        for (const id of known)
          if (!items.some((item) => item.id === id))
            clearKnowledgeScope(client, qk.knowledge.workspace(userId!, id));
      }
      return items;
    },
    enabled: Boolean(userId) && access.enabled,
  });
}

export function useWorkspaceMembers(
  userId?: string,
  workspaceId?: string,
  options: WorkspaceQueryOptions = {},
) {
  const queryClient = useQueryClient();
  const access = useAuthorizationQuery(userId, options);
  return useQuery({
    ...access.policy,
    queryKey: [
      ...qk.workspaces.members(userId ?? "anonymous", workspaceId ?? "none"),
      ...access.suffix,
    ],
    queryFn: async ({ signal }) => {
      const identity = authIdentity();
      const valid = () =>
        !signal.aborted && sameAuthIdentity(identity) && identity.userId === userId;
      if (options.authorizationFresh && (!userId || !workspaceId || !valid())) aborted();
      try {
        const members = await workspaceApi.listMembers(
          workspaceId!,
          options.authorizationFresh
            ? { signal, identityGuard: valid, cache: "no-store" }
            : undefined,
        );
        if (options.authorizationFresh && !valid()) aborted();
        return members;
      } catch (error) {
        if (
          sameAuthIdentity(identity) &&
          identity.userId === userId &&
          error instanceof ApiError &&
          (error.status === 403 || error.status === 404)
        )
          clearKnowledgeScope(queryClient, qk.knowledge.workspace(userId!, workspaceId!));
        throw error;
      }
    },
    enabled: Boolean(userId && workspaceId) && access.enabled,
  });
}

export function useWorkspaceMutations(userId: string) {
  const queryClient = useQueryClient();
  const listKey = qk.workspaces.list(userId);

  const create = useMutation({
    mutationFn: (payload: WorkspaceCreate) => workspaceApi.createWorkspace(payload),
    onSuccess: (workspace) => {
      queryClient.setQueryData<WorkspaceRead[]>(listKey, (current = []) => [...current, workspace]);
    },
  });

  const update = useMutation({
    mutationFn: ({ workspaceId, payload }: { workspaceId: string; payload: WorkspaceUpdate }) =>
      workspaceApi.updateWorkspace(workspaceId, payload),
    onSuccess: (workspace) => {
      queryClient.setQueryData<WorkspaceRead[]>(listKey, (current = []) =>
        current.map((item) => (item.id === workspace.id ? workspace : item)),
      );
      queryClient.setQueryData(qk.workspaces.detail(userId, workspace.id), workspace);
    },
  });

  const remove = useMutation({
    mutationFn: (workspaceId: string) => workspaceApi.deleteWorkspace(workspaceId),
    onMutate: () => authIdentity(),
    onSuccess: (_data, workspaceId, identity) => {
      if (identity && sameAuthIdentity(identity) && identity.userId === userId) {
        clearKnowledgeScope(queryClient, qk.knowledge.workspace(userId, workspaceId));
      }
      queryClient.setQueryData<WorkspaceRead[]>(listKey, (current = []) =>
        current.filter((item) => item.id !== workspaceId),
      );
      queryClient.removeQueries({ queryKey: qk.workspaces.detail(userId, workspaceId) });
      queryClient.removeQueries({ queryKey: qk.workspaces.members(userId, workspaceId) });
      queryClient.removeQueries({ queryKey: qk.workflows.workspace(userId, workspaceId) });
    },
  });

  return { create, update, remove };
}

export function useMemberMutations(userId: string, workspaceId: string) {
  const queryClient = useQueryClient();
  const membersKey = qk.workspaces.members(userId, workspaceId);
  const refresh = () => queryClient.invalidateQueries({ queryKey: membersKey });

  const add = useMutation({
    mutationFn: (payload: WorkspaceMemberCreate) => workspaceApi.addMember(workspaceId, payload),
    onSuccess: refresh,
  });

  const update = useMutation({
    mutationFn: ({
      memberUserId,
      payload,
    }: {
      memberUserId: string;
      payload: WorkspaceMemberUpdate;
    }) => workspaceApi.updateMember(workspaceId, memberUserId, payload),
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: (memberUserId: string) => workspaceApi.removeMember(workspaceId, memberUserId),
    onSuccess: refresh,
  });

  return { add, update, remove };
}

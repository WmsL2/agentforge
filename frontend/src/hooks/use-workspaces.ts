"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import { authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
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

export function useWorkspaces(userId?: string) {
  return useQuery({
    queryKey: qk.workspaces.list(userId ?? "anonymous"),
    queryFn: async () => (await workspaceApi.listWorkspaces()).items,
    enabled: Boolean(userId),
  });
}

export function useWorkspaceMembers(userId?: string, workspaceId?: string) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: qk.workspaces.members(userId ?? "anonymous", workspaceId ?? "none"),
    queryFn: async () => {
      const identity = authIdentity();
      try {
        return await workspaceApi.listMembers(workspaceId!);
      } catch (error) {
        // Membership endpoint checks workspace access before returning members.
        if (
          sameAuthIdentity(identity) &&
          identity.userId === userId &&
          error instanceof ApiError &&
          (error.status === 403 || error.status === 404)
        ) {
          clearKnowledgeScope(queryClient, qk.knowledge.workspace(userId!, workspaceId!));
        }
        throw error;
      }
    },
    enabled: Boolean(userId && workspaceId),
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

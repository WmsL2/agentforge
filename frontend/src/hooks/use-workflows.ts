"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { workflowApi } from "@/lib/workflow/workflow-api";
import type { WorkflowCreate, WorkflowList, WorkflowRead, WorkflowUpdate } from "@/types";

export function useWorkflows(
  userId: string | undefined,
  workspaceId: string | undefined,
  skip: number,
  limit: number,
) {
  return useQuery({
    queryKey: qk.workflows.list(userId ?? "anonymous", workspaceId ?? "none", skip, limit),
    queryFn: () => workflowApi.listWorkflows(workspaceId!, { skip, limit }),
    enabled: Boolean(userId && workspaceId),
  });
}

export function useWorkflow(userId: string | undefined, workflowId: string | undefined) {
  return useQuery({
    queryKey: qk.workflows.detail(userId ?? "anonymous", workflowId ?? "none"),
    queryFn: () => workflowApi.getWorkflow(workflowId!),
    enabled: Boolean(userId && workflowId),
  });
}

export function useWorkflowMutations(
  userId: string,
  workspaceId: string,
  skip: number,
  limit: number,
) {
  const queryClient = useQueryClient();
  const listKey = qk.workflows.list(userId, workspaceId, skip, limit);

  const create = useMutation({
    mutationFn: (payload: WorkflowCreate) => workflowApi.createWorkflow(workspaceId, payload),
    onSuccess: (workflow) => {
      queryClient.setQueryData<WorkflowList>(listKey, (current) => ({
        items: current ? [workflow, ...current.items] : [workflow],
        total: (current?.total ?? 0) + 1,
      }));
      void queryClient.invalidateQueries({ queryKey: qk.workflows.workspace(userId, workspaceId) });
    },
  });

  const update = useMutation({
    mutationFn: ({ workflowId, payload }: { workflowId: string; payload: WorkflowUpdate }) =>
      workflowApi.updateWorkflow(workflowId, payload),
    onSuccess: (workflow) => {
      queryClient.setQueryData<WorkflowRead>(qk.workflows.detail(userId, workflow.id), workflow);
      queryClient.setQueriesData<WorkflowList>(
        { queryKey: qk.workflows.workspace(userId, workspaceId) },
        (current) =>
          current
            ? {
                ...current,
                items: current.items.map((item) => (item.id === workflow.id ? workflow : item)),
              }
            : current,
      );
    },
  });

  const remove = useMutation({
    mutationFn: (workflowId: string) => workflowApi.deleteWorkflow(workflowId),
    onSuccess: (_data, workflowId) => {
      queryClient.setQueriesData<WorkflowList>(
        { queryKey: qk.workflows.workspace(userId, workspaceId) },
        (current) =>
          current
            ? {
                items: current.items.filter((item) => item.id !== workflowId),
                total: Math.max(0, current.total - 1),
              }
            : current,
      );
      queryClient.removeQueries({ queryKey: qk.workflows.detail(userId, workflowId) });
    },
  });

  return { create, update, remove };
}

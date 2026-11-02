"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { workflowApi } from "@/lib/workflow/workflow-api";
import type {
  ApprovalDecisionRequest,
  ApprovalRequestRead,
  JsonObject,
  WorkflowRunRead,
  WorkflowRunStatus,
} from "@/types";

export const workflowRunRefetchInterval = (status: WorkflowRunStatus | undefined) => {
  if (status === "pending" || status === "running") return 3000;
  if (status === "paused") return 10000;
  return false;
};

export function useWorkflowRuns(userId: string, workflowId: string, skip: number, limit: number) {
  return useQuery({
    queryKey: qk.workflowRuns.list(userId, workflowId, skip, limit),
    queryFn: () => workflowApi.listWorkflowRuns(workflowId, { skip, limit }),
    enabled: Boolean(userId && workflowId),
    retry: 1,
  });
}

export function useWorkflowRun(userId: string, workflowId: string, runId?: string) {
  return useQuery({
    queryKey: qk.workflowRuns.detail(userId, workflowId, runId ?? "none"),
    queryFn: () => workflowApi.getWorkflowRun(workflowId, runId!),
    enabled: Boolean(userId && workflowId && runId),
    retry: 1,
    refetchInterval: (query) => workflowRunRefetchInterval(query.state.data?.status),
    refetchIntervalInBackground: false,
  });
}

export function useWorkflowRunSteps(
  userId: string,
  workflowId: string,
  runId: string | undefined,
  status: WorkflowRunStatus | undefined,
) {
  return useQuery({
    queryKey: qk.workflowRuns.steps(userId, workflowId, runId ?? "none"),
    queryFn: () => workflowApi.getWorkflowRunSteps(workflowId, runId!),
    enabled: Boolean(userId && workflowId && runId),
    retry: 1,
    refetchInterval: workflowRunRefetchInterval(status),
    refetchIntervalInBackground: false,
  });
}

export function useWorkflowTrace(
  userId: string,
  workflowId: string,
  runId: string | undefined,
  status: WorkflowRunStatus | undefined,
) {
  return useQuery({
    queryKey: qk.workflowRuns.trace(userId, workflowId, runId ?? "none"),
    queryFn: () => workflowApi.getWorkflowTrace(workflowId, runId!),
    enabled: Boolean(userId && workflowId && runId),
    retry: 1,
    refetchInterval: workflowRunRefetchInterval(status),
    refetchIntervalInBackground: false,
  });
}

export function usePendingWorkflowApproval(
  userId: string,
  workflowId: string,
  runId: string | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: qk.workflowRuns.approval(userId, workflowId, runId ?? "none"),
    queryFn: () => workflowApi.getPendingApproval(workflowId, runId!),
    enabled: Boolean(userId && workflowId && runId && enabled),
    retry: false,
  });
}

export function useWorkflowRunMutations(userId: string, workflowId: string) {
  const queryClient = useQueryClient();
  const workflowKey = qk.workflowRuns.workflow(userId, workflowId);

  const refreshRun = async (runId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: qk.workflowRuns.detail(userId, workflowId, runId),
      }),
      queryClient.invalidateQueries({ queryKey: qk.workflowRuns.steps(userId, workflowId, runId) }),
      queryClient.invalidateQueries({ queryKey: qk.workflowRuns.trace(userId, workflowId, runId) }),
      queryClient.invalidateQueries({
        queryKey: qk.workflowRuns.approval(userId, workflowId, runId),
      }),
      queryClient.invalidateQueries({ queryKey: workflowKey }),
    ]);
  };

  const submit = useMutation({
    mutationFn: (input: JsonObject) => workflowApi.submitAsyncRun(workflowId, input),
    onSuccess: (run) => {
      queryClient.setQueryData<WorkflowRunRead>(
        qk.workflowRuns.detail(userId, workflowId, run.id),
        run,
      );
      void queryClient.invalidateQueries({ queryKey: workflowKey });
    },
  });

  const approve = useMutation({
    mutationFn: ({
      runId,
      approvalId,
      payload,
    }: {
      runId: string;
      approvalId: string;
      payload: ApprovalDecisionRequest;
    }) => workflowApi.approveAsync(workflowId, runId, approvalId, payload),
  });

  const reject = useMutation({
    mutationFn: ({
      runId,
      approvalId,
      payload,
    }: {
      runId: string;
      approvalId: string;
      payload: ApprovalDecisionRequest;
    }) => workflowApi.rejectApproval(workflowId, runId, approvalId, payload),
  });

  const decide = async (
    kind: "approve" | "reject",
    runId: string,
    approvalId: string,
    note: string | null,
  ): Promise<ApprovalRequestRead> => {
    const mutation = kind === "approve" ? approve : reject;
    const result = await mutation.mutateAsync({
      runId,
      approvalId,
      payload: { note },
    });
    queryClient.setQueryData(qk.workflowRuns.approval(userId, workflowId, runId), result);
    await refreshRun(runId);
    return result;
  };

  return { submit, approve, reject, decide, refreshRun };
}

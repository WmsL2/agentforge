"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { useAuthStore } from "@/stores/auth-store";
import { authIdentity } from "@/lib/auth-identity";
import {
  workflowRunReadKey,
  workflowRunRequest,
  workflowRunDenialKey,
  workflowRunReadRetry,
} from "@/lib/workflow/workflow-run-lifecycle";

import { qk } from "@/lib/query-keys";
import { workflowApi } from "@/lib/workflow/workflow-api";
import type {
  ApprovalDecisionRequest,
  ApprovalRequestRead,
  JsonObject,
  WorkflowRunRead,
  WorkflowRunStatus,
} from "@/types";

// Cache-only state has the same session/resource lifetime as its associated read.
function useRunAuthorization(key: QueryKey) {
  const client = useQueryClient();
  const denied = useQuery({
    queryKey: workflowRunDenialKey(key),
    enabled: false,
    initialData: false,
  });
  return { denied: denied.data === true, scope: { client, key } };
}

export const workflowRunRefetchInterval = (status: WorkflowRunStatus | undefined) => {
  if (status === "pending" || status === "running") return 3000;
  if (status === "paused") return 10000;
  return false;
};

export function useWorkflowRuns(userId: string, workflowId: string, skip: number, limit: number) {
  useAuthStore();
  const identity = authIdentity();
  const key = workflowRunReadKey(qk.workflowRuns.list(userId, workflowId, skip, limit), identity);
  const authorization = useRunAuthorization(key);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      workflowRunRequest(
        userId,
        identity,
        signal,
        (signal, identityGuard) =>
          workflowApi.listWorkflowRuns(workflowId, { skip, limit }, { signal, identityGuard }),
        authorization.scope,
      ),
    enabled: Boolean(identity.userId === userId && userId && workflowId),
    retry: workflowRunReadRetry,
    // A selected execution read must revalidate even under the global five-minute cache.
    staleTime: 0,
    refetchOnMount: "always",
  });
  return { ...query, authorizationDenied: authorization.denied };
}

export function useWorkflowRun(userId: string, workflowId: string, runId?: string) {
  useAuthStore();
  const identity = authIdentity();
  const key = workflowRunReadKey(
    qk.workflowRuns.detail(userId, workflowId, runId ?? "none"),
    identity,
  );
  const authorization = useRunAuthorization(key);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      workflowRunRequest(
        userId,
        identity,
        signal,
        (signal, identityGuard) =>
          workflowApi.getWorkflowRun(workflowId, runId!, { signal, identityGuard }),
        authorization.scope,
      ),
    enabled: Boolean(identity.userId === userId && userId && workflowId && runId),
    retry: workflowRunReadRetry,
    // A selected execution read must revalidate even under the global five-minute cache.
    staleTime: 0,
    refetchOnMount: "always",
    refetchInterval: (query) => workflowRunRefetchInterval(query.state.data?.status),
    refetchIntervalInBackground: false,
  });
  return { ...query, authorizationDenied: authorization.denied };
}

export function useWorkflowRunSteps(
  userId: string,
  workflowId: string,
  runId: string | undefined,
  status: WorkflowRunStatus | undefined,
) {
  useAuthStore();
  const identity = authIdentity();
  const key = workflowRunReadKey(
    qk.workflowRuns.steps(userId, workflowId, runId ?? "none"),
    identity,
  );
  const authorization = useRunAuthorization(key);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      workflowRunRequest(
        userId,
        identity,
        signal,
        (signal, identityGuard) =>
          workflowApi.getWorkflowRunSteps(workflowId, runId!, { signal, identityGuard }),
        authorization.scope,
      ),
    enabled: Boolean(identity.userId === userId && userId && workflowId && runId),
    retry: workflowRunReadRetry,
    // A selected execution read must revalidate even under the global five-minute cache.
    staleTime: 0,
    refetchOnMount: "always",
    refetchInterval: workflowRunRefetchInterval(status),
    refetchIntervalInBackground: false,
  });
  return { ...query, authorizationDenied: authorization.denied };
}

export function useWorkflowTrace(
  userId: string,
  workflowId: string,
  runId: string | undefined,
  status: WorkflowRunStatus | undefined,
) {
  useAuthStore();
  const identity = authIdentity();
  const key = workflowRunReadKey(
    qk.workflowRuns.trace(userId, workflowId, runId ?? "none"),
    identity,
  );
  const authorization = useRunAuthorization(key);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      workflowRunRequest(
        userId,
        identity,
        signal,
        (signal, identityGuard) =>
          workflowApi.getWorkflowTrace(workflowId, runId!, { signal, identityGuard }),
        authorization.scope,
      ),
    enabled: Boolean(identity.userId === userId && userId && workflowId && runId),
    retry: workflowRunReadRetry,
    // A selected execution read must revalidate even under the global five-minute cache.
    staleTime: 0,
    refetchOnMount: "always",
    refetchInterval: workflowRunRefetchInterval(status),
    refetchIntervalInBackground: false,
  });
  return { ...query, authorizationDenied: authorization.denied };
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
  const identity = authIdentity();

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
        workflowRunReadKey(qk.workflowRuns.detail(userId, workflowId, run.id), identity),
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

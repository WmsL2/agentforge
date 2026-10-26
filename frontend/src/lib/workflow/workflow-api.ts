import { apiClient } from "@/lib/api-client";
import type {
  ApprovalDecisionRequest,
  ApprovalRequestRead,
  JsonObject,
  RunStepRead,
  TraceEventRead,
  WorkflowCreate,
  WorkflowGraph,
  WorkflowList,
  WorkflowRead,
  WorkflowRunList,
  WorkflowRunRead,
  WorkflowUpdate,
  WorkflowValidationRead,
} from "@/types";

interface Pagination {
  skip?: number;
  limit?: number;
}

const workflowPath = (workflowId: string) => `/workflows/${encodeURIComponent(workflowId)}`;
const runPath = (workflowId: string, runId: string) =>
  `${workflowPath(workflowId)}/runs/${encodeURIComponent(runId)}`;
const paginationParams = (pagination: Pagination = {}) => {
  const params: Record<string, string> = {};
  if (pagination.skip !== undefined) params.skip = String(pagination.skip);
  if (pagination.limit !== undefined) params.limit = String(pagination.limit);
  return params;
};

export const workflowApi = {
  listWorkflows: (workspaceId: string, pagination: Pagination = {}) =>
    apiClient.get<WorkflowList>("/workflows", {
      params: { workspace_id: workspaceId, ...paginationParams(pagination) },
    }),
  createWorkflow: (workspaceId: string, payload: WorkflowCreate) =>
    apiClient.post<WorkflowRead>("/workflows", payload, {
      params: { workspace_id: workspaceId },
    }),
  getWorkflow: (workflowId: string) => apiClient.get<WorkflowRead>(workflowPath(workflowId)),
  updateWorkflow: (workflowId: string, payload: WorkflowUpdate) =>
    apiClient.patch<WorkflowRead>(workflowPath(workflowId), payload),
  deleteWorkflow: (workflowId: string) => apiClient.delete<null>(workflowPath(workflowId)),
  validateWorkflow: (graph: WorkflowGraph) =>
    apiClient.post<WorkflowValidationRead>("/workflows/validate", graph),
  submitAsyncRun: (workflowId: string, input: JsonObject) =>
    apiClient.post<WorkflowRunRead>(`${workflowPath(workflowId)}/runs/async`, { input }),
  listWorkflowRuns: (workflowId: string, pagination: Pagination = {}) =>
    apiClient.get<WorkflowRunList>(`${workflowPath(workflowId)}/runs`, {
      params: paginationParams(pagination),
    }),
  getWorkflowRun: (workflowId: string, runId: string) =>
    apiClient.get<WorkflowRunRead>(runPath(workflowId, runId)),
  getWorkflowRunSteps: (workflowId: string, runId: string) =>
    apiClient.get<RunStepRead[]>(`${runPath(workflowId, runId)}/steps`),
  getWorkflowTrace: (workflowId: string, runId: string) =>
    apiClient.get<TraceEventRead[]>(`${runPath(workflowId, runId)}/trace`),
  getPendingApproval: (workflowId: string, runId: string) =>
    apiClient.get<ApprovalRequestRead>(`${runPath(workflowId, runId)}/approvals/pending`),
  approveAsync: (
    workflowId: string,
    runId: string,
    approvalId: string,
    payload: ApprovalDecisionRequest = {},
  ) =>
    apiClient.post<ApprovalRequestRead>(
      `${runPath(workflowId, runId)}/approvals/${encodeURIComponent(approvalId)}/approve/async`,
      payload,
    ),
  rejectApproval: (
    workflowId: string,
    runId: string,
    approvalId: string,
    payload: ApprovalDecisionRequest = {},
  ) =>
    apiClient.post<ApprovalRequestRead>(
      `${runPath(workflowId, runId)}/approvals/${encodeURIComponent(approvalId)}/reject`,
      payload,
    ),
};

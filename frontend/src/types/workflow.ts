export type JsonObject = Record<string, unknown>;

export type WorkflowNodeKind = "start" | "value" | "agent" | "approval" | "end";

export interface WorkflowNode {
  id: string;
  kind: WorkflowNodeKind;
  config: JsonObject;
  metadata: JsonObject;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition: JsonObject | null;
  metadata: JsonObject;
}

export interface WorkflowGraph {
  entry_node_id: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  schema_version: number;
  metadata: JsonObject;
}

export interface WorkflowCreate {
  name: string;
  description?: string | null;
  definition: WorkflowGraph;
}

export interface WorkflowUpdate {
  name?: string | null;
  description?: string | null;
  definition?: WorkflowGraph | null;
}

export interface WorkflowRead {
  id: string;
  user_id: string | null;
  workspace_id: string;
  name: string;
  description: string | null;
  definition: WorkflowGraph;
  revision: number;
  created_at: string;
  updated_at: string | null;
}

export interface WorkflowList {
  items: WorkflowRead[];
  total: number;
}

export type WorkflowValidationCode =
  | "empty_workflow"
  | "duplicate_node_id"
  | "duplicate_edge_id"
  | "duplicate_edge"
  | "missing_edge_source"
  | "missing_edge_target"
  | "self_loop"
  | "missing_start_node"
  | "multiple_start_nodes"
  | "missing_entry_node"
  | "invalid_entry_kind"
  | "entry_node_mismatch"
  | "start_has_incoming_edge"
  | "missing_end_node"
  | "end_has_outgoing_edge"
  | "isolated_node"
  | "unreachable_node"
  | "cycle_detected"
  | "invalid_terminal_node"
  | "no_terminal_path"
  | "unsupported_edge_condition"
  | "agent_runner_required"
  | "agent_runner_invalid"
  | "agent_instruction_required"
  | "agent_instruction_invalid"
  | "agent_model_invalid"
  | "agent_config_unknown_field"
  | "approval_prompt_required"
  | "approval_prompt_invalid"
  | "approval_config_unknown_field";

export interface WorkflowValidationIssue {
  code: WorkflowValidationCode;
  message: string;
  node_id: string | null;
  edge_id: string | null;
}

export interface WorkflowValidationRead {
  is_valid: boolean;
  issues: WorkflowValidationIssue[];
}

export interface WorkflowRunCreate {
  input: JsonObject;
}

export type WorkflowRunStatus =
  "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface WorkflowRunErrorRead {
  code: string;
  message: string;
  node_id: string | null;
}

export interface WorkflowRunRead {
  id: string;
  workflow_id: string;
  workflow_revision: number;
  definition_snapshot: WorkflowGraph;
  status: WorkflowRunStatus;
  input: JsonObject;
  node_outputs: JsonObject;
  output: JsonObject | null;
  error: WorkflowRunErrorRead | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export type WorkflowRunListItem = Pick<
  WorkflowRunRead,
  | "id"
  | "workflow_id"
  | "workflow_revision"
  | "status"
  | "error"
  | "started_at"
  | "finished_at"
  | "created_at"
  | "updated_at"
>;

export interface WorkflowRunList {
  items: WorkflowRunListItem[];
  total: number;
}

export type RunStepStatus = "running" | "completed" | "failed" | "interrupted";

export interface RunStepRead {
  id: string;
  run_id: string;
  sequence: number;
  node_id: string;
  node_kind: WorkflowNodeKind;
  status: RunStepStatus;
  input: JsonObject;
  output: unknown | null;
  error: { code: string; message: string } | null;
  metadata: JsonObject;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export type TraceEventKind =
  | "node_started"
  | "node_completed"
  | "node_failed"
  | "node_interrupted"
  | "approval_requested"
  | "approval_approved"
  | "approval_rejected"
  | "agent_started"
  | "agent_completed"
  | "agent_failed"
  | "tool_started"
  | "tool_completed"
  | "tool_failed";

export interface TraceEventRead {
  id: string;
  run_id: string;
  step_id: string | null;
  kind: TraceEventKind;
  payload: JsonObject;
  created_at: string;
}

export type ApprovalRequestStatus = "pending" | "approved" | "rejected";

export interface ApprovalRequestRead {
  id: string;
  run_id: string;
  workflow_revision: number;
  node_id: string;
  prompt: string;
  status: ApprovalRequestStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
}

export interface ApprovalDecisionRequest {
  note?: string | null;
}

export interface PydanticValidationIssue {
  type: string;
  loc: Array<string | number>;
  msg: string;
  input?: unknown;
  ctx?: JsonObject;
}

export interface FastApiErrorResponse {
  error?: { code: string; message: string; details?: JsonObject };
  detail?: string | PydanticValidationIssue[];
}

export function getStructuredErrorIssues(data: unknown): unknown[] | null {
  if (data === null || typeof data !== "object") return null;
  const error = (data as FastApiErrorResponse).error;
  const issues = error?.details?.issues;
  return Array.isArray(issues) ? issues : null;
}

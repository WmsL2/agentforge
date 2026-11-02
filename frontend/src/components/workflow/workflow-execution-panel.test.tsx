import { NextIntlClientProvider } from "next-intl";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ApiError } from "@/lib/api-client";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";
import type {
  ApprovalRequestRead,
  RunStepRead,
  TraceEventRead,
  WorkflowRead,
  WorkflowRunRead,
  WorkflowRunStatus,
  WorkspaceRole,
} from "@/types";
import type { WorkflowEditorState } from "./workflow-canvas-editor";

const mocks = vi.hoisted(() => ({
  useWorkspaceMembers: vi.fn(),
  useWorkflowRuns: vi.fn(),
  useWorkflowRun: vi.fn(),
  useWorkflowRunSteps: vi.fn(),
  useWorkflowTrace: vi.fn(),
  usePendingWorkflowApproval: vi.fn(),
  useWorkflowRunMutations: vi.fn(),
}));

vi.mock("@/hooks", () => mocks);

import { WorkflowExecutionPanel } from "./workflow-execution-panel";

const workflow: WorkflowRead = {
  id: "workflow-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  name: "Execution flow",
  description: null,
  definition: createDefaultWorkflowGraph(),
  revision: 7,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: null,
};

function run(status: WorkflowRunStatus = "pending", id = "run-1"): WorkflowRunRead {
  return {
    id,
    workflow_id: workflow.id,
    workflow_revision: workflow.revision,
    definition_snapshot: workflow.definition,
    status,
    input: {},
    node_outputs: {},
    output: status === "completed" ? { result: "done" } : null,
    error:
      status === "failed" ? { code: "NODE_FAILED", message: "failed", node_id: "agent-1" } : null,
    started_at: status === "pending" ? null : "2026-11-01T00:00:01Z",
    finished_at: ["completed", "failed", "cancelled"].includes(status)
      ? "2026-11-01T00:00:02Z"
      : null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: null,
  };
}

function approval(): ApprovalRequestRead {
  return {
    id: "approval-1",
    run_id: "run-1",
    workflow_revision: 7,
    node_id: "approval-1",
    prompt: "Approve this run?",
    status: "pending",
    created_at: "2026-11-01T00:00:01Z",
    decided_at: null,
    decided_by: null,
    decision_note: null,
  };
}

function query<T>(data?: T) {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  };
}

function members(role: WorkspaceRole | null = "owner") {
  return {
    data: role
      ? [
          {
            workspace_id: "workspace-1",
            user_id: "user-1",
            role,
            created_at: "now",
            updated_at: null,
          },
        ]
      : [],
    isLoading: false,
    isSuccess: true,
    isError: false,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function mutationSet() {
  return {
    submit: { mutateAsync: vi.fn(), isPending: false },
    approve: { isPending: false },
    reject: { isPending: false },
    decide: vi.fn(),
    refreshRun: vi.fn().mockResolvedValue(undefined),
  };
}

let selectedRun = run();
let mutations = mutationSet();

function renderPanel(
  editorState: WorkflowEditorState = {
    hasUnsavedChanges: false,
    operation: "idle" as const,
    hasRevisionConflict: false,
  },
  selectedWorkflow = workflow,
) {
  return render(panel(editorState, selectedWorkflow));
}

function panel(
  editorState: WorkflowEditorState = {
    hasUnsavedChanges: false,
    operation: "idle" as const,
    hasRevisionConflict: false,
  },
  selectedWorkflow = workflow,
) {
  return (
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <WorkflowExecutionPanel
        workflow={selectedWorkflow}
        userId="user-1"
        editorState={editorState}
      />
    </NextIntlClientProvider>
  );
}

describe("WorkflowExecutionPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    selectedRun = run();
    mutations = mutationSet();
    mocks.useWorkspaceMembers.mockReturnValue(members());
    mocks.useWorkflowRuns.mockReturnValue(
      query({
        items: [
          {
            id: "run-1",
            workflow_id: workflow.id,
            workflow_revision: 7,
            status: "pending",
            error: null,
            started_at: null,
            finished_at: null,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: null,
          },
        ],
        total: 1,
      }),
    );
    mocks.useWorkflowRun.mockImplementation((_user: string, _workflow: string, runId?: string) =>
      query(runId ? selectedRun : undefined),
    );
    mocks.useWorkflowRunSteps.mockReturnValue(query<RunStepRead[]>([]));
    mocks.useWorkflowTrace.mockReturnValue(query<TraceEventRead[]>([]));
    mocks.usePendingWorkflowApproval.mockReturnValue(query<ApprovalRequestRead>());
    mocks.useWorkflowRunMutations.mockReturnValue(mutations);
  });

  it.each([
    ["invalid JSON", "{"],
    ["array", "[]"],
    ["null", "null"],
    ["number", "4"],
    ["overflow", '{"value":1e400}'],
    ["unsafe integer", '{"value":9007199254740992}'],
  ])("blocks %s input without calling the API", (_case, value) => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("Workflow input (JSON object)"), {
      target: { value },
    });
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeDisabled();
    expect(mutations.submit.mutateAsync).not.toHaveBeenCalled();
  });

  it("submits a nested object once on rapid clicks and treats 202 as pending", async () => {
    const pending = deferred<WorkflowRunRead>();
    mutations.submit.mutateAsync.mockReturnValue(pending.promise);
    renderPanel();
    fireEvent.change(screen.getByLabelText("Workflow input (JSON object)"), {
      target: { value: '{"nested":{"items":[1,true,null]}}' },
    });
    const button = screen.getByRole("button", { name: "Run workflow" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mutations.submit.mutateAsync).toHaveBeenCalledOnce();
    expect(mutations.submit.mutateAsync).toHaveBeenCalledWith({
      nested: { items: [1, true, null] },
    });

    await act(async () => pending.resolve(run("pending")));
    expect(await screen.findByText(/Run accepted for saved revision r7/i)).toBeInTheDocument();
    expect(
      screen.getByText((_text, element) =>
        Boolean(element?.tagName === "P" && element.textContent === "Status: pending"),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/completed/i)).not.toBeInTheDocument();
  });

  it("tracks a created run after dispatch failure and never resubmits automatically", async () => {
    mutations.submit.mutateAsync.mockRejectedValue(
      new ApiError(503, "dispatch failed", {
        error: {
          code: "WORKFLOW_DISPATCH_FAILED",
          message: "dispatch failed",
          details: { run_id: "run-dispatch" },
        },
      }),
    );
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    expect(await screen.findByText(/Run run-dispatch was created/i)).toBeInTheDocument();
    expect(mutations.submit.mutateAsync).toHaveBeenCalledOnce();
    expect(mutations.refreshRun).toHaveBeenCalledWith("run-dispatch");
  });

  it("does not invent a run when dispatch failure has no run ID", async () => {
    mutations.submit.mutateAsync.mockRejectedValue(
      new ApiError(503, "dispatch failed", {
        error: { code: "WORKFLOW_DISPATCH_FAILED", message: "dispatch failed", details: {} },
      }),
    );
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

    expect(await screen.findByText("dispatch failed")).toBeInTheDocument();
    expect(mutations.refreshRun).not.toHaveBeenCalled();
  });

  it.each([
    [
      { hasUnsavedChanges: true, operation: "idle" as const, hasRevisionConflict: false },
      /Save or discard/,
    ],
    [
      { hasUnsavedChanges: false, operation: "validating" as const, hasRevisionConflict: false },
      /Wait for workflow validation/,
    ],
    [
      { hasUnsavedChanges: false, operation: "saving" as const, hasRevisionConflict: false },
      /Wait for workflow validation/,
    ],
    [
      { hasUnsavedChanges: false, operation: "idle" as const, hasRevisionConflict: true },
      /Resolve the server revision/,
    ],
  ])("blocks saved-version execution while editor state is unsafe", (state, reason) => {
    renderPanel(state);
    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeDisabled();
  });

  it.each(["pending", "running", "paused", "completed", "failed", "cancelled"] as const)(
    "renders the backend %s status without reinterpretation",
    async (status) => {
      selectedRun = run(status);
      const user = userEvent.setup();
      renderPanel();
      await user.click(screen.getByRole("button", { name: /run-1/i }));
      expect(
        screen.getByText((_text, element) =>
          Boolean(element?.tagName === "P" && element.textContent === `Status: ${status}`),
        ),
      ).toBeInTheDocument();
    },
  );

  it("renders server steps, trace, null values, and null step IDs", async () => {
    selectedRun = run("completed");
    mocks.useWorkflowRunSteps.mockReturnValue(
      query([
        {
          id: "step-1",
          run_id: "run-1",
          sequence: 1,
          node_id: "value-1",
          node_kind: "value",
          status: "completed",
          input: { value: 1 },
          output: null,
          error: null,
          metadata: {},
          started_at: "2026-11-01T00:00:01Z",
          finished_at: "2026-11-01T00:00:02Z",
          duration_ms: 1000,
        },
      ] satisfies RunStepRead[]),
    );
    mocks.useWorkflowTrace.mockReturnValue(
      query([
        {
          id: "trace-1",
          run_id: "run-1",
          step_id: null,
          kind: "node_completed",
          payload: { source: "server" },
          created_at: "2026-11-01T00:00:02Z",
        },
      ] satisfies TraceEventRead[]),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: /run-1/i }));

    expect(screen.getByText(/#1 · value-1 · value · completed/)).toBeInTheDocument();
    expect(screen.getByText("node_completed")).toBeInTheDocument();
    expect(screen.getByText(/Step ID: —/)).toBeInTheDocument();
    expect(screen.getAllByText("null").length).toBeGreaterThan(0);
    expect(screen.getByText(/"source": "server"/)).toBeInTheDocument();
  });

  it("does not query approval for members and locks duplicate owner decisions", async () => {
    selectedRun = run("paused");
    mocks.useWorkspaceMembers.mockReturnValue(members("member"));
    const memberView = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    expect(mocks.usePendingWorkflowApproval).toHaveBeenLastCalledWith(
      "user-1",
      workflow.id,
      "run-1",
      false,
    );
    expect(screen.getByText(/cannot decide approvals/i)).toBeInTheDocument();
    memberView.unmount();

    mocks.useWorkspaceMembers.mockReturnValue(members("owner"));
    mocks.usePendingWorkflowApproval.mockReturnValue(query(approval()));
    const pending = deferred<ApprovalRequestRead>();
    mutations.decide.mockReturnValue(pending.promise);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    expect(mocks.usePendingWorkflowApproval).toHaveBeenLastCalledWith(
      "user-1",
      workflow.id,
      "run-1",
      true,
    );
    const approveButton = screen.getByRole("button", { name: "Approve and resume" });
    fireEvent.click(approveButton);
    fireEvent.click(approveButton);
    expect(mutations.decide).toHaveBeenCalledOnce();
    await act(async () => pending.resolve({ ...approval(), status: "approved" }));
    expect(await screen.findByText(/asynchronous resume/i)).toBeInTheDocument();
  });

  it.each(["approved", "rejected"] as const)(
    "does not offer another decision for an approval that is already %s",
    (status) => {
      selectedRun = run("paused");
      mocks.usePendingWorkflowApproval.mockReturnValue(query({ ...approval(), status }));
      renderPanel();
      fireEvent.click(screen.getByRole("button", { name: /run-1/i }));

      expect(screen.getByText("Approve this run?")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Approve and resume" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
      expect(mutations.decide).not.toHaveBeenCalled();
    },
  );

  it("does not allow approval when membership loading failed", () => {
    selectedRun = run("paused");
    mocks.useWorkspaceMembers.mockReturnValue({
      ...members("owner"),
      isSuccess: false,
      isError: true,
    });
    mocks.usePendingWorkflowApproval.mockReturnValue(query(approval()));
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));

    expect(mocks.usePendingWorkflowApproval).toHaveBeenLastCalledWith(
      "user-1",
      workflow.id,
      "run-1",
      false,
    );
    expect(screen.queryByRole("button", { name: "Approve and resume" })).not.toBeInTheDocument();
    expect(mutations.decide).not.toHaveBeenCalled();
  });

  it("does not submit a stale cached approval after the pending query fails", () => {
    selectedRun = run("paused");
    mocks.usePendingWorkflowApproval.mockReturnValue({
      ...query(approval()),
      isError: true,
      error: new ApiError(404, "not found"),
    });
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));

    expect(screen.getByText("No pending approval is available.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve and resume" })).not.toBeInTheDocument();
    expect(mutations.decide).not.toHaveBeenCalled();
  });

  it("removes approval actions when permission changes during a pending decision", async () => {
    selectedRun = run("paused");
    mocks.usePendingWorkflowApproval.mockReturnValue(query(approval()));
    const pending = deferred<ApprovalRequestRead>();
    mutations.decide.mockReturnValue(pending.promise);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const view = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    fireEvent.click(screen.getByRole("button", { name: "Approve and resume" }));
    expect(mutations.decide).toHaveBeenCalledOnce();

    mocks.useWorkspaceMembers.mockReturnValue(members("member"));
    view.rerender(panel());
    expect(screen.queryByRole("button", { name: "Approve and resume" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();

    await act(async () => pending.resolve({ ...approval(), status: "approved" }));
    expect(mutations.decide).toHaveBeenCalledOnce();
  });

  it("enforces the 2000 character approval note boundary", () => {
    selectedRun = run("paused");
    mocks.usePendingWorkflowApproval.mockReturnValue(query(approval()));
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    const note = screen.getByLabelText("Decision note (optional)");
    fireEvent.change(note, { target: { value: "a".repeat(2000) } });
    expect(screen.getByRole("button", { name: "Approve and resume" })).toBeEnabled();
    fireEvent.change(note, { target: { value: "a".repeat(2001) } });
    expect(screen.getByText(/2000 characters or fewer/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and resume" })).toBeDisabled();
  });

  it("renders history empty and error states, retries, and requests the next page", async () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mocks.useWorkflowRuns.mockReturnValue({
      ...query<{ items: []; total: number }>({ items: [], total: 0 }),
      isError: true,
      error: new ApiError(403, "forbidden"),
      refetch,
    });
    const errorView = renderPanel();
    expect(
      screen.getByText("You do not have permission to access this execution resource."),
    ).toBeInTheDocument();
    expect(screen.getByText("No runs have been recorded for this workflow.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledOnce();
    errorView.unmount();

    mocks.useWorkflowRuns.mockReturnValue(
      query({
        items: [
          {
            id: "run-1",
            workflow_id: workflow.id,
            workflow_revision: 7,
            status: "pending",
            error: null,
            started_at: null,
            finished_at: null,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: null,
          },
        ],
        total: 21,
      }),
    );
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(mocks.useWorkflowRuns).toHaveBeenLastCalledWith("user-1", workflow.id, 10, 10);
    expect(screen.getByText("Page 2")).toBeInTheDocument();
  });

  it("shows structured submission validation issues and distinct not-found errors", async () => {
    mutations.submit.mutateAsync.mockRejectedValue(
      new ApiError(422, "validation failed", {
        error: {
          code: "VALIDATION_ERROR",
          message: "validation failed",
          details: { issues: ["input.foo is required", "input.bar is invalid"] },
        },
      }),
    );
    const validationView = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    expect(await screen.findByText("input.foo is required")).toBeInTheDocument();
    expect(screen.getByText("input.bar is invalid")).toBeInTheDocument();
    validationView.unmount();

    mocks.useWorkflowRuns.mockReturnValue({
      ...query(),
      isError: true,
      error: new ApiError(404, "missing"),
    });
    renderPanel();
    expect(
      screen.getByText("The workflow no longer exists or is not accessible."),
    ).toBeInTheDocument();
  });

  it("refreshes server state on approval conflict and supports rejection", async () => {
    selectedRun = run("paused");
    mocks.usePendingWorkflowApproval.mockReturnValue(query(approval()));
    mutations.decide
      .mockRejectedValueOnce(new ApiError(409, "already decided"))
      .mockResolvedValueOnce({ ...approval(), status: "rejected" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    fireEvent.click(screen.getByRole("button", { name: "Approve and resume" }));
    expect(await screen.findByText("already decided")).toBeInTheDocument();
    expect(mutations.refreshRun).toHaveBeenCalledWith("run-1");

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(mutations.decide).toHaveBeenLastCalledWith("reject", "run-1", "approval-1", null),
    );
    expect(await screen.findByText(/Rejection was saved/i)).toBeInTheDocument();
  });

  it("truncates large server JSON while retaining a copy affordance", async () => {
    selectedRun = { ...run("completed"), output: { payload: "x".repeat(21000) } };
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    expect(screen.getAllByRole("button", { name: "Copy JSON" }).length).toBeGreaterThan(0);
    const renderedJson = screen
      .getAllByText((_text, element) => element?.tagName === "PRE")
      .map((element) => element.textContent ?? "");
    expect(renderedJson.some((value) => value.endsWith("…") && value.length <= 20_002)).toBe(true);
    expect(renderedJson.some((value) => value.includes("x".repeat(21000)))).toBe(false);
  });

  it("ignores workflow A submission results and preserves workflow B's newer lock", async () => {
    const workflowB = { ...workflow, id: "workflow-2", name: "Workflow B" };
    const pendingA = deferred<WorkflowRunRead>();
    const pendingB = deferred<WorkflowRunRead>();
    const mutationsA = mutationSet();
    const mutationsB = mutationSet();
    mutationsA.submit.mutateAsync.mockReturnValue(pendingA.promise);
    mutationsB.submit.mutateAsync.mockReturnValue(pendingB.promise);
    mocks.useWorkflowRunMutations.mockImplementation((_user: string, workflowId: string) =>
      workflowId === workflow.id ? mutationsA : mutationsB,
    );
    mocks.useWorkflowRuns.mockReturnValue(query({ items: [], total: 0 }));

    const view = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    expect(mutationsA.submit.mutateAsync).toHaveBeenCalledOnce();

    view.rerender(panel(undefined, workflowB));
    await waitFor(() =>
      expect(screen.getByLabelText("Workflow input (JSON object)")).toHaveValue("{}"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    expect(mutationsB.submit.mutateAsync).toHaveBeenCalledOnce();

    await act(async () => pendingA.resolve(run("pending", "run-a")));
    expect(screen.queryByText(/Run accepted for saved revision/i)).not.toBeInTheDocument();
    expect(screen.queryByText("run-a")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    expect(mutationsB.submit.mutateAsync).toHaveBeenCalledOnce();

    await act(async () =>
      pendingB.resolve({
        ...run("pending", "run-b"),
        workflow_id: workflowB.id,
      }),
    );
    expect(await screen.findByText(/Run accepted for saved revision r7/i)).toBeInTheDocument();
  });

  it("does not expose workflow A dispatch failure state after switching to B", async () => {
    const workflowB = { ...workflow, id: "workflow-2", name: "Workflow B" };
    const pendingA = deferred<WorkflowRunRead>();
    const mutationsA = mutationSet();
    const mutationsB = mutationSet();
    mutationsA.submit.mutateAsync.mockReturnValue(pendingA.promise);
    mocks.useWorkflowRunMutations.mockImplementation((_user: string, workflowId: string) =>
      workflowId === workflow.id ? mutationsA : mutationsB,
    );
    mocks.useWorkflowRuns.mockReturnValue(query({ items: [], total: 0 }));

    const view = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    view.rerender(panel(undefined, workflowB));
    await waitFor(() =>
      expect(screen.getByLabelText("Workflow input (JSON object)")).toHaveValue("{}"),
    );

    await act(async () =>
      pendingA.reject(
        new ApiError(503, "dispatch failed", {
          error: {
            code: "WORKFLOW_DISPATCH_FAILED",
            message: "dispatch failed",
            details: { run_id: "run-a" },
          },
        }),
      ),
    );

    expect(mutationsA.refreshRun).toHaveBeenCalledWith("run-a");
    expect(screen.queryByText(/Run run-a was created/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Selected run")).not.toBeInTheDocument();
  });

  it("ignores an old workflow approval response after switching workflows", async () => {
    const workflowB = { ...workflow, id: "workflow-2", name: "Workflow B" };
    const decisionA = deferred<ApprovalRequestRead>();
    const mutationsA = mutationSet();
    const mutationsB = mutationSet();
    mutationsA.decide.mockReturnValue(decisionA.promise);
    mocks.useWorkflowRunMutations.mockImplementation((_user: string, workflowId: string) =>
      workflowId === workflow.id ? mutationsA : mutationsB,
    );
    mocks.useWorkflowRuns.mockImplementation((_user: string, workflowId: string) =>
      query({
        items: [
          {
            id: workflowId === workflow.id ? "run-a" : "run-b",
            workflow_id: workflowId,
            workflow_revision: 7,
            status: "paused" as const,
            error: null,
            started_at: "2026-11-01T00:00:01Z",
            finished_at: null,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: null,
          },
        ],
        total: 1,
      }),
    );
    mocks.useWorkflowRun.mockImplementation((_user: string, workflowId: string, runId?: string) =>
      query(
        runId
          ? {
              ...run("paused", runId),
              workflow_id: workflowId,
            }
          : undefined,
      ),
    );
    mocks.usePendingWorkflowApproval.mockImplementation(
      (_user: string, _workflowId: string, runId?: string) =>
        query(runId ? { ...approval(), id: `approval-${runId}`, run_id: runId } : undefined),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const view = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-a/i }));
    fireEvent.click(screen.getByRole("button", { name: "Approve and resume" }));
    expect(mutationsA.decide).toHaveBeenCalledOnce();

    view.rerender(panel(undefined, workflowB));
    await waitFor(() => expect(screen.getByRole("button", { name: /run-b/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /run-b/i }));
    expect(screen.getByRole("button", { name: "Approve and resume" })).toBeEnabled();

    await act(async () => decisionA.resolve({ ...approval(), status: "approved" }));
    expect(screen.queryByText(/asynchronous resume/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and resume" })).toBeEnabled();
  });

  it.each([
    ["running", "completed"],
    ["running", "failed"],
    ["paused", "cancelled"],
  ] as const)(
    "performs one final related-data refresh for %s to %s",
    async (initialStatus, terminalStatus) => {
      const runQuery = query(run(initialStatus));
      const stepsQuery = query<RunStepRead[]>([]);
      const traceQuery = query<TraceEventRead[]>([]);
      const historyQuery = query({
        items: [
          {
            id: "run-1",
            workflow_id: workflow.id,
            workflow_revision: 7,
            status: initialStatus,
            error: null,
            started_at: "2026-11-01T00:00:01Z",
            finished_at: null,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: null,
          },
        ],
        total: 1,
      });
      mocks.useWorkflowRun.mockImplementation((_user: string, _workflow: string, runId?: string) =>
        runId ? runQuery : query(),
      );
      mocks.useWorkflowRunSteps.mockReturnValue(stepsQuery);
      mocks.useWorkflowTrace.mockReturnValue(traceQuery);
      mocks.useWorkflowRuns.mockReturnValue(historyQuery);

      const view = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
      runQuery.data = run(terminalStatus);
      view.rerender(panel());

      await waitFor(() => {
        expect(stepsQuery.refetch).toHaveBeenCalledOnce();
        expect(traceQuery.refetch).toHaveBeenCalledOnce();
        expect(historyQuery.refetch).toHaveBeenCalledOnce();
      });
      view.rerender(panel());
      expect(stepsQuery.refetch).toHaveBeenCalledOnce();
      expect(traceQuery.refetch).toHaveBeenCalledOnce();
      expect(historyQuery.refetch).toHaveBeenCalledOnce();
    },
  );

  it("does not run a terminal refresh for a different selected run", () => {
    const runQueries = {
      "run-1": query(run("running", "run-1")),
      "run-2": query(run("completed", "run-2")),
    };
    const stepsQuery = query<RunStepRead[]>([]);
    const traceQuery = query<TraceEventRead[]>([]);
    const historyQuery = query({
      items: [
        {
          id: "run-1",
          workflow_id: workflow.id,
          workflow_revision: 7,
          status: "running" as const,
          error: null,
          started_at: "2026-11-01T00:00:01Z",
          finished_at: null,
          created_at: "2026-11-01T00:00:00Z",
          updated_at: null,
        },
        {
          id: "run-2",
          workflow_id: workflow.id,
          workflow_revision: 7,
          status: "completed" as const,
          error: null,
          started_at: "2026-11-01T00:00:01Z",
          finished_at: "2026-11-01T00:00:02Z",
          created_at: "2026-11-01T00:00:00Z",
          updated_at: null,
        },
      ],
      total: 2,
    });
    mocks.useWorkflowRun.mockImplementation((_user: string, _workflow: string, runId?: string) =>
      query(runId ? runQueries[runId as keyof typeof runQueries].data : undefined),
    );
    mocks.useWorkflowRunSteps.mockReturnValue(stepsQuery);
    mocks.useWorkflowTrace.mockReturnValue(traceQuery);
    mocks.useWorkflowRuns.mockReturnValue(historyQuery);

    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));
    fireEvent.click(screen.getByRole("button", { name: /run-2/i }));

    expect(stepsQuery.refetch).not.toHaveBeenCalled();
    expect(traceQuery.refetch).not.toHaveBeenCalled();
    expect(historyQuery.refetch).not.toHaveBeenCalled();
  });

  it("hides related data and approval controls for a workflow-mismatched run", () => {
    selectedRun = { ...run("paused"), workflow_id: "workflow-other" };
    mocks.useWorkflowRunSteps.mockReturnValue(
      query([{ id: "secret-step" }] as unknown as RunStepRead[]),
    );
    mocks.useWorkflowTrace.mockReturnValue(
      query([{ id: "secret-trace", kind: "tool_started" }] as unknown as TraceEventRead[]),
    );
    mocks.usePendingWorkflowApproval.mockReturnValue(query(approval()));
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /run-1/i }));

    expect(screen.getByText(/does not belong to this workflow/i)).toBeInTheDocument();
    expect(screen.queryByText("secret-step")).not.toBeInTheDocument();
    expect(screen.queryByText("tool_started")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve and resume" })).not.toBeInTheDocument();
    expect(mocks.useWorkflowRunSteps).toHaveBeenLastCalledWith(
      "user-1",
      workflow.id,
      undefined,
      undefined,
    );
  });

  it("clears the selected run and input when switching workflows", async () => {
    const user = userEvent.setup();
    const view = renderPanel();
    await user.click(screen.getByRole("button", { name: /run-1/i }));
    fireEvent.change(screen.getByLabelText("Workflow input (JSON object)"), {
      target: { value: '{"old":true}' },
    });
    expect(screen.getByText("Selected run")).toBeInTheDocument();

    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowExecutionPanel
          workflow={{ ...workflow, id: "workflow-2" }}
          userId="user-1"
          editorState={{ hasUnsavedChanges: false, operation: "idle", hasRevisionConflict: false }}
        />
      </NextIntlClientProvider>,
    );

    await waitFor(() => expect(screen.queryByText("Selected run")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Workflow input (JSON object)")).toHaveValue("{}");
  });
});

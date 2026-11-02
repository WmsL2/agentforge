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
  return render(
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <WorkflowExecutionPanel
        workflow={selectedWorkflow}
        userId="user-1"
        editorState={editorState}
      />
    </NextIntlClientProvider>,
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

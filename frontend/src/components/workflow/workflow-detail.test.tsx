import { useState } from "react";
import { NextIntlClientProvider } from "next-intl";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import enMessages from "../../../messages/en.json";
import plMessages from "../../../messages/pl.json";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";
import type { WorkflowCanvasEditorProps } from "./workflow-canvas-editor";

const mocks = vi.hoisted(() => ({ useWorkflow: vi.fn() }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ workflowId: "workflow-1" }),
  usePathname: () => "/pl/workflows/workflow-1",
  useSearchParams: () => new URLSearchParams("workspace_id=workspace-1"),
}));

vi.mock("@/hooks", () => ({ useWorkflow: mocks.useWorkflow }));

import { WorkflowDetail } from "./workflow-detail";

const workflow = {
  id: "workflow-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  name: "Review workflow",
  description: null,
  definition: createDefaultWorkflowGraph(),
  revision: 3,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: null,
};

function StatefulEditor({ onDirtyChange }: WorkflowCanvasEditorProps) {
  const [draft, setDraft] = useState("");
  const [graphValue, setGraphValue] = useState("saved");
  return (
    <div>
      <p>selected:value-1</p>
      <label htmlFor="draft-value">Node draft</label>
      <input
        id="draft-value"
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          onDirtyChange?.(true);
        }}
      />
      <p>graph:{graphValue}</p>
      <button
        type="button"
        onClick={() => {
          setGraphValue("changed");
          onDirtyChange?.(true);
        }}
      >
        Apply graph change
      </button>
    </div>
  );
}

describe("localized workflow detail", () => {
  it("renders the canvas and preserves the Polish workspace return context", () => {
    mocks.useWorkflow.mockReturnValue({
      data: { ...workflow, name: "Polski przepływ" },
      isLoading: false,
      isError: false,
    });

    render(
      <NextIntlClientProvider locale="pl" messages={{ workflows: plMessages.workflows }}>
        <WorkflowDetail userId="user-1" CanvasEditorComponent={() => <div>canvas editor</div>} />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("canvas editor")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Wróć do przepływów/i })).toHaveAttribute(
      "href",
      "/pl/workflows?workspace_id=workspace-1",
    );
    expect(screen.getByText("r3")).toBeInTheDocument();
  });

  it("cancels breadcrumb navigation and preserves unapplied draft and selection", () => {
    mocks.useWorkflow.mockReturnValue({ data: workflow, isLoading: false, isError: false });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <NextIntlClientProvider locale="en" messages={{ workflows: enMessages.workflows }}>
        <WorkflowDetail userId="user-1" CanvasEditorComponent={StatefulEditor} />
      </NextIntlClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("Node draft"), {
      target: { value: '{"pending":true}' },
    });
    expect(fireEvent.click(screen.getByRole("link", { name: "Workflows" }))).toBe(false);

    expect(confirm).toHaveBeenCalledWith(enMessages.workflows.canvas.leaveConfirm);
    expect(screen.getByLabelText("Node draft")).toHaveValue('{"pending":true}');
    expect(screen.getByText("selected:value-1")).toBeInTheDocument();
  });

  it("protects applied graph changes consistently and allows confirmed navigation", async () => {
    mocks.useWorkflow.mockReturnValue({ data: workflow, isLoading: false, isError: false });
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const user = userEvent.setup();
    render(
      <NextIntlClientProvider locale="en" messages={{ workflows: enMessages.workflows }}>
        <WorkflowDetail userId="user-1" CanvasEditorComponent={StatefulEditor} />
      </NextIntlClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Apply graph change" }));
    const back = screen.getByRole("link", { name: /Back to workflows/i });
    expect(fireEvent.click(back)).toBe(false);
    expect(screen.getByText("graph:changed")).toBeInTheDocument();

    let preventedByGuard = true;
    document.addEventListener(
      "click",
      (event) => {
        preventedByGuard = event.defaultPrevented;
        event.preventDefault();
      },
      { once: true },
    );
    fireEvent.click(back);
    expect(preventedByGuard).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});

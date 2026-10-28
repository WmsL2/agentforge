import { NextIntlClientProvider } from "next-intl";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/pl.json";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";

const mocks = vi.hoisted(() => ({ useWorkflow: vi.fn() }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ workflowId: "workflow-1" }),
  usePathname: () => "/pl/workflows/workflow-1",
  useSearchParams: () => new URLSearchParams("workspace_id=workspace-1"),
}));

vi.mock("@/hooks", () => ({ useWorkflow: mocks.useWorkflow }));

import { WorkflowDetail } from "./workflow-detail";

describe("localized workflow detail", () => {
  it("renders the canvas and preserves the Polish workspace return context", () => {
    mocks.useWorkflow.mockReturnValue({
      data: {
        id: "workflow-1",
        user_id: "user-1",
        workspace_id: "workspace-1",
        name: "Polski przepływ",
        description: null,
        definition: createDefaultWorkflowGraph(),
        revision: 3,
        created_at: "2026-10-28T00:00:00Z",
        updated_at: null,
      },
      isLoading: false,
      isError: false,
    });

    render(
      <NextIntlClientProvider locale="pl" messages={{ workflows: messages.workflows }}>
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
});

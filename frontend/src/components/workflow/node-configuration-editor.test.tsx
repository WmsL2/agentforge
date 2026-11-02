import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import type { CanvasNode } from "@/lib/workflow/canvas-adapter";
import type { JsonObject, WorkflowNodeKind } from "@/types";

import { NodeConfigurationEditor, type NodeConfigurationDraft } from "./node-configuration-editor";

function node(kind: WorkflowNodeKind, config: JsonObject = {}): CanvasNode {
  return {
    id: `${kind}-1`,
    type: "workflowNode",
    position: { x: 12, y: 34 },
    data: { kind, config, metadata: { keep: true } },
  };
}

function Harness({
  selected,
  editable = true,
  disabled = false,
  onApply = vi.fn(),
}: {
  selected: CanvasNode | null;
  editable?: boolean;
  disabled?: boolean;
  onApply?: (nodeId: string, config: JsonObject) => void;
}) {
  const [draft, setDraft] = useState<NodeConfigurationDraft | undefined>();
  return (
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <NodeConfigurationEditor
        node={selected}
        draft={draft}
        editable={editable}
        disabled={disabled}
        onDraftChange={(_nodeId, next) => setDraft(next ?? undefined)}
        onApply={(nodeId, config) => {
          onApply(nodeId, config);
          setDraft(undefined);
        }}
      />
    </NextIntlClientProvider>
  );
}

describe("NodeConfigurationEditor", () => {
  it("shows an empty state and read-only START/END identity without creating drafts", () => {
    const view = render(<Harness selected={null} />);
    expect(screen.getByText(/Select a node/i)).toBeInTheDocument();

    view.rerender(<Harness selected={node("start")} />);
    expect(screen.getByDisplayValue("start-1")).toBeDisabled();
    expect(screen.getByDisplayValue("START")).toBeDisabled();
    expect(screen.getByText(/no editable configuration fields/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply configuration/i })).not.toBeInTheDocument();

    view.rerender(<Harness selected={node("end")} />);
    expect(screen.getByDisplayValue("end-1")).toBeDisabled();
    expect(screen.getByText(/no editable configuration fields/i)).toBeInTheDocument();
  });

  it.each([
    ["number", "42", 42],
    ["string", '"hello"', "hello"],
    ["boolean", "true", true],
    ["null", "null", null],
    ["array", '[1,"two",false]', [1, "two", false]],
    ["object", '{"name":"test","count":3}', { name: "test", count: 3 }],
  ])(
    "applies a %s VALUE without coercion and preserves other config",
    async (_label, text, expected) => {
      const onApply = vi.fn();
      const user = userEvent.setup();
      render(
        <Harness selected={node("value", { value: "initial", keep: "yes" })} onApply={onApply} />,
      );

      fireEvent.change(screen.getByLabelText(/JSON value/), { target: { value: text } });
      await user.click(screen.getByRole("button", { name: "Apply configuration" }));

      expect(onApply).toHaveBeenCalledWith("value-1", { value: expected, keep: "yes" });
    },
  );

  it("distinguishes a missing VALUE field from explicit null", async () => {
    const onApply = vi.fn();
    const user = userEvent.setup();
    const view = render(<Harness selected={node("value", { keep: 1 })} onApply={onApply} />);

    expect(screen.getByLabelText("Include the value field")).not.toBeChecked();
    await user.click(screen.getByLabelText("Include the value field"));
    expect(screen.getByLabelText(/JSON value/)).toHaveValue("null");
    await user.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(onApply).toHaveBeenLastCalledWith("value-1", { keep: 1, value: null });

    onApply.mockClear();
    view.rerender(<Harness selected={node("value", { value: null, keep: 1 })} onApply={onApply} />);
    await user.click(screen.getByLabelText("Include the value field"));
    await user.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(onApply).toHaveBeenCalledWith("value-1", { keep: 1 });
  });

  it("rejects invalid VALUE JSON", () => {
    render(<Harness selected={node("value", { value: null })} />);
    fireEvent.change(screen.getByLabelText(/JSON value/), { target: { value: "{" } });

    expect(screen.getByText("Enter a valid JSON value.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  });

  it("validates AGENT instruction, fixes runner, adds and clears optional model", async () => {
    const onApply = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <Harness
        selected={node("agent", { runner: "legacy", instruction: "Old", model: "old-model" })}
        onApply={onApply}
      />,
    );

    expect(screen.getByDisplayValue("langgraph")).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Instruction/), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Instruction/), { target: { value: "Analyze input." } });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "gpt-5-mini" } });
    await user.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(onApply).toHaveBeenLastCalledWith("agent-1", {
      runner: "langgraph",
      instruction: "Analyze input.",
      model: "gpt-5-mini",
    });

    onApply.mockClear();
    view.rerender(
      <Harness
        selected={node("agent", {
          runner: "langgraph",
          instruction: "Analyze input.",
          model: "gpt-5-mini",
        })}
        onApply={onApply}
      />,
    );
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(onApply).toHaveBeenCalledWith("agent-1", {
      runner: "langgraph",
      instruction: "Analyze input.",
    });
  });

  it("validates APPROVAL prompt and preserves valid configuration", async () => {
    const onApply = vi.fn();
    const user = userEvent.setup();
    render(<Harness selected={node("approval", { prompt: "Old" })} onApply={onApply} />);

    fireEvent.change(screen.getByLabelText(/Approval prompt/), { target: { value: " " } });
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Approval prompt/), {
      target: { value: "Approve this workflow?" },
    });
    await user.click(screen.getByRole("button", { name: "Apply configuration" }));
    expect(onApply).toHaveBeenCalledWith("approval-1", { prompt: "Approve this workflow?" });
  });

  it.each([
    ["agent" as const, { runner: "langgraph", instruction: "Run", tools: [] }],
    ["approval" as const, { prompt: "Approve?", timeout: 30 }],
  ])(
    "reports and preserves unsupported %s fields instead of silently deleting them",
    (kind, config) => {
      const onApply = vi.fn();
      render(<Harness selected={node(kind, config)} onApply={onApply} />);

      expect(screen.getByRole("alert")).toHaveTextContent(/Unsupported configuration fields/);
      expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
      expect(onApply).not.toHaveBeenCalled();
    },
  );

  it("allows read-only inspection but disables every configuration control", () => {
    render(
      <Harness
        selected={node("agent", { runner: "langgraph", instruction: "Inspect" })}
        editable={false}
      />,
    );

    expect(screen.getByText(/Configuration is read-only/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Instruction/)).toBeDisabled();
    expect(screen.getByLabelText("Model")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  });
});

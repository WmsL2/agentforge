import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";
import messages from "../../../messages/en.json";
import polish from "../../../messages/pl.json";
import { WorkflowKnowledgeResults } from "./workflow-knowledge-results";
import type { RunStepRead, WorkflowRunRead } from "@/types";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";

const source = {
  chunk_id: "chunk-real",
  document_id: "document-real",
  filename: "真实.pdf",
  page_start: null,
  page_end: 3,
  similarity_score: -0.1,
};
const output = {
  query: "actual query",
  total: 7,
  results: [
    { ...source, content: "first evidence" },
    { ...source, chunk_id: "second", content: "second evidence", similarity_score: 0 },
  ],
};
function renderResult({
  kind = "knowledge",
  value = output as unknown,
  ready = true,
  status = "completed",
  bound = true,
} = {}) {
  const run = {
    id: "r3",
    workflow_id: "wf",
    definition_snapshot: {
      ...createDefaultWorkflowGraph(),
      nodes: [
        {
          id: "node",
          kind,
          config: bound ? { knowledge_base_id: "00000000-0000-0000-0000-000000000001" } : {},
          metadata: {},
        },
      ],
    },
  } as WorkflowRunRead;
  const step = {
    id: "step",
    run_id: "r3",
    node_id: "node",
    node_kind: kind,
    status,
    output: value,
  } as RunStepRead;
  return render(
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <WorkflowKnowledgeResults workflowId="wf" runId="r3" run={run} step={step} ready={ready} />
    </NextIntlClientProvider>,
  );
}
describe("WorkflowKnowledgeResults", () => {
  it("shows actual fields, counts and backend order", () => {
    const view = renderResult();
    const region = screen.getByRole("region", { name: "Knowledge Retrieval" });
    expect(within(region).getByText("actual query")).toBeInTheDocument();
    expect(region).toHaveTextContent("Total: 7 · Results: 2");
    const rows = within(region).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("first evidence");
    expect(rows[1]).toHaveTextContent("second evidence");
    for (const text of ["真实.pdf", "chunk-real", "document-real", "—", "3", "-0.1"])
      expect(rows[0]).toHaveTextContent(text);
    expect(view.container.querySelector("a,img")).toBeNull();
    expect(region).toHaveTextContent("not answer accuracy or confidence");
  });
  it("shows normal empty retrieval", () => {
    renderResult({ value: { query: "q", total: 0, results: [] } });
    expect(screen.getByText("No retrieval matches were returned.")).toBeInTheDocument();
  });
  it("renders hostile HTML and URLs as plain text", () => {
    const hostile = '<img src="https://external/x" onerror="alert(1)"><script>bad()</script>';
    const view = renderResult({
      value: {
        ...output,
        query: hostile,
        results: [{ ...source, content: hostile, filename: hostile }],
      },
    });
    expect(screen.getAllByText(hostile)).toHaveLength(3);
    expect(view.container.querySelector("img,script,a,iframe")).toBeNull();
  });
  it("bounds query, content and metadata with explicit truncation", () => {
    const text = "😀".repeat(10_001);
    renderResult({
      value: { ...output, query: text, results: [{ ...source, filename: text, content: text }] },
    });
    expect(screen.getAllByText(/Text truncated to .* Unicode code points\./)).toHaveLength(3);
    expect(screen.getAllByText("😀".repeat(10_000))).toHaveLength(3);
  });
  it("shows actual Agent answer and actual sources only", () => {
    renderResult({
      kind: "agent",
      value: {
        answer: "answer with invented citation [999]",
        status: "answered",
        sources: [source],
      },
    });
    expect(screen.getByText("answer with invented citation [999]")).toBeInTheDocument();
    expect(screen.getByText("chunk-real")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
  it("does not turn answer citations into sources", () => {
    renderResult({
      kind: "agent",
      value: { answer: "[1] https://fake/source", status: "answered", sources: [] },
    });
    expect(screen.getByText("No sources were returned.")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });
  it("localizes no_evidence without claiming execution failure", () => {
    renderResult({
      kind: "agent",
      value: { answer: "backend deterministic message", status: "no_evidence", sources: [] },
    });
    expect(screen.getByText(/Insufficient supporting evidence/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("No retrieval matches were returned.")).not.toBeInTheDocument();
  });
  it("keeps a plain Agent outside the Knowledge renderer", () => {
    renderResult({
      kind: "agent",
      bound: false,
      value: { answer: "ordinary", status: "answered", sources: [] },
    });
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(screen.queryByText("ordinary")).not.toBeInTheDocument();
  });
  it.each(["running", "failed", "interrupted"])("does not label %s as no evidence", (status) => {
    renderResult({ status, value: null });
    expect(screen.queryByText(/No retrieval|Insufficient/)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
  it.each([null, {}, { ...output, results: [{}] }])("shows invalid output %# safely", (value) => {
    renderResult({ value });
    expect(screen.getByText(/cannot be interpreted/)).toBeInTheDocument();
    expect(screen.queryByText(/No retrieval matches/)).not.toBeInTheDocument();
  });
  it("hides cached structured content while query verification is incomplete", () => {
    renderResult({ ready: false });
    expect(screen.getByText(/unavailable for interpretation/)).toBeInTheDocument();
    expect(screen.queryByText("first evidence")).not.toBeInTheDocument();
  });
  it("does not execute or parse Agent markup and truncates long answers", () => {
    const view = renderResult({
      kind: "agent",
      value: {
        answer: "<script>bad()</script>" + "a".repeat(10_000),
        status: "answered",
        sources: [],
      },
    });
    expect(view.container.querySelector("script,a,img")).toBeNull();
    expect(screen.getByText(/Text truncated/)).toBeInTheDocument();
  });
  it("keeps en/pl key parity", () => {
    expect(Object.keys(messages.workflows.execution.knowledgeResults).sort()).toEqual(
      Object.keys(polish.workflows.execution.knowledgeResults).sort(),
    );
  });
});

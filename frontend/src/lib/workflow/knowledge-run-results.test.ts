import { describe, expect, it } from "vitest";
import type { RunStepRead, WorkflowRunRead } from "@/types";
import { createDefaultWorkflowGraph } from "./default-graph";
import { executionText, knowledgeRunResult } from "./knowledge-run-results";

const base = "00000000-0000-0000-0000-000000000001";
const source = {
  chunk_id: "c",
  document_id: "d",
  filename: "文档.pdf",
  page_start: null,
  page_end: null,
  similarity_score: 0,
};
const retrieval = {
  query: "real query",
  total: 2,
  results: [
    { ...source, content: "evidence" },
    { ...source, chunk_id: "c2", similarity_score: -0.5, content: "second" },
  ],
};
function run(kind = "knowledge", config = {}): WorkflowRunRead {
  return {
    id: "r3",
    workflow_id: "wf",
    workflow_revision: 3,
    definition_snapshot: {
      ...createDefaultWorkflowGraph(),
      nodes: [{ id: "node", kind, config, metadata: {} }],
    },
    status: "completed",
    input: {},
    output: null,
    node_outputs: {},
    error: null,
    started_at: null,
    finished_at: null,
    created_at: "now",
    updated_at: null,
  } as WorkflowRunRead;
}
function step(output: unknown = retrieval, node_kind = "knowledge"): RunStepRead {
  return {
    id: "step",
    run_id: "r3",
    sequence: 1,
    node_id: "node",
    node_kind,
    status: "completed",
    input: {},
    output,
    error: null,
    metadata: {},
    started_at: "now",
    finished_at: null,
    duration_ms: null,
  } as RunStepRead;
}
const read = (output: unknown) => knowledgeRunResult("wf", "r3", run(), { ...step(), output });
const agent = (output: unknown, config = { knowledge_base_id: base }) =>
  knowledgeRunResult("wf", "r3", run("agent", config), step(output, "agent"));

describe("persisted knowledge result contract", () => {
  it("keeps actual totals, fields, null pages, zero/negative score and order", () => {
    expect(read(retrieval)).toEqual({ kind: "retrieval", ...retrieval });
  });
  it.each([
    { query: "q", total: 0, results: [] },
    { query: "q", total: 4, results: [] },
  ])("accepts empty results without inventing total", (output) => {
    expect(read(output)).toEqual({ kind: "retrieval", ...output });
  });
  it.each([
    null,
    undefined,
    [],
    "text",
    {},
    { ...retrieval, query: 1 },
    { ...retrieval, total: -1 },
    { ...retrieval, total: 1.5 },
    { ...retrieval, total: NaN },
    { ...retrieval, total: Infinity },
    { ...retrieval, total: "2" },
    { ...retrieval, results: null },
  ])("fails closed for malformed retrieval %#", (output) => {
    expect(read(output)).toEqual({ kind: "invalid" });
  });
  it.each([
    "chunk_id",
    "document_id",
    "filename",
    "content",
    "page_start",
    "page_end",
    "similarity_score",
  ])("requires %s in every match", (key) => {
    const item: Record<string, unknown> = { ...retrieval.results[0] };
    delete item[key];
    expect(read({ ...retrieval, results: [item] })).toEqual({ kind: "invalid" });
  });
  it.each([
    { chunk_id: 5 },
    { document_id: null },
    { filename: [] },
    { content: {} },
    { page_start: "1" },
    { page_end: 1.5 },
    { similarity_score: "0" },
    { similarity_score: NaN },
    { similarity_score: Infinity },
  ])("rejects malformed match fields %#", (patch) => {
    expect(read({ ...retrieval, results: [{ ...retrieval.results[0], ...patch }] })).toEqual({
      kind: "invalid",
    });
  });
  it("accepts answered with actual sources and positive pages", () => {
    const output = {
      answer: "answer",
      status: "answered",
      sources: [{ ...source, page_start: 1, page_end: 2 }],
    };
    expect(agent(output)).toEqual({ kind: "agent", ...output });
  });
  it.each(["answered", "no_evidence"])("accepts %s with empty sources", (status) => {
    const output = { answer: "actual answer", status, sources: [] };
    expect(agent(output)).toEqual({ kind: "agent", ...output });
  });
  it.each([
    null,
    {},
    { answer: 4, status: "answered", sources: [] },
    { answer: "a", status: "unknown", sources: [] },
    { answer: "a", status: "answered" },
    { answer: "a", status: "answered", sources: [{}] },
    { answer: "a", status: "no_evidence", sources: [source] },
  ])("rejects malformed agent response %#", (output) => {
    expect(agent(output)).toEqual({ kind: "invalid" });
  });
  it("never infers Knowledge binding or sources from ordinary Agent output", () => {
    expect(
      agent(
        { answer: "[1] https://private", status: "answered", sources: [source] },
        {} as { knowledge_base_id: string },
      ),
    ).toEqual({ kind: "none" });
  });
  it.each(["", "arbitrary"])("rejects invalid snapshot binding %s", (knowledge_base_id) => {
    expect(agent({ answer: "a", status: "answered", sources: [] }, { knowledge_base_id })).toEqual({
      kind: "unavailable",
    });
  });
  it.each(["running", "failed", "interrupted"] as const)(
    "does not interpret %s as empty",
    (status) => {
      expect(knowledgeRunResult("wf", "r3", run(), { ...step(null), status })).toEqual({
        kind: "none",
      });
    },
  );
  it.each([
    undefined,
    { ...run(), id: "r4" },
    { ...run(), workflow_id: "other" },
    { ...run(), definition_snapshot: null },
    { ...run(), definition_snapshot: { nodes: [] } },
    { ...run(), definition_snapshot: { nodes: [{ id: "node", kind: "agent" }] } },
    {
      ...run(),
      definition_snapshot: {
        nodes: [run().definition_snapshot.nodes[0], run().definition_snapshot.nodes[0]],
      },
    },
  ])("rejects unavailable/inconsistent snapshot %#", (value) => {
    expect(knowledgeRunResult("wf", "r3", value as WorkflowRunRead, step())).toEqual({
      kind: "unavailable",
    });
  });
  it.each([{ run_id: "r4" }, { node_id: "other" }, { node_kind: "agent" }])(
    "rejects mismatched step %#",
    (patch) => {
      expect(knowledgeRunResult("wf", "r3", run(), { ...step(), ...patch } as RunStepRead)).toEqual(
        { kind: "unavailable" },
      );
    },
  );
  it("does not deduplicate repeated node attempts", () => {
    const steps = [step(), { ...step(), id: "retry", sequence: 2 }];
    expect(steps.map((value) => knowledgeRunResult("wf", "r3", run(), value).kind)).toEqual([
      "retrieval",
      "retrieval",
    ]);
  });
  it("bounds text by Unicode code points without splitting emoji", () => {
    expect(executionText("😀".repeat(10_001))).toEqual({
      preview: "😀".repeat(10_000),
      truncated: true,
    });
    expect(executionText("😀".repeat(10_000)).truncated).toBe(false);
  });
});

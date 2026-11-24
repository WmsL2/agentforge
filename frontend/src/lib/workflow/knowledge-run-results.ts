import type { RunStepRead, WorkflowRunRead } from "@/types";
import { isKnowledgeUuid } from "./knowledge-config";

export interface ExecutionSource {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_start: number | null;
  page_end: number | null;
  similarity_score: number;
}
export interface ExecutionMatch extends ExecutionSource {
  content: string;
}
export type KnowledgeRunResult =
  | { kind: "none" }
  | { kind: "unavailable" }
  | { kind: "invalid" }
  | { kind: "retrieval"; query: string; total: number; results: ExecutionMatch[] }
  | {
      kind: "agent";
      answer: string;
      status: "answered" | "no_evidence";
      sources: ExecutionSource[];
    };

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const page = (value: unknown) => value === null || Number.isSafeInteger(value);
function source(value: unknown): value is ExecutionSource {
  return (
    object(value) &&
    typeof value.chunk_id === "string" &&
    typeof value.document_id === "string" &&
    typeof value.filename === "string" &&
    page(value.page_start) &&
    page(value.page_end) &&
    typeof value.similarity_score === "number" &&
    Number.isFinite(value.similarity_score)
  );
}

/** Interpret one persisted step against its own run snapshot only; never the live canvas or trace. */
export function knowledgeRunResult(
  workflowId: string,
  runId: string,
  run: WorkflowRunRead | undefined,
  step: RunStepRead,
): KnowledgeRunResult {
  if (step.status !== "completed") return { kind: "none" };
  if (step.node_kind !== "knowledge" && step.node_kind !== "agent") return { kind: "none" };
  if (
    !run ||
    run.id !== runId ||
    run.workflow_id !== workflowId ||
    step.run_id !== runId ||
    typeof step.node_id !== "string" ||
    !step.node_id
  )
    return { kind: "unavailable" };
  const snapshot: unknown = run.definition_snapshot;
  if (!object(snapshot) || !Array.isArray(snapshot.nodes)) return { kind: "unavailable" };
  const nodes = snapshot.nodes.filter((node: unknown) => object(node) && node.id === step.node_id);
  if (nodes.length !== 1 || !object(nodes[0]) || nodes[0].kind !== step.node_kind)
    return { kind: "unavailable" };
  const node = nodes[0];
  if (step.node_kind === "agent") {
    if (!object(node.config)) return { kind: "unavailable" };
    if (!("knowledge_base_id" in node.config)) return { kind: "none" };
    if (
      typeof node.config.knowledge_base_id !== "string" ||
      !isKnowledgeUuid(node.config.knowledge_base_id)
    )
      return { kind: "unavailable" };
  }
  const output = step.output;
  if (!object(output)) return { kind: "invalid" };
  if (step.node_kind === "knowledge") {
    if (
      typeof output.query !== "string" ||
      !Number.isSafeInteger(output.total) ||
      Number(output.total) < 0 ||
      !Array.isArray(output.results) ||
      !output.results.every(
        (item: unknown) => source(item) && object(item) && typeof item.content === "string",
      )
    )
      return { kind: "invalid" };
    return {
      kind: "retrieval",
      query: output.query,
      total: Number(output.total),
      results: output.results as ExecutionMatch[],
    };
  }
  if (
    typeof output.answer !== "string" ||
    (output.status !== "answered" && output.status !== "no_evidence") ||
    !Array.isArray(output.sources) ||
    !output.sources.every(source) ||
    (output.status === "no_evidence" && output.sources.length !== 0)
  )
    return { kind: "invalid" };
  return { kind: "agent", answer: output.answer, status: output.status, sources: output.sources };
}

export const EXECUTION_TEXT_LIMIT = 10_000;
export function executionText(text: string) {
  const preview = Array.from(text.slice(0, EXECUTION_TEXT_LIMIT * 2))
    .slice(0, EXECUTION_TEXT_LIMIT)
    .join("");
  return { preview, truncated: preview.length < text.length };
}

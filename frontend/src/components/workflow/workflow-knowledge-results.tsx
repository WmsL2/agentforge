"use client";

import { useTranslations } from "next-intl";
import {
  executionText,
  knowledgeRunResult,
  type ExecutionSource,
} from "@/lib/workflow/knowledge-run-results";
import type { RunStepRead, WorkflowRunRead } from "@/types";

function BoundedText({ text }: { text: string }) {
  const t = useTranslations("workflows.execution.knowledgeResults");
  const { preview, truncated } = executionText(text);
  return (
    <div>
      {truncated && <p className="text-sm">{t("truncated", { count: 10_000 })}</p>}
      <pre className="max-h-80 overflow-auto rounded border p-3 text-sm break-words whitespace-pre-wrap">
        {preview}
      </pre>
    </div>
  );
}
function Source({ item }: { item: ExecutionSource }) {
  const t = useTranslations("workflows.execution.knowledgeResults");
  return (
    <dl className="grid gap-2 text-sm sm:grid-cols-2">
      {(
        [
          "filename",
          "chunk_id",
          "document_id",
          "page_start",
          "page_end",
          "similarity_score",
        ] as const
      ).map((key) => (
        <div key={key}>
          <dt className="font-medium">{t(key)}</dt>
          <dd>
            <BoundedText text={String(item[key] ?? "—")} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function WorkflowKnowledgeResults({
  workflowId,
  runId,
  run,
  step,
  ready,
}: {
  workflowId: string;
  runId: string;
  run: WorkflowRunRead | undefined;
  step: RunStepRead;
  ready: boolean;
}) {
  const t = useTranslations("workflows.execution.knowledgeResults");
  const result = knowledgeRunResult(workflowId, runId, run, step);
  if (result.kind === "none") return null;
  if (!ready || result.kind === "unavailable") return <p role="status">{t("unavailable")}</p>;
  if (result.kind === "invalid") return <p role="status">{t("invalid")}</p>;
  return (
    <section
      className="mt-3 space-y-3 rounded border p-3"
      aria-label={t(result.kind === "retrieval" ? "retrieval" : "agent")}
    >
      <h4 className="font-semibold">{t(result.kind === "retrieval" ? "retrieval" : "agent")}</h4>
      {result.kind === "retrieval" ? (
        <>
          <p className="font-medium">{t("query")}</p>
          <BoundedText text={result.query} />
          <p>
            {t("total")}: {result.total} · {t("results")}: {result.results.length}
          </p>
          {result.results.length === 0 && <p>{t("empty")}</p>}
          <ol className="space-y-3">
            {result.results.map((item, index) => (
              <li key={index} className="space-y-2 rounded border p-3">
                <Source item={item} />
                <p className="font-medium">{t("content")}</p>
                <BoundedText text={item.content} />
              </li>
            ))}
          </ol>
        </>
      ) : (
        <>
          {result.status === "no_evidence" ? (
            <p>{t("noEvidence")}</p>
          ) : (
            <BoundedText text={result.answer} />
          )}
          <h5 className="font-medium">{t("sources")}</h5>
          {result.status === "answered" && result.sources.length === 0 && <p>{t("noSources")}</p>}
          <ol className="space-y-3">
            {result.sources.map((item, index) => (
              <li key={index} className="rounded border p-3">
                <Source item={item} />
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="text-muted-foreground text-xs">{t("similarityHelp")}</p>
    </section>
  );
}

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, Copy, Play, RefreshCw } from "lucide-react";

import {
  usePendingWorkflowApproval,
  useWorkflowRun,
  useWorkflowRunMutations,
  useWorkflowRuns,
  useWorkflowRunSteps,
  useWorkspaceMembers,
  useWorkflowTrace,
} from "@/hooks";
import { ApiError, getApiErrorMessage } from "@/lib/api-client";
import { isJsonObject, parseSafeJson } from "@/lib/json-value";
import type { WorkflowEditorState } from "./workflow-canvas-editor";
import type { JsonObject, WorkflowRead, WorkflowRunRead } from "@/types";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  FormField,
  Textarea,
} from "@/components/ui";

const PAGE_SIZE = 10;
const MAX_JSON_DISPLAY = 20_000;

export interface WorkflowExecutionPanelProps {
  workflow: WorkflowRead;
  userId: string;
  editorState: WorkflowEditorState;
}

interface ErrorEnvelope {
  error?: { code?: unknown; message?: unknown; details?: Record<string, unknown> | null };
}

function errorEnvelope(error: unknown): ErrorEnvelope["error"] | null {
  if (!(error instanceof ApiError) || !error.data || typeof error.data !== "object") return null;
  const envelope = error.data as ErrorEnvelope;
  return envelope.error && typeof envelope.error === "object" ? envelope.error : null;
}

function dispatchRunId(error: unknown): string | null {
  const backend = errorEnvelope(error);
  if (backend?.code !== "WORKFLOW_DISPATCH_FAILED") return null;
  const runId = backend.details?.run_id;
  return typeof runId === "string" && runId.trim() ? runId : null;
}

function structuredIssues(error: unknown): string[] {
  const issues = errorEnvelope(error)?.details?.issues;
  if (!Array.isArray(issues)) return [];
  return issues.map((issue) => {
    if (!issue || typeof issue !== "object") return String(issue);
    const record = issue as Record<string, unknown>;
    return [
      record.message,
      record.node_id && `node: ${record.node_id}`,
      record.edge_id && `edge: ${record.edge_id}`,
    ]
      .filter(Boolean)
      .join(" · ");
  });
}

function displayError(
  error: unknown,
  fallback: string,
  forbidden: string,
  notFound: string,
): string {
  if (error instanceof ApiError && error.status === 403) return forbidden;
  if (error instanceof ApiError && error.status === 404) return notFound;
  return error instanceof ApiError
    ? getApiErrorMessage(error.data, error.message || fallback)
    : error instanceof Error
      ? error.message
      : fallback;
}

function timestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function JsonView({
  label,
  value,
  copyLabel,
}: {
  label: string;
  value: unknown;
  copyLabel: string;
}) {
  const full = JSON.stringify(value, null, 2) ?? "null";
  const truncated = full.length > MAX_JSON_DISPLAY;
  const shown = truncated ? `${full.slice(0, MAX_JSON_DISPLAY)}\n…` : full;
  return (
    <details className="rounded-lg border" open={!truncated}>
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{label}</summary>
      <div className="space-y-2 border-t p-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void navigator.clipboard?.writeText(full)}
        >
          <Copy className="h-4 w-4" />
          {copyLabel}
        </Button>
        <pre className="bg-muted/40 max-h-96 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
          {shown}
        </pre>
      </div>
    </details>
  );
}

export function WorkflowExecutionPanel({
  workflow,
  userId,
  editorState,
}: WorkflowExecutionPanelProps) {
  const t = useTranslations("workflows.execution");
  const [inputText, setInputText] = useState("{}");
  const [page, setPage] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitIssues, setSubmitIssues] = useState<string[]>([]);
  const [dispatchWarning, setDispatchWarning] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const submissionLock = useRef(false);
  const approvalLock = useRef(false);

  useEffect(() => {
    setInputText("{}");
    setPage(0);
    setSelectedRunId(undefined);
    setSubmitError(null);
    setSubmitIssues([]);
    setDispatchWarning(null);
    setNote("");
    setActionMessage(null);
    submissionLock.current = false;
    approvalLock.current = false;
  }, [workflow.id]);

  const members = useWorkspaceMembers(userId, workflow.workspace_id);
  const membership = members.data?.find((member) => member.user_id === userId);
  const canRun = members.isSuccess && Boolean(membership);
  const canDecide = membership?.role === "owner" || membership?.role === "admin";
  const history = useWorkflowRuns(userId, workflow.id, page * PAGE_SIZE, PAGE_SIZE);
  const run = useWorkflowRun(userId, workflow.id, selectedRunId);
  const selectedStatus = run.data?.status;
  const steps = useWorkflowRunSteps(userId, workflow.id, selectedRunId, selectedStatus);
  const trace = useWorkflowTrace(userId, workflow.id, selectedRunId, selectedStatus);
  const approval = usePendingWorkflowApproval(
    userId,
    workflow.id,
    selectedRunId,
    Boolean(canDecide && selectedStatus === "paused"),
  );
  const mutations = useWorkflowRunMutations(userId, workflow.id);

  const inputResult = useMemo(() => parseSafeJson(inputText), [inputText]);
  const inputProblem = inputResult.ok
    ? isJsonObject(inputResult.value)
      ? null
      : "object"
    : inputResult.problem;
  const inputError = inputProblem ? t(`inputErrors.${inputProblem}`) : null;

  const runBlockReason = members.isLoading
    ? t("checkingPermission")
    : members.isError || !canRun
      ? t("runForbidden")
      : editorState.hasUnsavedChanges
        ? t("blockedUnsaved")
        : editorState.operation !== "idle"
          ? t("blockedBusy")
          : editorState.hasRevisionConflict
            ? t("blockedRevision")
            : null;

  const submit = async () => {
    if (submissionLock.current || mutations.submit.isPending || runBlockReason || inputProblem)
      return;
    if (!inputResult.ok || !isJsonObject(inputResult.value)) return;
    submissionLock.current = true;
    setSubmitError(null);
    setSubmitIssues([]);
    setDispatchWarning(null);
    try {
      const created = await mutations.submit.mutateAsync(inputResult.value as JsonObject);
      if (created.workflow_id !== workflow.id) {
        setSubmitError(t("workflowMismatch"));
        return;
      }
      setSelectedRunId(created.id);
      setActionMessage(t("submitted", { revision: created.workflow_revision }));
    } catch (error) {
      const recoveredRunId = dispatchRunId(error);
      if (recoveredRunId) {
        setSelectedRunId(recoveredRunId);
        setDispatchWarning(t("dispatchUnconfirmed", { runId: recoveredRunId }));
        await mutations.refreshRun(recoveredRunId);
      } else {
        setSubmitIssues(structuredIssues(error));
        setSubmitError(
          displayError(error, t("submitFailed"), t("forbidden"), t("workflowNotFound")),
        );
      }
    } finally {
      submissionLock.current = false;
    }
  };

  const refreshSelected = async () => {
    if (!selectedRunId) return;
    await Promise.all([run.refetch(), steps.refetch(), trace.refetch(), history.refetch()]);
    if (canDecide && selectedStatus === "paused") await approval.refetch();
  };

  const decide = async (kind: "approve" | "reject") => {
    if (!approval.data || approvalLock.current || note.length > 2000) return;
    if (!window.confirm(kind === "approve" ? t("confirmApprove") : t("confirmReject"))) return;
    approvalLock.current = true;
    setActionMessage(null);
    try {
      await mutations.decide(kind, selectedRunId!, approval.data.id, note.trim() || null);
      setActionMessage(kind === "approve" ? t("approvalAccepted") : t("rejectionAccepted"));
      setNote("");
    } catch (error) {
      const recoveredRunId = dispatchRunId(error);
      if (recoveredRunId) {
        setDispatchWarning(t("approvalDispatchUnconfirmed", { runId: recoveredRunId }));
        await mutations.refreshRun(recoveredRunId);
      } else {
        setActionMessage(
          displayError(error, t("approvalFailed"), t("forbidden"), t("approvalNotFound")),
        );
        if (error instanceof ApiError && error.status === 409)
          await mutations.refreshRun(selectedRunId!);
      }
    } finally {
      approvalLock.current = false;
    }
  };

  const selectedMismatch = run.data && run.data.workflow_id !== workflow.id;
  const approvalPending = mutations.approve.isPending || mutations.reject.isPending;

  return (
    <section className="space-y-4" aria-label={t("title")}>
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            {t("savedRevision", { revision: workflow.revision })}
          </p>
          <FormField label={t("inputLabel")} htmlFor="workflow-run-input" error={inputError}>
            <Textarea
              value={inputText}
              rows={7}
              onChange={(event) => setInputText(event.target.value)}
            />
          </FormField>
          {runBlockReason && (
            <p className="text-sm text-amber-700 dark:text-amber-300">{runBlockReason}</p>
          )}
          <Button
            type="button"
            disabled={Boolean(inputError || runBlockReason || mutations.submit.isPending)}
            onClick={() => void submit()}
          >
            <Play className="h-4 w-4" />
            {mutations.submit.isPending ? t("submitting") : t("run")}
          </Button>
          {submitError && (
            <p role="alert" className="text-destructive text-sm">
              {submitError}
            </p>
          )}
          {submitIssues.length > 0 && (
            <ul className="text-destructive list-disc pl-5 text-sm">
              {submitIssues.map((issue, index) => (
                <li key={`${issue}-${index}`}>{issue}</li>
              ))}
            </ul>
          )}
          {dispatchWarning && (
            <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">
              <AlertTriangle className="mr-1 inline h-4 w-4" />
              {dispatchWarning}
            </p>
          )}
          {actionMessage && (
            <p role="status" className="text-sm">
              <CheckCircle2 className="mr-1 inline h-4 w-4" />
              {actionMessage}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("historyTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {history.isLoading && <p>{t("loadingHistory")}</p>}
          {history.isError && (
            <div role="alert">
              <p>
                {displayError(
                  history.error,
                  t("historyFailed"),
                  t("forbidden"),
                  t("workflowNotFound"),
                )}
              </p>
              <Button type="button" variant="outline" onClick={() => void history.refetch()}>
                {t("retry")}
              </Button>
            </div>
          )}
          {history.data?.items.length === 0 && (
            <p className="text-muted-foreground">{t("historyEmpty")}</p>
          )}
          <div className="space-y-2">
            {history.data?.items.map((item) =>
              item.workflow_id !== workflow.id ? (
                <p role="alert" className="text-destructive text-sm" key={item.id}>
                  {t("workflowMismatch")}
                </p>
              ) : (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={selectedRunId === item.id}
                  className="hover:bg-muted/50 w-full rounded-lg border p-3 text-left"
                  onClick={() => {
                    setSelectedRunId(item.id);
                    setActionMessage(null);
                    setDispatchWarning(null);
                  }}
                >
                  <span className="font-mono text-xs">{item.id}</span>
                  <span className="mt-1 grid gap-1 text-sm sm:grid-cols-3">
                    <span>
                      {t("status")}: {item.status}
                    </span>
                    <span>
                      {t("revision")}: r{item.workflow_revision}
                    </span>
                    <span>
                      {t("created")}: {timestamp(item.created_at)}
                    </span>
                  </span>
                  <span className="text-muted-foreground mt-1 block text-xs">
                    {t("started")}: {timestamp(item.started_at)} · {t("finished")}:{" "}
                    {timestamp(item.finished_at)}
                  </span>
                  {item.error && (
                    <span className="text-destructive mt-1 block text-xs">
                      {item.error.code}: {item.error.message}
                    </span>
                  )}
                </button>
              ),
            )}
          </div>
          <div className="flex items-center justify-between">
            <Button
              type="button"
              variant="outline"
              disabled={page === 0}
              onClick={() => setPage((value) => value - 1)}
            >
              {t("previous")}
            </Button>
            <span className="text-sm">{t("page", { page: page + 1 })}</span>
            <Button
              type="button"
              variant="outline"
              disabled={!history.data || (page + 1) * PAGE_SIZE >= history.data.total}
              onClick={() => setPage((value) => value + 1)}
            >
              {t("next")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {selectedRunId && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>{t("detailsTitle")}</CardTitle>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void refreshSelected()}
              >
                <RefreshCw className="h-4 w-4" />
                {t("refresh")}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {run.isLoading && <p>{t("loadingRun")}</p>}
            {run.isError && (
              <p role="alert" className="text-destructive">
                {displayError(run.error, t("runLoadFailed"), t("forbidden"), t("runNotFound"))}
              </p>
            )}
            {selectedMismatch && (
              <p role="alert" className="text-destructive">
                {t("workflowMismatch")}
              </p>
            )}
            {run.data && !selectedMismatch && <RunDetails run={run.data} copyLabel={t("copy")} />}

            <div>
              <h3 className="mb-2 font-semibold">{t("stepsTitle")}</h3>
              {steps.isLoading && <p>{t("loadingSteps")}</p>}
              {steps.isError && (
                <p role="alert" className="text-destructive">
                  {t("stepsFailed")}
                </p>
              )}
              {steps.data?.length === 0 && (
                <p className="text-muted-foreground">{t("stepsEmpty")}</p>
              )}
              <div className="space-y-2">
                {steps.data?.map((step) => (
                  <div className="rounded-lg border p-3" key={step.id}>
                    <p className="font-medium">
                      #{step.sequence} · {step.node_id} · {step.node_kind} · {step.status}
                    </p>
                    <p className="text-muted-foreground text-xs">
                      {timestamp(step.started_at)} → {timestamp(step.finished_at)} ·{" "}
                      {step.duration_ms === null ? "—" : `${step.duration_ms} ms`}
                    </p>
                    {step.error && (
                      <p className="text-destructive text-sm">
                        {step.error.code}: {step.error.message}
                      </p>
                    )}
                    <div className="mt-2 grid gap-2 lg:grid-cols-2">
                      <JsonView label={t("input")} value={step.input} copyLabel={t("copy")} />
                      <JsonView label={t("output")} value={step.output} copyLabel={t("copy")} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h3 className="mb-2 font-semibold">{t("traceTitle")}</h3>
              {trace.isLoading && <p>{t("loadingTrace")}</p>}
              {trace.isError && (
                <p role="alert" className="text-destructive">
                  {t("traceFailed")}
                </p>
              )}
              {trace.data?.length === 0 && (
                <p className="text-muted-foreground">{t("traceEmpty")}</p>
              )}
              <div className="space-y-2">
                {trace.data?.map((event) => (
                  <div className="rounded-lg border p-3" key={event.id}>
                    <p className="font-medium">{event.kind}</p>
                    <p className="text-muted-foreground text-xs">
                      {timestamp(event.created_at)} · {t("stepId")}: {event.step_id ?? "—"}
                    </p>
                    <JsonView label={t("payload")} value={event.payload} copyLabel={t("copy")} />
                  </div>
                ))}
              </div>
            </div>

            {selectedStatus === "paused" && (
              <div className="space-y-3 rounded-lg border p-4">
                <h3 className="font-semibold">{t("approvalTitle")}</h3>
                {members.isLoading && <p>{t("checkingPermission")}</p>}
                {!members.isLoading && !canDecide && <p>{t("approvalForbidden")}</p>}
                {canDecide && approval.isLoading && <p>{t("loadingApproval")}</p>}
                {canDecide && approval.isError && (
                  <p
                    role={
                      approval.error instanceof ApiError && approval.error.status === 404
                        ? undefined
                        : "alert"
                    }
                  >
                    {approval.error instanceof ApiError && approval.error.status === 404
                      ? t("approvalEmpty")
                      : displayError(
                          approval.error,
                          t("approvalLoadFailed"),
                          t("forbidden"),
                          t("approvalEmpty"),
                        )}
                  </p>
                )}
                {approval.data && (
                  <>
                    <p>{approval.data.prompt}</p>
                    <FormField
                      label={t("note")}
                      htmlFor="approval-note"
                      description={t("noteCount", { count: note.length })}
                      error={note.length > 2000 ? t("noteTooLong") : null}
                    >
                      <Textarea
                        value={note}
                        maxLength={2001}
                        rows={4}
                        disabled={approvalPending}
                        onChange={(event) => setNote(event.target.value)}
                      />
                    </FormField>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        disabled={approvalPending || note.length > 2000}
                        onClick={() => void decide("approve")}
                      >
                        {t("approve")}
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        disabled={approvalPending || note.length > 2000}
                        onClick={() => void decide("reject")}
                      >
                        {t("reject")}
                      </Button>
                    </div>
                  </>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  );
}

function RunDetails({ run, copyLabel }: { run: WorkflowRunRead; copyLabel: string }) {
  const t = useTranslations("workflows.execution");
  return (
    <div className="space-y-3">
      <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <p>
          <strong>{t("runId")}:</strong> <span className="font-mono">{run.id}</span>
        </p>
        <p>
          <strong>{t("workflowId")}:</strong> <span className="font-mono">{run.workflow_id}</span>
        </p>
        <p>
          <strong>{t("revision")}:</strong> r{run.workflow_revision}
        </p>
        <p>
          <strong>{t("status")}:</strong> {run.status}
        </p>
        <p>
          <strong>{t("started")}:</strong> {timestamp(run.started_at)}
        </p>
        <p>
          <strong>{t("finished")}:</strong> {timestamp(run.finished_at)}
        </p>
      </div>
      {run.error && (
        <p className="text-destructive">
          {run.error.code}: {run.error.message}
          {run.error.node_id ? ` · ${run.error.node_id}` : ""}
        </p>
      )}
      <div className="grid gap-2 lg:grid-cols-2">
        <JsonView label={t("input")} value={run.input} copyLabel={copyLabel} />
        <JsonView label={t("output")} value={run.output} copyLabel={copyLabel} />
        <JsonView
          label={t("definitionSnapshot")}
          value={run.definition_snapshot}
          copyLabel={copyLabel}
        />
        <JsonView label={t("nodeOutputs")} value={run.node_outputs} copyLabel={copyLabel} />
      </div>
    </div>
  );
}

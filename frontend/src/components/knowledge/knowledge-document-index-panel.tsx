"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Badge } from "@/components/ui";
import { LoadingState } from "@/components/states";
import { useKnowledgeIndexStatus, useKnowledgeIndexMutation } from "@/hooks/use-knowledge";
import { ApiError } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { clearKnowledgeScope, onKnowledgeClear, within } from "@/lib/knowledge/knowledge-lifecycle";
import type {
  KnowledgeDocumentRead,
  KnowledgeIndexJobRead,
  KnowledgeIndexStatusRead,
} from "@/types";
import type { DocumentScope } from "./knowledge-document-management";
import { documentMatches } from "./knowledge-document-utils";
import { isAbort, useKnowledgeLease } from "./knowledge-ui";
import {
  INDEX_CONFIRM_MS,
  INDEX_STATES,
  INDEX_CODES,
  indexError,
  indexReason,
} from "./knowledge-index-utils";

export function KnowledgeDocumentIndexPanel({
  document,
  onFailure,
  ...scope
}: DocumentScope & { document: KnowledgeDocumentRead; onFailure: (error: unknown) => void }) {
  const { userId, workspaceId, knowledgeBaseId, canWrite, revalidateWrite } = scope;
  const t = useTranslations("knowledgeManagement"),
    capture = useKnowledgeLease(),
    client = useQueryClient();
  const live = useRef(true),
    resourceLive = useRef(true),
    busy = useRef(false),
    callbacks = useRef(onFailure);
  callbacks.current = onFailure;
  const [invalid, setInvalid] = useState(false),
    [submitting, setSubmitting] = useState(false),
    [confirm, setConfirm] = useState(false),
    [error, setError] = useState<string>();
  const [accepted, setAccepted] = useState<{ job: KnowledgeIndexJobRead; until: number }>();
  const key = useMemo(
    () => qk.knowledge.index(userId, workspaceId, knowledgeBaseId, document.id),
    [userId, workspaceId, knowledgeBaseId, document.id],
  );
  const matches = documentMatches(document, workspaceId, knowledgeBaseId);
  const validScope = !invalid && matches;
  const query = useKnowledgeIndexStatus(
    validScope ? userId : undefined,
    validScope ? workspaceId : undefined,
    validScope ? knowledgeBaseId : undefined,
    validScope ? document.id : undefined,
    {
      pollActive: validScope,
      isCurrent: () => resourceLive.current,
      awaitJob: accepted ? { id: accepted.job.id, until: accepted.until } : undefined,
    },
  );
  const mutation = useKnowledgeIndexMutation(userId, workspaceId, knowledgeBaseId, document.id);
  const data = query.data;
  const validData = data?.document_id === document.id;
  const state = validData && INDEX_STATES.includes(data.status) ? data.status : "unknown";
  const awaiting = Boolean(accepted && (!validData || data.job_id !== accepted.job.id));
  const active = state === "pending" || state === "running";
  const writable =
    canWrite &&
    Boolean(revalidateWrite) &&
    document.parse_status === "ready" &&
    query.isSuccess &&
    !query.isFetching &&
    validData &&
    state !== "unknown" &&
    !active &&
    !awaiting &&
    !submitting &&
    validScope;
  const current = useRef(writable);
  current.current = writable;
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        if (within(key, prefix)) {
          live.current = false;
          resourceLive.current = false;
          setInvalid(true);
          setConfirm(false);
          setAccepted(undefined);
        }
      }),
    [key],
  );
  useEffect(() => {
    if (!canWrite && !busy.current) setConfirm(false);
  }, [canWrite]);
  const handleFailure = (failure: unknown) => {
    if (failure instanceof ApiError && [403, 404].includes(failure.status)) {
      live.current = false;
      resourceLive.current = false;
      setInvalid(true);
      setConfirm(false);
      callbacks.current(failure);
      if (failure.status === 404)
        clearKnowledgeScope(
          client,
          qk.knowledge.document(userId, workspaceId, knowledgeBaseId, document.id),
        );
    }
  };
  const failureHandler = useRef(handleFailure);
  failureHandler.current = handleFailure;
  useEffect(() => {
    if (query.isError && !isAbort(query.error) && capture()() && live.current)
      failureHandler.current(query.error);
  }, [query.isError, query.error, capture]);
  const submit = async () => {
    if (busy.current || !current.current || !live.current) return;
    const lease = capture(),
      valid = () => lease() && live.current;
    if (!valid()) return;
    busy.current = true;
    setSubmitting(true);
    setError(undefined);
    try {
      const allowed = await revalidateWrite!();
      if (!valid()) return;
      if (!allowed) {
        setConfirm(false);
        setError(t("errors.forbidden"));
        return;
      }
      // Read the current scoped snapshot again after permission I/O; never submit against an active or invalidated job.
      const latest = client.getQueryState<KnowledgeIndexStatusRead>(key);
      if (
        latest?.status !== "success" ||
        latest.fetchStatus !== "idle" ||
        latest.data?.document_id !== document.id ||
        !["not_indexed", "succeeded", "failed"].includes(latest.data.status)
      )
        return;
      const job = await mutation.mutateAsync();
      if (!valid()) return;
      if (
        job.document_id !== document.id ||
        !job.id ||
        !["pending", "running", "succeeded", "failed"].includes(job.status)
      ) {
        setError(t("scopeError"));
        return;
      }
      setAccepted({ job, until: Date.now() + INDEX_CONFIRM_MS });
      setConfirm(false);
      // The Hook already invalidates status on 202. Do not create a second POST or assume completion.
    } catch (failure) {
      if (!valid() || isAbort(failure)) return;
      setError(indexError(failure, t));
      handleFailure(failure);
    } finally {
      if (valid()) {
        busy.current = false;
        setSubmitting(false);
      }
    }
  };
  const refresh = async () => {
    if (!live.current || !validScope || submitting) return;
    const lease = capture();
    try {
      await query.refetch();
    } catch (failure) {
      if (lease() && live.current && !isAbort(failure)) setError(indexError(failure, t));
    }
  };
  if (invalid || !matches)
    return (
      <section aria-label={t("documents.index.title")}>
        <p role="alert">{t("scopeError")}</p>
      </section>
    );
  return (
    <section className="space-y-3 rounded border p-4" aria-label={t("documents.index.title")}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">{t("documents.index.title")}</h3>
        <Button
          variant="outline"
          onClick={() => void refresh()}
          disabled={query.isFetching || submitting}
        >
          {t("documents.index.refresh")}
        </Button>
      </div>
      {query.isPending ? (
        <LoadingState label={t("loading")} />
      ) : query.isError ? (
        <p role="alert">{indexError(query.error, t)}</p>
      ) : !validData ? (
        <p role="alert">{t("scopeError")}</p>
      ) : (
        <>
          <dl className="grid gap-2 sm:grid-cols-2">
            {[
              [t("documents.index.documentId"), data.document_id],
              [t("documents.index.jobId"), data.job_id ?? "—"],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="flex items-center gap-2">
            {t("documents.index.latest")}: <Badge>{t(`documents.index.states.${state}`)}</Badge>
            {active && (
              <span className="ml-2 inline-block animate-pulse" aria-hidden>
                …
              </span>
            )}
          </div>
          {data.active_generation_id ? (
            <div className="space-y-2">
              <p>{t("documents.index.hasActive")}</p>
              <dl>
                {[
                  [t("documents.index.generation"), data.active_generation_id],
                  [t("documents.index.chunks"), String(data.chunk_count)],
                  [t("documents.index.model"), data.embedding_model ?? "—"],
                  [t("documents.index.version"), data.index_version ?? "—"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd className="break-all">{value}</dd>
                  </div>
                ))}
              </dl>
              {state === "failed" && <p>{t("documents.index.oldActive")}</p>}
            </div>
          ) : (
            <div>
              <p>{t("documents.index.noActive")}</p>
              <p>
                {t("documents.index.chunks")}: {data.chunk_count}
              </p>
              <p>
                {t("documents.index.model")}: {data.embedding_model ?? "—"}
              </p>
              <p>
                {t("documents.index.version")}: {data.index_version ?? "—"}
              </p>
            </div>
          )}
          {data.error_code && (
            <div>
              <p>{indexReason(data.error_code, t)}</p>
              {INDEX_CODES.includes(data.error_code as (typeof INDEX_CODES)[number]) && (
                <p>
                  {t("documents.index.errorCode")}: {data.error_code}
                </p>
              )}
            </div>
          )}
        </>
      )}
      {document.parse_status !== "ready" && <p>{t("documents.index.notReady")}</p>}
      {accepted && (
        <div role="status">
          <p>{t("documents.index.accepted", { id: accepted.job.id })}</p>
          <p>
            {t("documents.index.acceptedState")}:{" "}
            {t(`documents.index.states.${accepted.job.status}`)}
          </p>
          {awaiting && (
            <p>
              {t(
                Date.now() < accepted.until
                  ? "documents.index.confirming"
                  : "documents.index.unconfirmed",
              )}
            </p>
          )}
        </div>
      )}
      {submitting && <p role="status">{t("documents.index.submitting")}</p>}
      {error && <p role="alert">{error}</p>}
      {writable && !confirm && (
        <Button onClick={() => (state === "succeeded" ? setConfirm(true) : void submit())}>
          {t(
            `documents.index.${state === "succeeded" ? "rebuild" : state === "failed" ? "retry" : "build"}`,
          )}
        </Button>
      )}
      {confirm && canWrite && (
        <div role="group" aria-label={t("documents.index.confirmTitle")}>
          <p>{t("documents.index.confirmWarning")}</p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={submitting} onClick={() => setConfirm(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={!writable} onClick={() => void submit()}>
              {t("documents.index.confirm")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

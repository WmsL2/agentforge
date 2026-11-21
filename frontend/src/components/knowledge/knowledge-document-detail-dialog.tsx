"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui";
import { LoadingState, ErrorState } from "@/components/states";
import {
  useKnowledgeDocument,
  useKnowledgeDocumentContent,
  useKnowledgeDocumentMutations,
} from "@/hooks/use-knowledge";
import { ApiError } from "@/lib/api-client";
import { onKnowledgeClear, within } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import { isAbort, knowledgeDate, useKnowledgeLease } from "./knowledge-ui";
import {
  documentError,
  documentMatches,
  parseReason,
  PREVIEW_CHAR_LIMIT,
  saveDocument,
} from "./knowledge-document-utils";
import { KnowledgeDocumentIndexPanel } from "./knowledge-document-index-panel";
import type { DocumentScope } from "./knowledge-document-management";

export function KnowledgeDocumentDetailDialog({
  documentId,
  onClose,
  ...scope
}: DocumentScope & { documentId: string; onClose: () => void }) {
  const t = useTranslations("knowledgeManagement"),
    locale = useLocale(),
    capture = useKnowledgeLease();
  const client = useQueryClient(),
    live = useRef(true),
    downloadSequence = useRef(0);
  const [terminalError, setTerminalError] = useState<unknown>();
  const [preview, setPreview] = useState(false),
    [error, setError] = useState<string>(),
    [invalid, setInvalid] = useState(false);
  const query = useKnowledgeDocument(
    invalid ? undefined : scope.userId,
    invalid ? undefined : scope.workspaceId,
    invalid ? undefined : scope.knowledgeBaseId,
    invalid ? undefined : documentId,
  );
  const mutations = useKnowledgeDocumentMutations(
    scope.userId,
    scope.workspaceId,
    scope.knowledgeBaseId,
  );
  const data = query.data;
  const { revalidate, checkBase } = scope;
  const verified =
    !invalid &&
    query.isSuccess &&
    !query.isFetching &&
    data &&
    documentMatches(data, scope.workspaceId, scope.knowledgeBaseId, documentId);
  const key = useMemo(
    () => qk.knowledge.document(scope.userId, scope.workspaceId, scope.knowledgeBaseId, documentId),
    [scope.userId, scope.workspaceId, scope.knowledgeBaseId, documentId],
  );
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        if (within(key, prefix)) {
          live.current = false;
          downloadSequence.current++;
          setInvalid(true);
          setPreview(false);
        }
      }),
    [key],
  );
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const handleFailure = useCallback(
    (failure: unknown) => {
      if (failure instanceof ApiError && failure.status === 403) {
        live.current = false;
        setTerminalError(failure);
        setInvalid(true);
        setPreview(false);
        void revalidate();
      }
      if (failure instanceof ApiError && failure.status === 404) {
        live.current = false;
        setTerminalError(failure);
        setInvalid(true);
        setPreview(false);
        void checkBase();
      }
    },
    [revalidate, checkBase],
  );
  useEffect(() => {
    if (query.isError) handleFailure(query.error);
  }, [query.isError, query.error, handleFailure]);
  const download = async () => {
    if (!verified || !live.current) return;
    const valid = capture(),
      seq = ++downloadSequence.current;
    setError(undefined);
    try {
      const result = await mutations.download.mutateAsync(documentId);
      const current = client.getQueryState<typeof data>(key);
      if (
        valid() &&
        live.current &&
        seq === downloadSequence.current &&
        current?.status === "success" &&
        current.fetchStatus === "idle" &&
        current.data &&
        documentMatches(current.data, scope.workspaceId, scope.knowledgeBaseId, documentId)
      )
        saveDocument(result.blob, current.data.filename);
    } catch (failure) {
      if (!valid() || !live.current || seq !== downloadSequence.current || isAbort(failure)) return;
      setError(documentError(failure, t));
      handleFailure(failure);
    }
  };
  const closePreview = () => {
    void client.cancelQueries({
      queryKey: qk.knowledge.content(
        scope.userId,
        scope.workspaceId,
        scope.knowledgeBaseId,
        documentId,
      ),
      exact: true,
    });
    setPreview(false);
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("documents.detail")}</DialogTitle>
          <DialogDescription>{t("documents.detailHelp")}</DialogDescription>
        </DialogHeader>
        {terminalError ? (
          <ErrorState
            title={t("documents.detailError")}
            description={documentError(terminalError, t)}
          />
        ) : query.isPending || query.isFetching ? (
          <LoadingState label={t("loading")} />
        ) : query.isError ? (
          <ErrorState
            title={t("documents.detailError")}
            description={documentError(query.error, t)}
            cta={{
              label: t("retry"),
              onClick: () => {
                const valid = capture();
                void scope.revalidate().then((allowed) => {
                  if (allowed && valid() && live.current) void query.refetch();
                });
              },
            }}
          />
        ) : !verified ? (
          <p role="alert">{t("scopeError")}</p>
        ) : (
          <>
            <dl className="grid gap-3 sm:grid-cols-2">
              {[
                [t("documents.filename"), data.filename],
                [t("id"), data.id],
                [t("documents.mime"), data.mime_type],
                [t("documents.size"), t("documents.bytes", { count: data.size_bytes })],
                [t("documents.sha256"), data.sha256],
                [
                  t("documents.status"),
                  t(
                    `documents.${data.parse_status === "ready" ? "ready" : data.parse_status === "failed" ? "failed" : "unknown"}`,
                  ),
                ],
                ...(data.parse_error_code
                  ? [[t("documents.parseError"), parseReason(data.parse_error_code, t)]]
                  : []),
                ...(data.page_count !== null
                  ? [[t("documents.pages"), String(data.page_count)]]
                  : []),
                [t("createdAt"), knowledgeDate(data.created_at, locale)],
                [t("updatedAt"), knowledgeDate(data.updated_at, locale)],
                // Only documented scalar parser metadata is exposed. Paths and arbitrary server fields are omitted.
                ...Object.entries(data.parse_metadata)
                  .filter(
                    ([key, value]) =>
                      ["paragraph_count", "table_count", "table_cell_count"].includes(key) &&
                      typeof value === "number" &&
                      Number.isFinite(value),
                  )
                  .map(([key, value]) => [t(`documents.${key}`), String(value)]),
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-muted-foreground text-sm">{label}</dt>
                  <dd className="break-all whitespace-pre-wrap">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void download()}>{t("documents.download")}</Button>
              {data.parse_status === "ready" && (
                <Button
                  variant="outline"
                  onClick={() => (preview ? closePreview() : setPreview(true))}
                >
                  {t(preview ? "documents.hidePreview" : "documents.preview")}
                </Button>
              )}
            </div>
            <KnowledgeDocumentIndexPanel
              key={`${scope.userId}/${scope.workspaceId}/${scope.knowledgeBaseId}/${documentId}`}
              {...scope}
              document={data}
              onFailure={handleFailure}
            />
            {preview && data.parse_status === "ready" && (
              <DocumentPreview
                key={documentId}
                {...scope}
                documentId={documentId}
                onFailure={handleFailure}
              />
            )}
          </>
        )}
        {error && <p role="alert">{error}</p>}
        <Button variant="outline" onClick={onClose}>
          {t("documents.close")}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
function DocumentPreview({
  documentId,
  onFailure,
  ...scope
}: DocumentScope & { documentId: string; onFailure: (error: unknown) => void }) {
  const t = useTranslations("knowledgeManagement");
  const query = useKnowledgeDocumentContent(
    scope.userId,
    scope.workspaceId,
    scope.knowledgeBaseId,
    documentId,
    true,
  );
  useEffect(() => {
    if (query.isError) onFailure(query.error);
  }, [query.isError, query.error, onFailure]);
  if (query.isPending || query.isFetching) return <LoadingState label={t("loading")} />;
  if (query.isError)
    return (
      <p role="alert">
        {query.error instanceof ApiError && query.error.status === 409
          ? t("documents.errors.DOCUMENT_CONTENT_UNAVAILABLE")
          : documentError(query.error, t)}
      </p>
    );
  if (query.data.document_id !== documentId) return <p role="alert">{t("scopeError")}</p>;
  return (
    <div>
      {query.data.content.length > PREVIEW_CHAR_LIMIT && (
        <p>{t("documents.truncated", { count: PREVIEW_CHAR_LIMIT })}</p>
      )}
      <pre className="max-h-80 overflow-auto rounded border p-3 break-words whitespace-pre-wrap">
        {query.data.content.slice(0, PREVIEW_CHAR_LIMIT)}
      </pre>
    </div>
  );
}

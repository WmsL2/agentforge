"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { FileText } from "lucide-react";
import {
  Button,
  Badge,
  DataTable,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  FormField,
  Input,
  type Column,
} from "@/components/ui";
import { EmptyState, LoadingState, ErrorState } from "@/components/states";
import { useKnowledgeDocuments, useKnowledgeDocumentMutations } from "@/hooks/use-knowledge";
import { ApiError } from "@/lib/api-client";
import { onKnowledgeClear, within } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import type { KnowledgeDocumentRead } from "@/types";
import { isAbort, knowledgeDate, useKnowledgeLease } from "./knowledge-ui";
import {
  DOCUMENT_PAGE_SIZE,
  documentError,
  documentMatches,
  parseReason,
  prepareDocument,
} from "./knowledge-document-utils";
import { KnowledgeDocumentDetailDialog } from "./knowledge-document-detail-dialog";

export interface DocumentScope {
  userId: string;
  workspaceId: string;
  knowledgeBaseId: string;
  canWrite: boolean;
  revalidate: () => Promise<boolean>;
  checkBase: () => Promise<void>;
}
type Selection =
  | { kind: "upload" }
  | { kind: "detail"; document: KnowledgeDocumentRead }
  | { kind: "delete"; document: KnowledgeDocumentRead };
export function KnowledgeDocumentManagement(props: DocumentScope) {
  const { userId, workspaceId, knowledgeBaseId, canWrite } = props;
  const t = useTranslations("knowledgeManagement"),
    locale = useLocale();
  const capture = useKnowledgeLease();
  const [page, setPage] = useState(0),
    [selection, setSelection] = useState<Selection | null>(null),
    [revoked, setRevoked] = useState(false);
  const selectionRef = useRef(selection);
  selectionRef.current = selection;
  const version = useRef(0);
  const scope = useMemo(
    () => qk.knowledge.base(userId, workspaceId, knowledgeBaseId),
    [userId, workspaceId, knowledgeBaseId],
  );
  const query = useKnowledgeDocuments(
    revoked ? undefined : userId,
    revoked ? undefined : workspaceId,
    revoked ? undefined : knowledgeBaseId,
    { skip: page * DOCUMENT_PAGE_SIZE, limit: DOCUMENT_PAGE_SIZE },
  );
  const writable = canWrite && !query.isError;
  const maxPage = Math.max(0, Math.ceil((query.data?.total ?? 0) / DOCUMENT_PAGE_SIZE) - 1);
  useEffect(() => {
    if (query.isSuccess && page > maxPage) setPage(maxPage);
  }, [query.isSuccess, page, maxPage]);
  useEffect(() => {
    if (!writable) setSelection((current) => (current?.kind === "detail" ? current : null));
  }, [writable]);
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        if (within(scope, prefix)) {
          version.current++;
          setRevoked(true);
          setSelection(null);
        } else {
          const selected = selectionRef.current;
          if (
            selected &&
            "document" in selected &&
            within(
              qk.knowledge.document(userId, workspaceId, knowledgeBaseId, selected.document.id),
              prefix,
            )
          ) {
            version.current++;
            setSelection(null);
            if (selected.kind === "delete")
              setPage((current) => Math.max(0, current - (query.data?.items.length === 1 ? 1 : 0)));
          }
        }
      }),
    [userId, workspaceId, knowledgeBaseId, query.data?.items.length, scope],
  ); // Scope is fixed by the parent's keyed mount.
  if (revoked) return <ErrorState title={t("scopeError")} description={t("errors.notFound")} />;
  const columns: Column<KnowledgeDocumentRead>[] = [
    {
      key: "name",
      header: t("documents.filename"),
      cell: (d) => (
        <Button
          variant="link"
          className="max-w-xs break-all whitespace-normal"
          onClick={() => setSelection({ kind: "detail", document: d })}
        >
          {d.filename}
        </Button>
      ),
    },
    {
      key: "mime",
      header: t("documents.mime"),
      cell: (d) => <span className="break-all">{d.mime_type}</span>,
      hideBelow: "md",
    },
    {
      key: "size",
      header: t("documents.size"),
      cell: (d) => t("documents.bytes", { count: d.size_bytes }),
    },
    {
      key: "status",
      header: t("documents.status"),
      cell: (d) => (
        <Badge>
          {t(
            `documents.${d.parse_status === "ready" ? "ready" : d.parse_status === "failed" ? "failed" : "unknown"}`,
          )}
        </Badge>
      ),
    },
    {
      key: "pages",
      header: t("documents.pages"),
      cell: (d) => d.page_count ?? "—",
      hideBelow: "sm",
    },
    {
      key: "date",
      header: t("createdAt"),
      cell: (d) => knowledgeDate(d.created_at, locale),
      hideBelow: "lg",
    },
    ...(writable
      ? [
          {
            key: "actions",
            header: t("actions"),
            cell: (d: KnowledgeDocumentRead) => (
              <Button
                variant="destructive"
                size="sm"
                aria-label={`${t("documents.delete")} ${d.filename}`}
                onClick={() => setSelection({ kind: "delete", document: d })}
              >
                {t("documents.delete")}
              </Button>
            ),
          },
        ]
      : []),
  ];
  return (
    <section className="space-y-4" aria-label={t("documents.title")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-xl font-semibold">{t("documents.title")}</h3>
        {writable && (
          <Button onClick={() => setSelection({ kind: "upload" })}>{t("documents.upload")}</Button>
        )}
      </div>
      <p>{query.data ? t("documents.total", { count: query.data.total }) : t("loading")}</p>
      {query.isPending || query.isFetching ? (
        <LoadingState label={t("loading")} />
      ) : query.isError ? (
        <ErrorState
          title={t("documents.listError")}
          description={documentError(query.error, t)}
          cta={{
            label: t("retry"),
            onClick: () => {
              const valid = capture(),
                stamp = version.current;
              void props.revalidate().then((allowed) => {
                if (allowed && valid() && stamp === version.current) {
                  if (query.error instanceof ApiError && query.error.status === 404)
                    void props.checkBase();
                  else void query.refetch();
                }
              });
            },
          }}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={(query.data?.items ?? []).filter((d) =>
            documentMatches(d, workspaceId, knowledgeBaseId),
          )}
          getRowKey={(d) => d.id}
          empty={
            <EmptyState
              icon={FileText}
              title={t("documents.empty")}
              description={t("documents.emptyDescription")}
            />
          }
        />
      )}
      {query.isSuccess && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p>{t("page", { page: page + 1, pages: maxPage + 1 })}</p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={!page || query.isFetching}
              onClick={() => setPage(page - 1)}
            >
              {t("previous")}
            </Button>
            <Button
              variant="outline"
              disabled={page >= maxPage || query.isFetching}
              onClick={() => setPage(page + 1)}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      )}
      {selection?.kind === "detail" && (
        <KnowledgeDocumentDetailDialog
          key={selection.document.id}
          {...props}
          documentId={selection.document.id}
          onClose={() => setSelection(null)}
        />
      )}
      {selection && selection.kind !== "detail" && writable && (
        <DocumentWriteDialog
          key={selection.kind === "upload" ? "upload" : selection.document.id}
          {...props}
          selection={selection}
          onClose={() => setSelection(null)}
          onDeleted={() => {
            if (query.data?.items.length === 1 && page > 0) setPage(page - 1);
          }}
        />
      )}
    </section>
  );
}
function DocumentWriteDialog({
  selection,
  onClose,
  onDeleted,
  ...props
}: DocumentScope & {
  selection: Exclude<Selection, { kind: "detail"; document: KnowledgeDocumentRead }>;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("knowledgeManagement"),
    capture = useKnowledgeLease();
  const mutations = useKnowledgeDocumentMutations(
    props.userId,
    props.workspaceId,
    props.knowledgeBaseId,
  );
  const [file, setFile] = useState<File>(),
    [error, setError] = useState<string>(),
    [pending, setPending] = useState(false),
    [saved, setSaved] = useState<string>();
  const busy = useRef(false),
    live = useRef(true);
  const writing = useRef(props.canWrite);
  writing.current = props.canWrite;
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        // A successful document delete also clears this key; its own success callback is handled by the parent listener.
        if (
          within(qk.knowledge.base(props.userId, props.workspaceId, props.knowledgeBaseId), prefix)
        )
          live.current = false;
      }),
    [props.userId, props.workspaceId, props.knowledgeBaseId],
  );
  const submit = async () => {
    if (busy.current || !writing.current || !live.current || saved) return;
    const prepared = selection.kind === "upload" ? prepareDocument(file) : null;
    if (prepared && "error" in prepared) {
      setError(t(`documents.errors.${prepared.error}`));
      return;
    }
    const lease = capture(),
      valid = () => lease() && live.current && writing.current;
    if (!valid()) return;
    busy.current = true;
    setPending(true);
    setError(undefined);
    try {
      if (selection.kind === "upload") {
        const result = await mutations.upload.mutateAsync((prepared as { file: File }).file);
        if (!valid()) return;
        setFile(undefined);
        if (!documentMatches(result, props.workspaceId, props.knowledgeBaseId)) {
          setSaved(t("scopeError"));
          return;
        }
        if (result.parse_status !== "ready")
          setSaved(`${t("documents.savedFailed")} ${parseReason(result.parse_error_code, t)}`);
        else onClose();
      } else {
        await mutations.remove.mutateAsync(selection.document.id);
        if (!valid()) return;
        onDeleted();
        onClose();
      }
    } catch (failure) {
      if (!valid() || isAbort(failure)) return;
      setError(documentError(failure, t));
      if (failure instanceof ApiError && failure.status === 403) {
        live.current = false;
        onClose();
        void props.revalidate();
      }
    } finally {
      if (valid()) {
        busy.current = false;
        setPending(false);
      }
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy.current) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(selection.kind === "upload" ? "documents.upload" : "documents.delete")}
          </DialogTitle>
          <DialogDescription>
            {selection.kind === "upload"
              ? t("documents.uploadHelp")
              : t("documents.deleteWarning", { name: selection.document.filename })}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {selection.kind === "upload" && !saved && (
            <FormField label={t("documents.file")} htmlFor="document-file">
              <Input
                id="document-file"
                type="file"
                accept=".pdf,.docx,.txt,.md,.markdown"
                disabled={pending}
                onChange={(e) => setFile(e.target.files?.[0])}
              />
            </FormField>
          )}
          {pending && <p role="status">{t("documents.waiting")}</p>}
          {saved && <p role="status">{saved}</p>}
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
              {t(saved ? "documents.close" : "cancel")}
            </Button>
            {!saved && (
              <Button
                type="submit"
                variant={selection.kind === "delete" ? "destructive" : "default"}
                disabled={pending}
              >
                {t(selection.kind === "upload" ? "documents.upload" : "documents.delete")}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

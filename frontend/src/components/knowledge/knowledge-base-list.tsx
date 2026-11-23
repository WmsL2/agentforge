"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { BookOpen } from "lucide-react";
import { Button, DataTable, type Column } from "@/components/ui";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useKnowledgeBases } from "@/hooks/use-knowledge";
import { ROUTES } from "@/lib/constants";
import { localizeHref } from "@/lib/active-route";
import type { KnowledgeBaseRead } from "@/types";
import { KnowledgeBaseFormDialog, type KnowledgeDialog } from "./knowledge-base-form-dialog";
import { knowledgeDate, knowledgeError, useKnowledgeLease } from "./knowledge-ui";

export const KNOWLEDGE_PAGE_SIZE = 10;
export interface KnowledgeContentProps {
  userId: string;
  workspaceId: string;
  pathname: string;
  canWrite: boolean;
  revalidate: () => Promise<boolean>;
  revalidateWrite?: () => Promise<boolean>;
  revalidateRead?: () => Promise<boolean>;
}
export function KnowledgeBaseList({
  userId,
  workspaceId,
  pathname,
  canWrite,
  revalidate,
}: KnowledgeContentProps) {
  const capture = useKnowledgeLease();
  const t = useTranslations("knowledgeManagement"),
    locale = useLocale();
  const [page, setPage] = useState(0),
    [dialog, setDialog] = useState<KnowledgeDialog | null>(null);
  const query = useKnowledgeBases(userId, workspaceId, {
    skip: page * KNOWLEDGE_PAGE_SIZE,
    limit: KNOWLEDGE_PAGE_SIZE,
  });
  const writable = canWrite && !query.isError;
  const total = query.data?.total ?? 0,
    maxPage = Math.max(0, Math.ceil(total / KNOWLEDGE_PAGE_SIZE) - 1);
  useEffect(() => {
    if (query.isSuccess && page > maxPage) setPage(maxPage);
  }, [query.isSuccess, page, maxPage]);
  useEffect(() => {
    if (!writable) setDialog(null);
  }, [writable]);
  const columns: Column<KnowledgeBaseRead>[] = [
    {
      key: "name",
      header: t("name"),
      cell: (base) => (
        <Link
          className="font-medium underline-offset-4 hover:underline"
          href={`${localizeHref(pathname, ROUTES.KNOWLEDGE_DETAIL(base.id))}?workspace_id=${encodeURIComponent(workspaceId)}`}
        >
          {base.name}
        </Link>
      ),
    },
    {
      key: "description",
      header: t("descriptionLabel"),
      cell: (base) => (
        <span className="block max-w-md break-words whitespace-pre-wrap">
          {base.description || t("noDescription")}
        </span>
      ),
      hideBelow: "sm",
    },
    {
      key: "created",
      header: t("createdAt"),
      cell: (base) => knowledgeDate(base.created_at, locale),
      hideBelow: "md",
    },
    ...(writable
      ? [
          {
            key: "actions",
            header: t("actions"),
            cell: (base: KnowledgeBaseRead) => (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`${t("edit")} ${base.name}`}
                  onClick={() => setDialog({ kind: "edit", base })}
                >
                  {t("edit")}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  aria-label={`${t("delete")} ${base.name}`}
                  onClick={() => setDialog({ kind: "delete", base })}
                >
                  {t("delete")}
                </Button>
              </div>
            ),
          },
        ]
      : []),
  ];
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p>{query.data ? t("total", { count: total }) : t("loading")}</p>
        {writable ? (
          <Button onClick={() => setDialog({ kind: "create" })}>{t("create")}</Button>
        ) : (
          <p className="text-muted-foreground text-sm">{t("readOnly")}</p>
        )}
      </div>
      {query.isPending || query.isFetching ? (
        <LoadingState label={t("loading")} />
      ) : query.isError ? (
        <ErrorState
          title={t("errors.knowledge")}
          description={knowledgeError(query.error, t)}
          cta={{
            label: t("retry"),
            onClick: () => {
              const valid = capture();
              void revalidate().then((allowed) => {
                if (allowed && valid()) void query.refetch();
              });
            },
          }}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={query.data?.items ?? []}
          getRowKey={(base) => base.id}
          empty={
            <EmptyState icon={BookOpen} title={t("empty")} description={t("emptyDescription")} />
          }
        />
      )}
      {query.isSuccess && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p>{t("page", { page: page + 1, pages: maxPage + 1 })}</p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={page === 0 || query.isFetching}
              onClick={() => setPage((value) => Math.max(0, value - 1))}
            >
              {t("previous")}
            </Button>
            <Button
              variant="outline"
              disabled={page >= maxPage || query.isFetching}
              onClick={() => setPage((value) => value + 1)}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      )}
      {writable && dialog && (
        <KnowledgeBaseFormDialog
          key={`${dialog.kind}/${"base" in dialog ? dialog.base.id : "new"}`}
          userId={userId}
          workspaceId={workspaceId}
          dialog={dialog}
          onClose={() => setDialog(null)}
          onCreated={() => setPage(0)}
          onDeleted={() => {
            if (query.data?.items.length === 1 && page > 0) setPage(page - 1);
          }}
          onForbidden={revalidate}
        />
      )}
    </section>
  );
}

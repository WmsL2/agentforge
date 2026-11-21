"use client";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-client";
import { clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import { KnowledgeDocumentManagement } from "./knowledge-document-management";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card, CardContent } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { useKnowledgeBase } from "@/hooks/use-knowledge";
import { localizeHref } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { KnowledgeBaseFormDialog, type KnowledgeDialog } from "./knowledge-base-form-dialog";
import type { KnowledgeContentProps } from "./knowledge-base-list";
import { knowledgeDate, knowledgeError, useKnowledgeLease } from "./knowledge-ui";

export function KnowledgeBaseDetail({
  userId,
  workspaceId,
  pathname,
  canWrite,
  revalidate,
  revalidateWrite,
  knowledgeBaseId,
  workspaceName,
}: KnowledgeContentProps & { knowledgeBaseId: string; workspaceName: string }) {
  const capture = useKnowledgeLease();
  const client = useQueryClient();
  const t = useTranslations("knowledgeManagement"),
    locale = useLocale(),
    router = useRouter();
  const query = useKnowledgeBase(userId, workspaceId, knowledgeBaseId);
  const writable =
    canWrite &&
    !query.isError &&
    query.data?.workspace_id === workspaceId &&
    query.data.id === knowledgeBaseId;
  const [dialog, setDialog] = useState<KnowledgeDialog | null>(null);
  useEffect(() => {
    if (!writable) setDialog(null);
  }, [writable]);
  const back = `${localizeHref(pathname, ROUTES.KNOWLEDGE)}?workspace_id=${encodeURIComponent(workspaceId)}`;
  return (
    <section className="space-y-4">
      <Button variant="outline" asChild>
        <Link href={back}>{t("back")}</Link>
      </Button>
      {query.isPending || query.isFetching ? (
        <LoadingState label={t("loading")} />
      ) : query.isError ? (
        <ErrorState
          title={t("errors.detail")}
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
      ) : query.data?.workspace_id !== workspaceId || query.data.id !== knowledgeBaseId ? (
        <ErrorState title={t("scopeError")} description={t("errors.notFound")} />
      ) : (
        <>
          <Card>
            <CardContent className="space-y-4 pt-6">
              <h2 className="text-2xl font-semibold break-words">{query.data.name}</h2>
              <p className="break-words whitespace-pre-wrap">
                {query.data.description || t("noDescription")}
              </p>
              <dl className="grid gap-4 sm:grid-cols-2">
                {[
                  [t("workspace"), workspaceName],
                  [t("id"), query.data.id],
                  [t("createdAt"), knowledgeDate(query.data.created_at, locale)],
                  [t("updatedAt"), knowledgeDate(query.data.updated_at, locale)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-muted-foreground text-sm">{label}</dt>
                    <dd className="break-all">{value}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
          {writable ? (
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setDialog({ kind: "edit", base: query.data! })}
              >
                {t("edit")}
              </Button>
              <Button
                variant="destructive"
                onClick={() => setDialog({ kind: "delete", base: query.data! })}
              >
                {t("delete")}
              </Button>
            </div>
          ) : (
            <p>{t("readOnly")}</p>
          )}
          <KnowledgeDocumentManagement
            key={`${userId}/${workspaceId}/${knowledgeBaseId}`}
            userId={userId}
            workspaceId={workspaceId}
            knowledgeBaseId={knowledgeBaseId}
            canWrite={writable}
            revalidate={revalidate}
            revalidateWrite={revalidateWrite}
            checkBase={async () => {
              const valid = capture();
              const result = await query.refetch();
              if (valid() && result.error instanceof ApiError && result.error.status === 404)
                clearKnowledgeScope(
                  client,
                  qk.knowledge.base(userId, workspaceId, knowledgeBaseId),
                );
            }}
          />
        </>
      )}
      {writable && dialog && (
        <KnowledgeBaseFormDialog
          key={`${dialog.kind}/${"base" in dialog ? dialog.base.id : "new"}`}
          userId={userId}
          workspaceId={workspaceId}
          dialog={dialog}
          onClose={() => setDialog(null)}
          onCreated={() => {}}
          onDeleted={() => router.push(back)}
          onForbidden={revalidate}
        />
      )}
    </section>
  );
}

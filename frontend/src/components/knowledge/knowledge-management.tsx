"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Card,
  CardContent,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useWorkspaces, useWorkspaceMembers } from "@/hooks/use-workspaces";
import { useAuthStore } from "@/stores/auth-store";
import { authIdentity } from "@/lib/auth-identity";
import { ApiError } from "@/lib/api-client";
import { clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import { ROUTES } from "@/lib/constants";
import { localizeHref } from "@/lib/active-route";
import type { WorkspaceRead } from "@/types";
import { KnowledgeBaseList } from "./knowledge-base-list";
import { KnowledgeBaseDetail } from "./knowledge-base-detail";
import { knowledgeError, useKnowledgeLease } from "./knowledge-ui";

const FRESH_ACCESS = { authorizationFresh: true } as const;
export function KnowledgeManagement({
  userId,
  knowledgeBaseId,
}: {
  userId: string;
  knowledgeBaseId?: string;
}) {
  useAuthStore((state) => state.user);
  const identity = authIdentity();
  if (identity.userId !== userId) return null;
  return (
    <KnowledgeSession
      key={`${userId}/${identity.generation}/${identity.transitionEpoch}`}
      userId={userId}
      knowledgeBaseId={knowledgeBaseId}
    />
  );
}
function KnowledgeSession({
  userId,
  knowledgeBaseId,
}: {
  userId: string;
  knowledgeBaseId?: string;
}) {
  const t = useTranslations("knowledgeManagement"),
    pathname = usePathname(),
    router = useRouter(),
    search = useSearchParams();
  const requested = search.get("workspace_id");
  const query = useWorkspaces(userId, FRESH_ACCESS);
  const capture = useKnowledgeLease();
  const refetchWorkspaces = query.refetch;
  const client = useQueryClient();
  const [revoked, setRevoked] = useState<string[]>([]);
  const workspaces = (query.data ?? []).filter((workspace) => !revoked.includes(workspace.id));
  const selected =
    workspaces.find((workspace) => workspace.id === requested) ??
    (knowledgeBaseId ? undefined : workspaces[0]);
  const listHref = localizeHref(pathname, ROUTES.KNOWLEDGE);
  useEffect(() => {
    if (knowledgeBaseId || !query.isSuccess || query.isFetching || !query.isFetchedAfterMount)
      return;
    if (selected && selected.id !== requested)
      router.replace(`${listHref}?workspace_id=${encodeURIComponent(selected.id)}`);
  }, [
    knowledgeBaseId,
    query.isSuccess,
    query.isFetching,
    query.isFetchedAfterMount,
    selected,
    requested,
    listHref,
    router,
  ]);
  const accessLost = useCallback(
    (workspaceId: string) => {
      if (!capture()()) return;
      clearKnowledgeScope(client, qk.knowledge.workspace(userId, workspaceId));
      setRevoked((current) =>
        current.includes(workspaceId) ? current : [...current, workspaceId],
      );
      void refetchWorkspaces();
    },
    [client, userId, refetchWorkspaces, capture],
  );
  if (query.isError)
    return (
      <ErrorState
        title={t("errors.workspace")}
        description={knowledgeError(query.error, t)}
        cta={{ label: t("retry"), onClick: () => void query.refetch() }}
      />
    );
  if (!query.isFetchedAfterMount || query.isFetching || query.isPending)
    return <LoadingState label={t("checkingAccess")} />;
  if (knowledgeBaseId && !selected)
    return (
      <ErrorState
        title={t("scopeError")}
        description={t("errors.notFound")}
        cta={{ label: t("back"), onClick: () => router.push(listHref) }}
      />
    );
  return (
    <div className="space-y-6 pb-8">
      <PageHeader title={t("title")} description={t("description")} />
      {workspaces.length === 0 ? (
        revoked.length > 0 ? (
          <ErrorState
            title={t("accessLost")}
            description={t("scopeError")}
            cta={{
              label: t("retry"),
              onClick: () => {
                setRevoked([]);
                void query.refetch();
              },
            }}
          />
        ) : (
          <EmptyState
            title={t("noWorkspaces")}
            description={t("noWorkspacesDescription")}
            cta={{
              label: t("workflows"),
              onClick: () => router.push(localizeHref(pathname, ROUTES.WORKFLOWS)),
            }}
          />
        )
      ) : (
        <>
          <Card>
            <CardContent className="pt-6">
              <FormField label={t("workspace")} htmlFor="knowledge-workspace">
                <Select
                  value={selected?.id}
                  onValueChange={(id) =>
                    router.push(`${listHref}?workspace_id=${encodeURIComponent(id)}`)
                  }
                >
                  <SelectTrigger id="knowledge-workspace" className="sm:max-w-md">
                    <SelectValue placeholder={t("selectWorkspace")} />
                  </SelectTrigger>
                  <SelectContent>
                    {workspaces.map((workspace) => (
                      <SelectItem key={workspace.id} value={workspace.id}>
                        {workspace.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            </CardContent>
          </Card>
          {selected && (
            <KnowledgeWorkspace
              key={`${selected.id}/${knowledgeBaseId ?? "list"}`}
              userId={userId}
              workspace={selected}
              knowledgeBaseId={knowledgeBaseId}
              pathname={pathname}
              onAccessLost={accessLost}
            />
          )}
        </>
      )}
    </div>
  );
}
function KnowledgeWorkspace({
  userId,
  workspace,
  knowledgeBaseId,
  pathname,
  onAccessLost,
}: {
  userId: string;
  workspace: WorkspaceRead;
  knowledgeBaseId?: string;
  pathname: string;
  onAccessLost: (id: string) => void;
}) {
  const t = useTranslations("knowledgeManagement");
  const members = useWorkspaceMembers(userId, workspace.id, FRESH_ACCESS);
  const writeCheck = useRef(false);
  const capture = useKnowledgeLease();
  // Keep the verified reader mounted during its own write preflight, but hide writes.
  const verified =
    members.isSuccess && members.isFetchedAfterMount && (!members.isFetching || writeCheck.current);
  const membership = verified
    ? members.data.find(
        (member) => member.user_id === userId && member.workspace_id === workspace.id,
      )
    : undefined;
  const lost =
    (members.isError &&
      members.error instanceof ApiError &&
      [403, 404].includes(members.error.status)) ||
    (verified && !membership);
  useEffect(() => {
    if (lost) onAccessLost(workspace.id);
  }, [lost, onAccessLost, workspace.id]);
  if (lost) return <ErrorState title={t("accessLost")} description={t("scopeError")} />;
  if (members.isError)
    return (
      <ErrorState
        title={t("errors.membership")}
        description={knowledgeError(members.error, t)}
        cta={{ label: t("retry"), onClick: () => void members.refetch() }}
      />
    );
  if (!verified || !membership) return <LoadingState label={t("checkingAccess")} />;
  const canWrite =
    !members.isFetching && (membership.role === "owner" || membership.role === "admin");
  const props = {
    userId,
    workspaceId: workspace.id,
    pathname,
    canWrite,
    revalidateWrite: async () => {
      if (writeCheck.current) return false;
      const valid = capture();
      if (!valid()) return false;
      writeCheck.current = true;
      try {
        const result = await members.refetch();
        return (
          valid() &&
          result.isSuccess &&
          result.data.some(
            (member) =>
              member.user_id === userId &&
              member.workspace_id === workspace.id &&
              (member.role === "owner" || member.role === "admin"),
          )
        );
      } finally {
        writeCheck.current = false;
      }
    },
    revalidate: async () => {
      const result = await members.refetch();
      return (
        result.isSuccess &&
        result.data.some(
          (member) => member.user_id === userId && member.workspace_id === workspace.id,
        )
      );
    },
  };
  return knowledgeBaseId ? (
    <KnowledgeBaseDetail
      {...props}
      knowledgeBaseId={knowledgeBaseId}
      workspaceName={workspace.name}
    />
  ) : (
    <KnowledgeBaseList {...props} />
  );
}

"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { UseQueryResult } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  Settings2,
  Trash2,
  Users,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  type Column,
} from "@/components/ui";
import {
  useMemberMutations,
  useWorkspaceMembers,
  useWorkspaceMutations,
  useWorkspaces,
  useWorkflows,
  useWorkflowMutations,
} from "@/hooks";
import { ApiError, getApiErrorMessage } from "@/lib/api-client";
import { localizeHref } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";
import type {
  WorkspaceMemberRead,
  WorkspaceRead,
  WorkspaceRole,
  WorkflowList as WorkflowListData,
  WorkflowRead,
} from "@/types";

const PAGE_SIZE = 10;

function errorMessage(error: unknown, t: ReturnType<typeof useTranslations>): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return t("errors.forbidden");
    if (error.status === 404) return t("errors.notFound");
    if (error.status === 409) return t("errors.conflict");
    if (error.status === 422) return getApiErrorMessage(error.data, t("errors.validation"));
    if (error.status >= 500) return t("errors.server");
    return getApiErrorMessage(error.data, error.message);
  }
  return t("errors.server");
}

function validateName(name: string, t: ReturnType<typeof useTranslations>) {
  const value = name.trim();
  if (!value) return t("errors.nameRequired");
  if (value.length > 255) return t("errors.nameTooLong");
  return null;
}

export function WorkflowManagement({ userId }: { userId: string }) {
  const t = useTranslations("workflows");
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedWorkspaceId = searchParams.get("workspace_id") ?? undefined;
  const [page, setPage] = useState(0);
  const invalidNotice = useRef<string | null>(null);

  const workspaces = useWorkspaces(userId);
  const refetchWorkspaces = workspaces.refetch;
  const recoverAccess = useCallback(() => void refetchWorkspaces(), [refetchWorkspaces]);
  const selectedWorkspace = workspaces.data?.find((item) => item.id === requestedWorkspaceId);
  const selectedWorkspaceId = selectedWorkspace?.id;

  useEffect(() => {
    if (!workspaces.isSuccess) return;
    const first = workspaces.data[0];
    if (!first) {
      if (requestedWorkspaceId) router.replace(pathname);
      return;
    }
    if (!selectedWorkspace) {
      router.replace(`${pathname}?workspace_id=${encodeURIComponent(first.id)}`);
      if (requestedWorkspaceId && invalidNotice.current !== requestedWorkspaceId) {
        invalidNotice.current = requestedWorkspaceId;
        toast.info(t("workspaceSelectionRecovered"));
      }
    }
  }, [
    pathname,
    requestedWorkspaceId,
    router,
    selectedWorkspace,
    t,
    workspaces.data,
    workspaces.isSuccess,
  ]);

  useEffect(() => setPage(0), [selectedWorkspaceId]);

  if (workspaces.isLoading) return <LoadingState variant="skeleton-cards" rows={2} />;
  if (workspaces.isError) {
    return (
      <ErrorState
        title={t("errors.loadWorkspaces")}
        description={errorMessage(workspaces.error, t)}
        cta={{ label: t("retry"), onClick: () => void workspaces.refetch() }}
      />
    );
  }

  const workspaceItems = workspaces.data ?? [];

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={<CreateWorkspaceButton userId={userId} />}
      />

      {workspaceItems.length === 0 ? (
        <EmptyState
          icon={Workflow}
          title={t("noWorkspaces")}
          description={t("noWorkspacesDescription")}
          cta={{
            label: t("createWorkspace"),
            onClick: () => document.getElementById("create-workspace-trigger")?.click(),
          }}
        />
      ) : (
        <>
          <WorkspacePicker
            workspaces={workspaceItems}
            selectedId={selectedWorkspaceId}
            onSelect={(workspaceId) =>
              router.push(`${pathname}?workspace_id=${encodeURIComponent(workspaceId)}`)
            }
          />
          {selectedWorkspace && (
            <WorkspaceContent
              userId={userId}
              workspace={selectedWorkspace}
              page={page}
              onPageChange={setPage}
              onAccessLost={recoverAccess}
            />
          )}
        </>
      )}
    </div>
  );
}

function WorkspacePicker({
  workspaces,
  selectedId,
  onSelect,
}: {
  workspaces: WorkspaceRead[];
  selectedId?: string;
  onSelect: (workspaceId: string) => void;
}) {
  const t = useTranslations("workflows");
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-6 sm:flex-row sm:items-end sm:justify-between">
        <FormField label={t("workspace")} htmlFor="workspace-picker" className="w-full sm:max-w-md">
          <Select value={selectedId} onValueChange={onSelect}>
            <SelectTrigger id="workspace-picker">
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
        <p className="text-muted-foreground font-mono text-xs">{selectedId}</p>
      </CardContent>
    </Card>
  );
}

function WorkspaceContent({
  userId,
  workspace,
  page,
  onPageChange,
  onAccessLost,
}: {
  userId: string;
  workspace: WorkspaceRead;
  page: number;
  onPageChange: (page: number) => void;
  onAccessLost: () => void;
}) {
  const t = useTranslations("workflows");
  const members = useWorkspaceMembers(userId, workspace.id);
  const currentMembership = members.data?.find((member) => member.user_id === userId);
  const role = currentMembership?.role;
  const canManageWorkspace = role === "owner";
  const canManageMembers = role === "owner" || role === "admin";
  const canDeleteWorkflow = role === "owner" || role === "admin";
  const workflows = useWorkflows(userId, workspace.id, page * PAGE_SIZE, PAGE_SIZE);

  useEffect(() => {
    if (
      (members.error instanceof ApiError && members.error.status === 404) ||
      (workflows.error instanceof ApiError && workflows.error.status === 404) ||
      (members.isSuccess && !currentMembership)
    ) {
      toast.info(t("workspaceSelectionRecovered"));
      onAccessLost();
    }
  }, [currentMembership, members.error, members.isSuccess, onAccessLost, t, workflows.error]);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <WorkflowList
        userId={userId}
        workspace={workspace}
        role={role}
        canDelete={canDeleteWorkflow}
        page={page}
        onPageChange={onPageChange}
        query={workflows}
      />
      <WorkspacePanel
        userId={userId}
        workspace={workspace}
        role={role}
        canManageWorkspace={canManageWorkspace}
        canManageMembers={canManageMembers}
        members={members}
      />
    </div>
  );
}

function WorkflowList({
  userId,
  workspace,
  role,
  canDelete,
  page,
  onPageChange,
  query,
}: {
  userId: string;
  workspace: WorkspaceRead;
  role?: WorkspaceRole;
  canDelete: boolean;
  page: number;
  onPageChange: (page: number) => void;
  query: UseQueryResult<WorkflowListData, Error>;
}) {
  const t = useTranslations("workflows");
  const pathname = usePathname();
  const mutations = useWorkflowMutations(userId, workspace.id, page * PAGE_SIZE, PAGE_SIZE);
  const [editing, setEditing] = useState<WorkflowRead | null>(null);
  const [deleting, setDeleting] = useState<WorkflowRead | null>(null);
  const total = query.data?.total ?? 0;
  const columns = useMemo<Column<WorkflowRead>[]>(
    () => [
      {
        key: "name",
        header: t("columns.name"),
        cell: (item) => (
          <Link
            className="font-medium hover:underline"
            href={`${localizeHref(pathname, `${ROUTES.WORKFLOWS}/${item.id}`)}?workspace_id=${encodeURIComponent(workspace.id)}`}
          >
            {item.name}
          </Link>
        ),
      },
      {
        key: "description",
        header: t("columns.description"),
        hideBelow: "md",
        cell: (item) => (
          <span className="text-muted-foreground line-clamp-1">
            {item.description || t("noDescription")}
          </span>
        ),
      },
      {
        key: "revision",
        header: t("columns.revision"),
        cell: (item) => <Badge variant="outline">r{item.revision}</Badge>,
      },
      {
        key: "created",
        header: t("columns.created"),
        hideBelow: "sm",
        cell: (item) => new Date(item.created_at).toLocaleDateString(),
      },
      {
        key: "actions",
        header: t("columns.actions"),
        align: "right",
        cell: (item) => (
          <div className="flex justify-end gap-1">
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("editWorkflow")}
              onClick={() => setEditing(item)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            {canDelete && (
              <Button
                size="sm"
                variant="ghost"
                aria-label={t("deleteWorkflow")}
                onClick={() => setDeleting(item)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        ),
      },
    ],
    [canDelete, pathname, t, workspace.id],
  );

  if (query.isError)
    return (
      <ErrorState
        title={t("errors.loadWorkflows")}
        description={errorMessage(query.error, t)}
        cta={{ label: t("retry"), onClick: () => void query.refetch() }}
      />
    );

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">{t("workflowList")}</h2>
          <p className="text-muted-foreground text-sm">{t("workflowCount", { count: total })}</p>
        </div>
        <CreateWorkflowButton userId={userId} workspaceId={workspace.id} page={page} />
      </div>
      <DataTable
        columns={columns}
        rows={query.data?.items}
        loading={query.isLoading}
        getRowKey={(row: WorkflowRead) => row.id}
        empty={<span>{t("noWorkflows")}</span>}
      />
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          disabled={page === 0 || query.isFetching}
          onClick={() => onPageChange(Math.max(0, page - 1))}
        >
          <ChevronLeft className="h-4 w-4" />
          {t("previous")}
        </Button>
        <span className="text-muted-foreground text-sm">{t("page", { page: page + 1 })}</span>
        <Button
          variant="outline"
          size="sm"
          disabled={(page + 1) * PAGE_SIZE >= total || query.isFetching}
          onClick={() => onPageChange(page + 1)}
        >
          {t("next")}
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <WorkflowFormDialog
        open={Boolean(editing)}
        onOpenChange={(open) => !open && setEditing(null)}
        title={t("editWorkflow")}
        initial={editing ?? undefined}
        loading={mutations.update.isPending}
        onSubmit={async (name, description) => {
          if (!editing) return;
          try {
            await mutations.update.mutateAsync({
              workflowId: editing.id,
              payload: { name, description },
            });
            toast.success(t("workflowUpdated"));
            setEditing(null);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteWorkflow")}
        description={t("deleteWorkflowDescription", { name: deleting?.name ?? "" })}
        destructive
        confirmLabel={t("delete")}
        loading={mutations.remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await mutations.remove.mutateAsync(deleting.id);
            toast.success(t("workflowDeleted"));
            setDeleting(null);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
      {role === "member" && (
        <p className="text-muted-foreground text-xs">{t("memberDeleteRestriction")}</p>
      )}
    </section>
  );
}

function WorkspacePanel({
  userId,
  workspace,
  role,
  canManageWorkspace,
  canManageMembers,
  members,
}: {
  userId: string;
  workspace: WorkspaceRead;
  role?: WorkspaceRole;
  canManageWorkspace: boolean;
  canManageMembers: boolean;
  members: UseQueryResult<WorkspaceMemberRead[], Error>;
}) {
  const t = useTranslations("workflows");
  const workspaceMutations = useWorkspaceMutations(userId);
  const memberMutations = useMemberMutations(userId, workspace.id);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [adding, setAdding] = useState(false);

  return (
    <aside className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            {t("workspaceSettings")}
          </CardTitle>
          <CardDescription>{workspace.name}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground text-sm">{t("yourRole")}</span>
            <Badge variant="secondary">{role ? t(`roles.${role}`) : t("loading")}</Badge>
          </div>
          {canManageWorkspace && (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setRenaming(true)}>
                {t("renameWorkspace")}
              </Button>
              <Button variant="destructive" size="sm" onClick={() => setDeleting(true)}>
                {t("deleteWorkspace")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            {t("members")}
          </CardTitle>
          <CardDescription>{t("membersDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {canManageMembers && (
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" />
              {t("addMember")}
            </Button>
          )}
          {members.isLoading && <LoadingState variant="skeleton-list" rows={3} />}
          {members.isError && (
            <ErrorState
              title={t("errors.loadMembers")}
              description={errorMessage(members.error, t)}
              cta={{ label: t("retry"), onClick: () => void members.refetch() }}
            />
          )}
          {members.data?.map((member: WorkspaceMemberRead) => (
            <MemberRow
              key={member.user_id}
              member={member}
              canManage={canManageMembers}
              busy={memberMutations.update.isPending || memberMutations.remove.isPending}
              onRole={async (nextRole) => {
                try {
                  await memberMutations.update.mutateAsync({
                    memberUserId: member.user_id,
                    payload: { role: nextRole },
                  });
                  toast.success(t("memberUpdated"));
                } catch (error) {
                  toast.error(errorMessage(error, t));
                }
              }}
              onRemove={async () => {
                try {
                  await memberMutations.remove.mutateAsync(member.user_id);
                  toast.success(t("memberRemoved"));
                } catch (error) {
                  toast.error(errorMessage(error, t));
                }
              }}
            />
          ))}
        </CardContent>
      </Card>
      <WorkflowFormDialog
        open={renaming}
        onOpenChange={setRenaming}
        title={t("renameWorkspace")}
        initial={{ name: workspace.name, description: null }}
        nameOnly
        loading={workspaceMutations.update.isPending}
        onSubmit={async (name) => {
          try {
            await workspaceMutations.update.mutateAsync({
              workspaceId: workspace.id,
              payload: { name },
            });
            toast.success(t("workspaceUpdated"));
            setRenaming(false);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t("deleteWorkspace")}
        description={t("deleteWorkspaceDescription", { name: workspace.name })}
        confirmText={workspace.name}
        destructive
        confirmLabel={t("delete")}
        loading={workspaceMutations.remove.isPending}
        onConfirm={async () => {
          try {
            await workspaceMutations.remove.mutateAsync(workspace.id);
            toast.success(t("workspaceDeleted"));
            setDeleting(false);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
      <AddMemberDialog
        open={adding}
        onOpenChange={setAdding}
        loading={memberMutations.add.isPending}
        onSubmit={async (memberUserId, memberRole) => {
          try {
            await memberMutations.add.mutateAsync({ user_id: memberUserId, role: memberRole });
            toast.success(t("memberAdded"));
            setAdding(false);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
    </aside>
  );
}

function MemberRow({
  member,
  canManage,
  busy,
  onRole,
  onRemove,
}: {
  member: WorkspaceMemberRead;
  canManage: boolean;
  busy: boolean;
  onRole: (role: "admin" | "member") => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  const t = useTranslations("workflows");
  const owner = member.role === "owner";
  return (
    <div className="border-border space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs" title={member.user_id}>
          {member.user_id}
        </span>
        <Badge variant={owner ? "default" : "outline"}>{t(`roles.${member.role}`)}</Badge>
      </div>
      <p className="text-muted-foreground text-xs">
        {t("joined", { date: new Date(member.created_at).toLocaleDateString() })}
      </p>
      {canManage && !owner && (
        <div className="flex gap-2">
          <Select
            value={member.role}
            disabled={busy}
            onValueChange={(value) => void onRole(value as "admin" | "member")}
          >
            <SelectTrigger aria-label={t("memberRole")} className="h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="admin">{t("roles.admin")}</SelectItem>
              <SelectItem value="member">{t("roles.member")}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={t("removeMember")}
            onClick={() => void onRemove()}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      )}
      {owner && <p className="text-muted-foreground text-xs">{t("ownerProtected")}</p>}
    </div>
  );
}

function CreateWorkspaceButton({ userId }: { userId: string }) {
  const t = useTranslations("workflows");
  const mutations = useWorkspaceMutations(userId);
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button id="create-workspace-trigger" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" />
        {t("createWorkspace")}
      </Button>
      <WorkflowFormDialog
        open={open}
        onOpenChange={setOpen}
        title={t("createWorkspace")}
        nameOnly
        loading={mutations.create.isPending}
        onSubmit={async (name) => {
          try {
            await mutations.create.mutateAsync({ name });
            toast.success(t("workspaceCreated"));
            setOpen(false);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
    </>
  );
}

function CreateWorkflowButton({
  userId,
  workspaceId,
  page,
}: {
  userId: string;
  workspaceId: string;
  page: number;
}) {
  const t = useTranslations("workflows");
  const mutations = useWorkflowMutations(userId, workspaceId, page * PAGE_SIZE, PAGE_SIZE);
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" />
        {t("createWorkflow")}
      </Button>
      <WorkflowFormDialog
        open={open}
        onOpenChange={setOpen}
        title={t("createWorkflow")}
        loading={mutations.create.isPending}
        onSubmit={async (name, description) => {
          try {
            await mutations.create.mutateAsync({
              name,
              description,
              definition: createDefaultWorkflowGraph(),
            });
            toast.success(t("workflowCreated"));
            setOpen(false);
          } catch (error) {
            toast.error(errorMessage(error, t));
          }
        }}
      />
    </>
  );
}

function WorkflowFormDialog({
  open,
  onOpenChange,
  title,
  initial,
  nameOnly,
  loading,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  initial?: Pick<WorkflowRead, "name" | "description">;
  nameOnly?: boolean;
  loading: boolean;
  onSubmit: (name: string, description: string | null) => Promise<void>;
}) {
  const t = useTranslations("workflows");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setDescription(initial?.description ?? "");
      setError(null);
    }
  }, [initial, open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{t("formDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            const nextError = validateName(name, t);
            setError(nextError);
            if (!nextError) void onSubmit(name.trim(), description.trim() || null);
          }}
        >
          <FormField label={t("name")} htmlFor="resource-name" error={error} required>
            <Input
              id="resource-name"
              value={name}
              maxLength={255}
              disabled={loading}
              onChange={(event) => setName(event.target.value)}
            />
          </FormField>
          {!nameOnly && (
            <FormField label={t("workflowDescription")} htmlFor="resource-description">
              <Textarea
                id="resource-description"
                value={description}
                disabled={loading}
                onChange={(event) => setDescription(event.target.value)}
              />
            </FormField>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={loading}
              onClick={() => onOpenChange(false)}
            >
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddMemberDialog({
  open,
  onOpenChange,
  loading,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loading: boolean;
  onSubmit: (userId: string, role: "admin" | "member") => Promise<void>;
}) {
  const t = useTranslations("workflows");
  const [memberUserId, setMemberUserId] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setMemberUserId("");
      setRole("member");
      setError(null);
    }
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("addMember")}</DialogTitle>
          <DialogDescription>{t("addMemberDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            const value = memberUserId.trim();
            if (!value) {
              setError(t("errors.userIdRequired"));
              return;
            }
            void onSubmit(value, role);
          }}
        >
          <FormField label={t("userId")} htmlFor="member-user-id" error={error} required>
            <Input
              id="member-user-id"
              value={memberUserId}
              disabled={loading}
              onChange={(event) => setMemberUserId(event.target.value)}
            />
          </FormField>
          <FormField label={t("memberRole")} htmlFor="new-member-role">
            <Select value={role} onValueChange={(value) => setRole(value as "admin" | "member")}>
              <SelectTrigger id="new-member-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">{t("roles.admin")}</SelectItem>
                <SelectItem value="member">{t("roles.member")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? t("saving") : t("addMember")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

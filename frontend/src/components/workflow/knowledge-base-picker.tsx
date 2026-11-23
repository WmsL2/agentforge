"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";
import { Button, FormField } from "@/components/ui";
import { useKnowledgeBase, useKnowledgeBases } from "@/hooks/use-knowledge";
import { authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { useAuthStore } from "@/stores/auth-store";
import { onKnowledgeClear, within } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import { canonicalKnowledgeUuid } from "@/lib/workflow/knowledge-config";
import type { KnowledgeBaseRead, WorkspaceMemberRead } from "@/types";
export interface KnowledgeSelectionProof {
  scope: string;
  value: string;
  verified: boolean;
  current: () => boolean;
}
interface Props {
  authorized?: boolean;
  userId: string;
  workspaceId: string;
  scope: string;
  value: string;
  disabled: boolean;
  optional: boolean;
  onChange: (value: string) => void;
  onVerification: (proof: KnowledgeSelectionProof) => void;
}
export function KnowledgeBasePicker(props: Props) {
  useAuthStore((s) => s.user);
  const identity = authIdentity();
  const t = useTranslations("workflows.canvas.knowledge");
  const { userId, authorized, scope, value, onVerification } = props;
  useEffect(() => {
    if (identity.userId !== userId || authorized === false)
      onVerification({ scope, value, verified: false, current: () => false });
  }, [identity.userId, authorized, userId, scope, value, onVerification]);
  if (identity.userId !== props.userId || props.authorized === false)
    return <p role="status">{t("unavailable")}</p>;
  return (
    <PickerSession
      key={`${props.scope}/${identity.generation}/${identity.transitionEpoch}`}
      {...props}
    />
  );
}
function PickerSession({
  authorized,
  userId,
  workspaceId,
  scope,
  value,
  disabled,
  optional,
  onChange,
  onVerification,
}: Props) {
  const t = useTranslations("workflows.canvas.knowledge"),
    client = useQueryClient();
  const [page, setPage] = useState(0),
    [revoked, setRevoked] = useState(false),
    [lostId, setLostId] = useState<string>();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const resource = useRef(true),
    identity = useMemo(() => authIdentity(), []),
    fetched = useRef(false);
  const id = canonicalKnowledgeUuid(value);
  const selection = useRef({ id, live: true });
  if (selection.current.id !== id) selection.current = { id, live: true };
  const authenticated = identity.userId === userId && sameAuthIdentity(identity) && !revoked;
  const list = useKnowledgeBases(
    authenticated ? userId : undefined,
    authenticated ? workspaceId : undefined,
    { skip: page * 10, limit: 10 },
  );
  const detail = useKnowledgeBase(
    authenticated && id && lostId !== id ? userId : undefined,
    authenticated && id && lostId !== id ? workspaceId : undefined,
    authenticated && id && lostId !== id ? id : undefined,
  );
  const listVerified =
    authenticated && list.isSuccess && list.isFetchedAfterMount && !list.isFetching;
  fetched.current =
    authenticated && detail.isSuccess && detail.isFetchedAfterMount && !detail.isFetching;
  const options = (listVerified ? list.data.items : []).filter(
    (base) =>
      base.workspace_id === workspaceId &&
      canonicalKnowledgeUuid(base.id) &&
      canonicalKnowledgeUuid(base.id) !== lostId &&
      !(detail.isError && canonicalKnowledgeUuid(base.id) === id),
  );
  const membershipCurrent = useCallback(() => {
    if (authorized === undefined) return true;
    const state = client.getQueryState<WorkspaceMemberRead[]>(
      qk.workspaces.members(userId, workspaceId),
    );
    return Boolean(
      state?.status === "success" &&
      state.fetchStatus === "idle" &&
      state.data?.some(
        (member) => member.user_id === userId && member.workspace_id === workspaceId,
      ),
    );
  }, [authorized, client, userId, workspaceId]);
  const current = useCallback(() => {
    if (
      !mounted.current ||
      !resource.current ||
      !membershipCurrent() ||
      identity.userId !== userId ||
      !sameAuthIdentity(identity) ||
      !id ||
      !fetched.current ||
      selection.current.id !== id ||
      !selection.current.live
    )
      return false;
    const state = client.getQueryState<KnowledgeBaseRead>(
      qk.knowledge.base(userId, workspaceId, id),
    );
    return Boolean(
      state?.status === "success" &&
      state.fetchStatus === "idle" &&
      state.data?.workspace_id === workspaceId &&
      canonicalKnowledgeUuid(state.data.id) === id,
    );
  }, [client, id, identity, userId, workspaceId, membershipCurrent]);
  const verified = current();
  useEffect(
    () => onVerification({ scope, value, verified, current }),
    [scope, value, verified, current, onVerification],
  );
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        const workspace = qk.knowledge.workspace(userId, workspaceId),
          base = id ? qk.knowledge.base(userId, workspaceId, id) : workspace;
        if (within(workspace, prefix)) {
          resource.current = false;
          setRevoked(true);
        } else if (id && within(base, prefix)) {
          selection.current.live = false;
          setLostId(id);
        }
      }),
    [id, userId, workspaceId],
  );
  const maxPage = Math.max(0, Math.ceil((list.data?.total ?? 0) / 10) - 1);
  useEffect(() => {
    if (list.isSuccess && page > maxPage) setPage(maxPage);
  }, [list.isSuccess, page, maxPage]);
  const selectedInPage = options.some(
    (base) => canonicalKnowledgeUuid(base.id) === id && base.id === value,
  );
  return (
    <div className="space-y-2">
      <FormField label={t(optional ? "binding" : "base")} htmlFor="workflow-knowledge-base">
        <select
          id="workflow-knowledge-base"
          className="bg-background w-full rounded-md border p-2 text-sm"
          value={value}
          disabled={disabled || !authenticated || !resource.current}
          onChange={(event) => {
            if (disabled || !mounted.current || !resource.current || !sameAuthIdentity(identity))
              return;
            const selected = event.target.value;
            if (!selected && optional) {
              onChange("");
              return;
            }
            const state = client.getQueryState(
              qk.knowledge.list(userId, workspaceId, page * 10, 10),
            );
            if (
              listVerified &&
              state?.status === "success" &&
              state.fetchStatus === "idle" &&
              options.some((base) => base.id === selected)
            )
              onChange(selected);
          }}
        >
          <option value="">{t(optional ? "none" : "choose")}</option>
          {value && !selectedInPage && (
            <option value={value} disabled={!verified}>
              {verified ? detail.data?.name : t("unverified")}
            </option>
          )}
          {options.map((base) => (
            <option key={base.id} value={base.id}>
              {base.name}
            </option>
          ))}
        </select>
      </FormField>
      {!authenticated || revoked ? (
        <p role="alert">{t("unavailable")}</p>
      ) : list.isFetching || list.isPending ? (
        <p role="status">{t("loading")}</p>
      ) : list.isError ? (
        <div>
          <p role="alert">{t("loadFailed")}</p>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              if (mounted.current && resource.current && sameAuthIdentity(identity))
                void list.refetch();
            }}
          >
            {t("retry")}
          </Button>
        </div>
      ) : !options.length ? (
        <p>{t("empty")}</p>
      ) : null}
      {value && !verified && (
        <div>
          <p role="status">
            {t(
              !id
                ? "invalidId"
                : lostId === id
                  ? "unavailable"
                  : detail.isPending || detail.isFetching
                    ? "verifying"
                    : detail.isError
                      ? "unavailable"
                      : "unverified",
            )}
          </p>
          {id && (detail.isError || lostId === id) && authenticated && !revoked && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (!mounted.current || !resource.current || !sameAuthIdentity(identity)) return;
                if (lostId === id) {
                  selection.current.live = true;
                  setLostId(undefined);
                } else void detail.refetch();
              }}
            >
              {t("retrySelection")}
            </Button>
          )}
        </div>
      )}
      {list.isSuccess && (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={list.isFetching || page === 0 || revoked}
            onClick={() => setPage((p) => p - 1)}
          >
            {t("previous")}
          </Button>
          <span>{t("page", { page: page + 1, pages: maxPage + 1 })}</span>
          <Button
            type="button"
            variant="outline"
            disabled={list.isFetching || page >= maxPage || revoked}
            onClick={() => setPage((p) => p + 1)}
          >
            {t("next")}
          </Button>
        </div>
      )}
    </div>
  );
}

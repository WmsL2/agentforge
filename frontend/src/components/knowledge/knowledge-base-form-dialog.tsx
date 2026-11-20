"use client";
import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Textarea,
} from "@/components/ui";
import { useKnowledgeBaseMutations } from "@/hooks/use-knowledge";
import { ApiError } from "@/lib/api-client";
import type { KnowledgeBaseRead } from "@/types";
import { isAbort, knowledgeError, useKnowledgeLease } from "./knowledge-ui";

export type KnowledgeDialog =
  { kind: "create" } | { kind: "edit" | "delete"; base: KnowledgeBaseRead };
export function KnowledgeBaseFormDialog({
  userId,
  workspaceId,
  dialog,
  onClose,
  onCreated,
  onDeleted,
  onForbidden,
}: {
  userId: string;
  workspaceId: string;
  dialog: KnowledgeDialog;
  onClose: () => void;
  onCreated: () => void;
  onDeleted: () => void;
  onForbidden: () => void;
}) {
  const t = useTranslations("knowledgeManagement");
  const base = dialog.kind === "create" ? undefined : dialog.base;
  const [name, setName] = useState(base?.name ?? "");
  const [description, setDescription] = useState(base?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const capture = useKnowledgeLease();
  const mutations = useKnowledgeBaseMutations(userId, workspaceId);
  const submit = async () => {
    if (busy.current) return;
    const trimmed = name.trim();
    if (dialog.kind !== "delete" && (!trimmed || Array.from(trimmed).length > 255)) {
      setError(t(!trimmed ? "errors.nameRequired" : "errors.nameTooLong"));
      return;
    }
    const valid = capture();
    if (!valid()) return;
    busy.current = true;
    setPending(true);
    setError(null);
    try {
      if (dialog.kind === "create")
        await mutations.create.mutateAsync({
          name: trimmed,
          description: description.trim() || null,
        });
      else if (dialog.kind === "edit")
        await mutations.update.mutateAsync({
          knowledgeBaseId: dialog.base.id,
          payload: { name: trimmed, description: description.trim() || null },
        });
      else await mutations.remove.mutateAsync(dialog.base.id);
      if (!valid()) return;
      if (dialog.kind === "create") onCreated();
      if (dialog.kind === "delete") onDeleted();
      onClose();
    } catch (failure) {
      if (!valid() || isAbort(failure)) return;
      const message = knowledgeError(failure, t);
      setError(message);
      if (failure instanceof ApiError && failure.status === 403) {
        toast.error(message);
        onClose();
        onForbidden();
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
            {t(
              dialog.kind === "create"
                ? "create"
                : dialog.kind === "edit"
                  ? "editTitle"
                  : "deleteTitle",
            )}
          </DialogTitle>
          <DialogDescription>
            {dialog.kind === "delete"
              ? t("deleteDescription", { name: base!.name })
              : t("description")}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
          className="space-y-4"
          noValidate
        >
          {dialog.kind !== "delete" && (
            <>
              <FormField label={t("name")} htmlFor="knowledge-name">
                <Input
                  id="knowledge-name"
                  value={name}
                  disabled={pending}
                  onChange={(event) => setName(event.target.value)}
                  autoComplete="off"
                  aria-required="true"
                />
              </FormField>
              <FormField label={t("descriptionLabel")} htmlFor="knowledge-description">
                <Textarea
                  id="knowledge-description"
                  value={description}
                  disabled={pending}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </FormField>
            </>
          )}
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button
              type="submit"
              variant={dialog.kind === "delete" ? "destructive" : "default"}
              disabled={pending}
            >
              {pending ? "…" : t(dialog.kind === "delete" ? "delete" : "save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  FormField,
  Input,
  Textarea,
} from "@/components/ui";
import { KnowledgeBasePicker, type KnowledgeSelectionProof } from "./knowledge-base-picker";
import {
  isKnowledgeUuid,
  normalizeKnowledgeQuery,
  validKnowledgeTopK,
} from "@/lib/workflow/knowledge-config";
import type { CanvasNode } from "@/lib/workflow/canvas-adapter";
import { parseSafeJson } from "@/lib/json-value";
import type { JsonObject } from "@/types";

export type NodeConfigurationDraft =
  | { kind: "value"; hasValue: boolean; valueText: string }
  | { kind: "agent"; instruction: string; model: string; knowledgeBaseId?: string }
  | {
      kind: "knowledge";
      knowledgeBaseId: string;
      querySource: string;
      query: string;
      inputKey: string;
      topK: string;
    }
  | { kind: "approval"; prompt: string };

export interface NodeConfigurationEditorProps {
  node: CanvasNode | null;
  scopeAuthorized?: boolean;
  userId?: string;
  workspaceId?: string;
  workflowId?: string;
  draft?: NodeConfigurationDraft;
  editable: boolean;
  disabled: boolean;
  onDraftChange: (nodeId: string, draft: NodeConfigurationDraft | null) => void;
  onApply: (nodeId: string, config: JsonObject) => void;
}

const AGENT_FIELDS = new Set(["runner", "instruction", "model", "knowledge_base_id"]);
const KNOWLEDGE_FIELDS = new Set([
  "knowledge_base_id",
  "query_source",
  "query",
  "input_key",
  "top_k",
]);
const APPROVAL_FIELDS = new Set(["prompt"]);
function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "";
}

export function draftForNode(node: CanvasNode): NodeConfigurationDraft | null {
  const { config, kind } = node.data;
  if (kind === "value") {
    const hasValue = Object.prototype.hasOwnProperty.call(config, "value");
    return { kind, hasValue, valueText: hasValue ? formatJson(config.value) : "null" };
  }
  if (kind === "agent") {
    return {
      kind,
      instruction: typeof config.instruction === "string" ? config.instruction : "",
      model: typeof config.model === "string" ? config.model : "",
      ...(Object.prototype.hasOwnProperty.call(config, "knowledge_base_id")
        ? {
            knowledgeBaseId:
              typeof config.knowledge_base_id === "string"
                ? config.knowledge_base_id
                : formatJson(config.knowledge_base_id),
          }
        : {}),
    };
  }
  if (kind === "knowledge")
    return {
      kind,
      knowledgeBaseId:
        typeof config.knowledge_base_id === "string"
          ? config.knowledge_base_id
          : config.knowledge_base_id === undefined
            ? ""
            : formatJson(config.knowledge_base_id),
      querySource: typeof config.query_source === "string" ? config.query_source : "",
      query: typeof config.query === "string" ? config.query : "",
      inputKey: typeof config.input_key === "string" ? config.input_key : "",
      topK:
        config.top_k === undefined
          ? "5"
          : typeof config.top_k === "number"
            ? String(config.top_k)
            : formatJson(config.top_k),
    };
  if (kind === "approval") {
    return { kind, prompt: typeof config.prompt === "string" ? config.prompt : "" };
  }
  return null;
}

function draftsEqual(left: NodeConfigurationDraft | null, right: NodeConfigurationDraft | null) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function unknownFields(node: CanvasNode): string[] {
  const allowed =
    node.data.kind === "agent"
      ? AGENT_FIELDS
      : node.data.kind === "knowledge"
        ? KNOWLEDGE_FIELDS
        : node.data.kind === "approval"
          ? APPROVAL_FIELDS
          : null;
  return allowed ? Object.keys(node.data.config).filter((field) => !allowed.has(field)) : [];
}

export function NodeConfigurationEditor({
  node,
  scopeAuthorized,
  userId,
  workspaceId,
  workflowId,
  draft,
  editable,
  disabled,
  onDraftChange,
  onApply,
}: NodeConfigurationEditorProps) {
  const t = useTranslations("workflows.canvas.inspector");
  const k = useTranslations("workflows.canvas.knowledge");
  const [proof, setProof] = useState<KnowledgeSelectionProof>();
  const onVerification = useCallback(
    (next: KnowledgeSelectionProof) =>
      setProof((previous) =>
        previous?.scope === next.scope &&
        previous.value === next.value &&
        previous.verified === next.verified &&
        previous.current === next.current
          ? previous
          : next,
      ),
    [],
  );
  const initialDraft = useMemo(() => (node ? draftForNode(node) : null), [node]);
  const currentDraft = draft ?? initialDraft;
  const unsupported = useMemo(() => (node ? unknownFields(node) : []), [node]);

  if (!node) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">{t("empty")}</CardContent>
      </Card>
    );
  }

  const canChange = editable && !disabled;
  const setDraft = (next: NodeConfigurationDraft) => {
    onDraftChange(node.id, draftsEqual(next, initialDraft) ? null : next);
  };

  const binding =
    currentDraft && (currentDraft.kind === "agent" || currentDraft.kind === "knowledge")
      ? (currentDraft.knowledgeBaseId ?? "")
      : "";
  const scopeKey = `${userId ?? ""}/${workspaceId ?? ""}/${workflowId ?? ""}/${node.id}`;
  const needsBinding = currentDraft?.kind === "knowledge" || Boolean(binding);
  const bindingCurrent = () =>
    Boolean(
      proof?.scope === scopeKey && proof.value === binding && proof.verified && proof.current(),
    );
  let error: string | null = null;
  let parsedValue: unknown;
  if (currentDraft?.kind === "value" && currentDraft.hasValue) {
    const result = parseSafeJson(currentDraft.valueText);
    if (result.ok) parsedValue = result.value;
    else if (result.problem === "nonFinite") error = t("nonFiniteNumber");
    else if (result.problem === "unsafeInteger") error = t("unsafeInteger");
    else if (result.problem === "precisionLoss") error = t("numericPrecisionLoss");
    else error = t("invalidJson");
  } else if (currentDraft?.kind === "agent") {
    if (!currentDraft.instruction.trim()) error = t("instructionRequired");
    else if (currentDraft.model && !currentDraft.model.trim()) error = t("modelInvalid");
  } else if (currentDraft?.kind === "approval" && !currentDraft.prompt.trim()) {
    error = t("promptRequired");
  }
  if (currentDraft?.kind === "knowledge") {
    if (!isKnowledgeUuid(binding)) error = k("invalidId");
    else if (!["literal", "workflow_input"].includes(currentDraft.querySource))
      error = k("sourceInvalid");
    else if (
      currentDraft.querySource === "literal" &&
      (!normalizeKnowledgeQuery(currentDraft.query) ||
        Array.from(normalizeKnowledgeQuery(currentDraft.query)).length > 2000)
    )
      error = k("queryInvalid");
    else if (
      currentDraft.querySource === "workflow_input" &&
      !normalizeKnowledgeQuery(currentDraft.inputKey)
    )
      error = k("inputRequired");
    else if (!validKnowledgeTopK(currentDraft.topK)) error = k("topInvalid");
  }
  if (needsBinding && !isKnowledgeUuid(binding)) error = k("invalidId");
  else if (needsBinding && !bindingCurrent()) error = error ?? k("unverified");
  if (unsupported.length) error = t("unsupportedFields", { fields: unsupported.join(", ") });

  const apply = () => {
    if (!canChange || !currentDraft || error || (needsBinding && !bindingCurrent())) return;
    const config = structuredClone(node.data.config);
    if (currentDraft.kind === "value") {
      if (currentDraft.hasValue) config.value = parsedValue;
      else delete config.value;
    } else if (currentDraft.kind === "agent") {
      config.runner = "langgraph";
      config.instruction = currentDraft.instruction;
      if (currentDraft.model.trim()) config.model = currentDraft.model;
      else delete config.model;
      if (currentDraft.knowledgeBaseId) config.knowledge_base_id = currentDraft.knowledgeBaseId;
      else delete config.knowledge_base_id;
    } else if (currentDraft.kind === "knowledge") {
      config.knowledge_base_id = currentDraft.knowledgeBaseId;
      config.query_source = currentDraft.querySource;
      config.top_k = Number(currentDraft.topK);
      if (currentDraft.querySource === "literal") {
        config.query = currentDraft.query;
        delete config.input_key;
      } else {
        config.input_key = currentDraft.inputKey;
        delete config.query;
      }
    } else {
      config.prompt = currentDraft.prompt;
    }
    onApply(node.id, config);
  };

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <FormField label={t("nodeId")} htmlFor="node-config-id">
            <Input value={node.id} readOnly disabled />
          </FormField>
          <FormField label={t("nodeKind")} htmlFor="node-config-kind">
            <Input value={node.data.kind.toUpperCase()} readOnly disabled />
          </FormField>
        </div>

        {!editable && <p className="text-muted-foreground text-sm">{t("readOnly")}</p>}

        {currentDraft?.kind === "value" && (
          <div className="space-y-4">
            <label
              className="flex items-center gap-2 text-sm font-medium"
              htmlFor="node-value-present"
            >
              <input
                id="node-value-present"
                type="checkbox"
                checked={currentDraft.hasValue}
                disabled={!canChange}
                onChange={(event) => setDraft({ ...currentDraft, hasValue: event.target.checked })}
              />
              {t("includeValue")}
            </label>
            {currentDraft.hasValue && (
              <FormField
                label={t("valueJson")}
                htmlFor="node-value-json"
                description={t("valueDescription")}
                error={error}
                required
              >
                <Textarea
                  value={currentDraft.valueText}
                  disabled={!canChange}
                  rows={8}
                  onChange={(event) => setDraft({ ...currentDraft, valueText: event.target.value })}
                />
              </FormField>
            )}
          </div>
        )}

        {currentDraft?.kind === "agent" && (
          <div className="space-y-4">
            <FormField label={t("runner")} htmlFor="node-agent-runner">
              <Input value="langgraph" readOnly disabled />
            </FormField>
            <FormField
              label={t("instruction")}
              htmlFor="node-agent-instruction"
              error={!currentDraft.instruction.trim() ? t("instructionRequired") : null}
              required
            >
              <Textarea
                value={currentDraft.instruction}
                disabled={!canChange}
                rows={6}
                onChange={(event) => setDraft({ ...currentDraft, instruction: event.target.value })}
              />
            </FormField>
            <FormField
              label={t("model")}
              htmlFor="node-agent-model"
              description={t("modelDescription")}
              error={currentDraft.model && !currentDraft.model.trim() ? t("modelInvalid") : null}
            >
              <Input
                value={currentDraft.model}
                disabled={!canChange}
                onChange={(event) => setDraft({ ...currentDraft, model: event.target.value })}
              />
            </FormField>
          </div>
        )}

        {currentDraft?.kind === "knowledge" && (
          <div className="space-y-4">
            <h4 className="font-semibold">{k("node")}</h4>
            <p>{k("evidenceOnly")}</p>
            <FormField label={k("source")} htmlFor="knowledge-query-source">
              <select
                id="knowledge-query-source"
                className="bg-background w-full rounded-md border p-2"
                value={currentDraft.querySource}
                disabled={!canChange}
                onChange={(e) =>
                  setDraft({
                    ...currentDraft,
                    querySource: e.target.value,
                    ...(e.target.value === "literal" ? { inputKey: "" } : { query: "" }),
                  })
                }
              >
                {!["literal", "workflow_input"].includes(currentDraft.querySource) && (
                  <option value={currentDraft.querySource}>{k("sourceInvalid")}</option>
                )}
                <option value="literal">{k("literal")}</option>
                <option value="workflow_input">{k("workflowInput")}</option>
              </select>
            </FormField>
            {currentDraft.querySource === "literal" && (
              <FormField label={k("query")} htmlFor="knowledge-query">
                <Textarea
                  id="knowledge-query"
                  value={currentDraft.query}
                  disabled={!canChange}
                  onChange={(e) => setDraft({ ...currentDraft, query: e.target.value })}
                />
              </FormField>
            )}
            {currentDraft.querySource === "workflow_input" && (
              <FormField label={k("inputKey")} htmlFor="knowledge-input-key">
                <Input
                  id="knowledge-input-key"
                  value={currentDraft.inputKey}
                  disabled={!canChange}
                  onChange={(e) => setDraft({ ...currentDraft, inputKey: e.target.value })}
                />
              </FormField>
            )}
            <FormField label={k("topK")} htmlFor="knowledge-top-k">
              <Input
                id="knowledge-top-k"
                inputMode="numeric"
                value={currentDraft.topK}
                disabled={!canChange}
                onChange={(e) => setDraft({ ...currentDraft, topK: e.target.value })}
              />
            </FormField>
          </div>
        )}
        {(currentDraft?.kind === "agent" || currentDraft?.kind === "knowledge") &&
          userId &&
          workspaceId && (
            <KnowledgeBasePicker
              key={scopeKey}
              scope={scopeKey}
              authorized={scopeAuthorized}
              userId={userId}
              workspaceId={workspaceId}
              value={binding}
              disabled={!canChange}
              optional={currentDraft.kind === "agent"}
              onVerification={onVerification}
              onChange={(value) => {
                if (currentDraft.kind === "knowledge")
                  setDraft({ ...currentDraft, knowledgeBaseId: value });
                else {
                  const next = { ...currentDraft };
                  if (value) next.knowledgeBaseId = value;
                  else delete next.knowledgeBaseId;
                  setDraft(next);
                }
              }}
            />
          )}
        {error && currentDraft?.kind === "knowledge" && <p role="alert">{error}</p>}
        {currentDraft?.kind === "approval" && (
          <FormField
            label={t("prompt")}
            htmlFor="node-approval-prompt"
            error={!currentDraft.prompt.trim() ? t("promptRequired") : null}
            required
          >
            <Textarea
              value={currentDraft.prompt}
              disabled={!canChange}
              rows={5}
              onChange={(event) => setDraft({ ...currentDraft, prompt: event.target.value })}
            />
          </FormField>
        )}

        {(node.data.kind === "start" || node.data.kind === "end") && (
          <p className="text-muted-foreground text-sm">{t("noConfig")}</p>
        )}

        {unsupported.length > 0 && (
          <p role="alert" className="text-destructive text-sm">
            {t("unsupportedFields", { fields: unsupported.join(", ") })}
          </p>
        )}

        {currentDraft && (
          <Button
            type="button"
            className="w-full"
            disabled={!canChange || !draft || Boolean(error)}
            onClick={apply}
          >
            {t("apply")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

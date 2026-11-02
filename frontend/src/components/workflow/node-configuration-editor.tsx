"use client";

import { useMemo } from "react";
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
import type { CanvasNode } from "@/lib/workflow/canvas-adapter";
import { parseSafeJson } from "@/lib/json-value";
import type { JsonObject } from "@/types";

export type NodeConfigurationDraft =
  | { kind: "value"; hasValue: boolean; valueText: string }
  | { kind: "agent"; instruction: string; model: string }
  | { kind: "approval"; prompt: string };

export interface NodeConfigurationEditorProps {
  node: CanvasNode | null;
  draft?: NodeConfigurationDraft;
  editable: boolean;
  disabled: boolean;
  onDraftChange: (nodeId: string, draft: NodeConfigurationDraft | null) => void;
  onApply: (nodeId: string, config: JsonObject) => void;
}

const AGENT_FIELDS = new Set(["runner", "instruction", "model"]);
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
    };
  }
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
      : node.data.kind === "approval"
        ? APPROVAL_FIELDS
        : null;
  return allowed ? Object.keys(node.data.config).filter((field) => !allowed.has(field)) : [];
}

export function NodeConfigurationEditor({
  node,
  draft,
  editable,
  disabled,
  onDraftChange,
  onApply,
}: NodeConfigurationEditorProps) {
  const t = useTranslations("workflows.canvas.inspector");
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
  if (unsupported.length) error = t("unsupportedFields", { fields: unsupported.join(", ") });

  const apply = () => {
    if (!canChange || !currentDraft || error) return;
    const config = structuredClone(node.data.config);
    if (currentDraft.kind === "value") {
      if (currentDraft.hasValue) config.value = parsedValue;
      else delete config.value;
    } else if (currentDraft.kind === "agent") {
      config.runner = "langgraph";
      config.instruction = currentDraft.instruction;
      if (currentDraft.model.trim()) config.model = currentDraft.model;
      else delete config.model;
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

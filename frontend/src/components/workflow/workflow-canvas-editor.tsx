"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import { AlertTriangle, CheckCircle2, RotateCcw, Save, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useWorkflowMutations, useWorkspaceMembers } from "@/hooks";
import { ApiError, getApiErrorMessage } from "@/lib/api-client";
import { fromCanvasGraph, toCanvasGraph, type CanvasGraph } from "@/lib/workflow/canvas-adapter";
import type { ConnectionProblem } from "@/lib/workflow/canvas-rules";
import { workflowApi } from "@/lib/workflow/workflow-api";
import type { WorkflowRead, WorkflowValidationRead } from "@/types";

import { WorkflowCanvas, type WorkflowCanvasProps } from "./workflow-canvas";

export interface WorkflowCanvasEditorProps {
  workflow: WorkflowRead;
  userId: string;
  onDirtyChange?: (dirty: boolean) => void;
  onSaved?: (workflow: WorkflowRead) => void;
  CanvasComponent?: ComponentType<WorkflowCanvasProps>;
}

type EditorOperation = "idle" | "validating" | "saving";

interface EditorRequest {
  id: number;
  workflowId: string;
  revision: number;
}

function withPresentationState(current: CanvasGraph, next: CanvasGraph): CanvasGraph {
  const nextNodes = new Map(next.nodes.map((node) => [node.id, node]));
  const nextEdges = new Map(next.edges.map((edge) => [edge.id, edge.selected]));
  return {
    nodes: current.nodes.map((node) => {
      const nextNode = nextNodes.get(node.id);
      if (!nextNode) return node;
      return {
        ...node,
        selected: nextNode.selected,
        measured: nextNode.measured ?? node.measured,
      };
    }),
    edges: current.edges.map((edge) => ({ ...edge, selected: nextEdges.get(edge.id) })),
  };
}

function requestError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return getApiErrorMessage(error.data, error.message || fallback);
  return error instanceof Error ? error.message : fallback;
}

export function WorkflowCanvasEditor({
  workflow,
  userId,
  onDirtyChange,
  onSaved,
  CanvasComponent = WorkflowCanvas,
}: WorkflowCanvasEditorProps) {
  const t = useTranslations("workflows.canvas");
  const members = useWorkspaceMembers(userId, workflow.workspace_id);
  const mutations = useWorkflowMutations(userId, workflow.workspace_id);
  const [savedWorkflow, setSavedWorkflow] = useState(workflow);
  const [canvas, setCanvas] = useState<CanvasGraph>(() => toCanvasGraph(workflow.definition));
  const [dirty, setDirty] = useState(false);
  const [validation, setValidation] = useState<WorkflowValidationRead | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [operation, setOperation] = useState<EditorOperation>("idle");
  const [remoteRevision, setRemoteRevision] = useState<number | null>(null);
  const workflowIdRef = useRef(workflow.id);
  const latestWorkflowRef = useRef(workflow);
  const mountedRef = useRef(true);
  const operationRef = useRef<EditorOperation>("idle");
  const requestIdRef = useRef(0);
  latestWorkflowRef.current = workflow;

  const membership = members.data?.find((member) => member.user_id === userId);
  const canEdit = members.isSuccess && Boolean(membership);
  const permissionLoading = members.isLoading;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      operationRef.current = "idle";
    };
  }, []);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (workflow.id !== workflowIdRef.current) {
      workflowIdRef.current = workflow.id;
      requestIdRef.current += 1;
      operationRef.current = "idle";
      setOperation("idle");
      setSavedWorkflow(workflow);
      setCanvas(toCanvasGraph(workflow.definition));
      setDirty(false);
      setValidation(null);
      setValidationError(null);
      setSaveError(null);
      setRemoteRevision(null);
      return;
    }
    if (workflow.revision === savedWorkflow.revision) return;
    if (dirty) {
      setRemoteRevision(workflow.revision);
      return;
    }
    setSavedWorkflow(workflow);
    setCanvas(toCanvasGraph(workflow.definition));
    setValidation(null);
    setRemoteRevision(null);
  }, [dirty, savedWorkflow.revision, workflow]);

  const currentGraph = useCallback(
    () => fromCanvasGraph(savedWorkflow.definition, canvas),
    [canvas, savedWorkflow.definition],
  );

  const beginOperation = useCallback(
    (next: Exclude<EditorOperation, "idle">): EditorRequest | null => {
      if (operationRef.current !== "idle") return null;
      operationRef.current = next;
      setOperation(next);
      return {
        id: ++requestIdRef.current,
        workflowId: savedWorkflow.id,
        revision: savedWorkflow.revision,
      };
    },
    [savedWorkflow.id, savedWorkflow.revision],
  );

  const finishOperation = useCallback((request: EditorRequest) => {
    if (!mountedRef.current || requestIdRef.current !== request.id) return;
    operationRef.current = "idle";
    setOperation("idle");
  }, []);

  const isCurrentRequest = useCallback((request: EditorRequest, checkRevision = true) => {
    const latest = latestWorkflowRef.current;
    return (
      mountedRef.current &&
      requestIdRef.current === request.id &&
      latest.id === request.workflowId &&
      (!checkRevision || latest.revision === request.revision)
    );
  }, []);

  const validateSnapshot = useCallback(
    async (graph: ReturnType<typeof currentGraph>, request: EditorRequest) => {
      try {
        const result = await workflowApi.validateWorkflow(graph);
        if (!isCurrentRequest(request)) return null;
        setValidation(result);
        return result;
      } catch (error) {
        if (!isCurrentRequest(request)) return null;
        setValidation(null);
        setValidationError(requestError(error, t("validationServiceFailed")));
        return null;
      }
    },
    [isCurrentRequest, t],
  );

  const runValidation = useCallback(async (): Promise<WorkflowValidationRead | null> => {
    const request = beginOperation("validating");
    if (!request) return null;
    const graph = currentGraph();
    setValidationError(null);
    try {
      return await validateSnapshot(graph, request);
    } finally {
      finishOperation(request);
    }
  }, [beginOperation, currentGraph, finishOperation, validateSnapshot]);

  const issues = useMemo(() => validation?.issues ?? [], [validation]);
  const invalidNodeIds = useMemo(
    () => new Set(issues.flatMap((issue) => (issue.node_id ? [issue.node_id] : []))),
    [issues],
  );
  const invalidEdgeIds = useMemo(
    () => new Set(issues.flatMap((issue) => (issue.edge_id ? [issue.edge_id] : []))),
    [issues],
  );

  const changeCanvas = useCallback(
    (next: CanvasGraph, marksDirty: boolean) => {
      if (marksDirty && (!canEdit || operationRef.current !== "idle")) return;
      setCanvas((current) => (marksDirty ? next : withPresentationState(current, next)));
      if (marksDirty) {
        setDirty(true);
        setValidation(null);
        setValidationError(null);
        setSaveError(null);
      }
    },
    [canEdit],
  );

  const save = async () => {
    if (
      !canEdit ||
      !dirty ||
      remoteRevision !== null ||
      latestWorkflowRef.current.revision !== savedWorkflow.revision
    )
      return;
    const request = beginOperation("saving");
    if (!request) return;
    const graph = currentGraph();
    setSaveError(null);
    setValidationError(null);
    try {
      const result = await validateSnapshot(graph, request);
      if (!result?.is_valid || !isCurrentRequest(request)) return;
      const updated = await mutations.update.mutateAsync({
        workflowId: savedWorkflow.id,
        payload: { definition: graph },
      });
      if (!isCurrentRequest(request, false)) return;
      setSavedWorkflow(updated);
      setCanvas(toCanvasGraph(updated.definition));
      setDirty(false);
      setRemoteRevision(null);
      setValidation(result);
      onSaved?.(updated);
    } catch (error) {
      if (!isCurrentRequest(request, false)) return;
      setSaveError(requestError(error, t("saveFailed")));
    } finally {
      finishOperation(request);
    }
  };

  const discard = () => {
    if (operationRef.current !== "idle") return;
    setCanvas(toCanvasGraph(savedWorkflow.definition));
    setDirty(false);
    setValidation(null);
    setValidationError(null);
    setSaveError(null);
  };

  const reloadServerVersion = () => {
    if (operationRef.current !== "idle") return;
    setSavedWorkflow(workflow);
    setCanvas(toCanvasGraph(workflow.definition));
    setDirty(false);
    setValidation(null);
    setValidationError(null);
    setSaveError(null);
    setRemoteRevision(null);
  };

  const rejectConnection = (problem: ConnectionProblem) => {
    if (operationRef.current !== "idle") return;
    setValidation(null);
    setValidationError(t(`connectionProblems.${problem}`));
  };

  return (
    <section className="space-y-4" aria-label={t("title")}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-display text-lg font-semibold">{t("title")}</h2>
            {dirty ? (
              <span className="rounded-full bg-amber-500/15 px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                {t("unsaved")}
              </span>
            ) : (
              <span className="text-muted-foreground text-xs">{t("saved")}</span>
            )}
          </div>
          <p className="text-muted-foreground text-sm">{t("description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={operation !== "idle"}
            onClick={() => void runValidation()}
          >
            {operation === "validating" ? t("validating") : t("validate")}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!dirty || operation !== "idle"}
            onClick={discard}
          >
            <RotateCcw className="h-4 w-4" />
            {t("discard")}
          </Button>
          <Button
            type="button"
            disabled={
              !canEdit ||
              !dirty ||
              remoteRevision !== null ||
              operation !== "idle" ||
              mutations.update.isPending
            }
            onClick={() => void save()}
          >
            <Save className="h-4 w-4" />
            {operation === "saving" || mutations.update.isPending ? t("saving") : t("save")}
          </Button>
        </div>
      </div>

      {permissionLoading && <StatusMessage>{t("checkingPermission")}</StatusMessage>}
      {members.isError && (
        <StatusMessage destructive icon={<ShieldAlert className="h-4 w-4" />}>
          {t("permissionFailed")}
        </StatusMessage>
      )}
      {!permissionLoading && !members.isError && !membership && (
        <StatusMessage destructive icon={<ShieldAlert className="h-4 w-4" />}>
          {t("readOnly")}
        </StatusMessage>
      )}
      {remoteRevision !== null && (
        <StatusMessage destructive icon={<AlertTriangle className="h-4 w-4" />}>
          <span>{t("remoteRevision", { revision: remoteRevision })}</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={operation !== "idle"}
            onClick={reloadServerVersion}
          >
            {t("reload")}
          </Button>
        </StatusMessage>
      )}
      {validation?.is_valid && (
        <StatusMessage icon={<CheckCircle2 className="h-4 w-4" />}>{t("valid")}</StatusMessage>
      )}
      {validation && !validation.is_valid && (
        <StatusMessage destructive icon={<AlertTriangle className="h-4 w-4" />}>
          <div>
            <p className="font-medium">{t("invalid")}</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
              {issues.map((issue, index) => (
                <li key={`${issue.code}-${issue.node_id}-${issue.edge_id}-${index}`}>
                  {issue.message}
                  {issue.node_id && ` [node: ${issue.node_id}]`}
                  {issue.edge_id && ` [edge: ${issue.edge_id}]`}
                </li>
              ))}
            </ul>
          </div>
        </StatusMessage>
      )}
      {validationError && <StatusMessage destructive>{validationError}</StatusMessage>}
      {saveError && <StatusMessage destructive>{saveError}</StatusMessage>}

      <CanvasComponent
        graph={canvas}
        editable={canEdit && operation === "idle" && !mutations.update.isPending}
        invalidNodeIds={invalidNodeIds}
        invalidEdgeIds={invalidEdgeIds}
        onChange={changeCanvas}
        onConnectionRejected={rejectConnection}
        labels={{
          addValue: t("addValue"),
          deleteNode: t("deleteNode"),
          deleteEdge: t("deleteEdge"),
        }}
      />
    </section>
  );
}

function StatusMessage({
  children,
  destructive = false,
  icon,
}: {
  children: React.ReactNode;
  destructive?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <div
      role={destructive ? "alert" : "status"}
      className={
        destructive
          ? "border-destructive/30 bg-destructive/5 text-destructive flex items-center gap-2 rounded-lg border p-3"
          : "bg-muted/30 flex items-center gap-2 rounded-lg border p-3 text-sm"
      }
    >
      {icon}
      {children}
    </div>
  );
}

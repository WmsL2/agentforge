import { expect, type Page, type Route } from "@playwright/test";
import type * as K from "../../src/types/knowledge";
import type {
  WorkflowGraph,
  WorkflowRead,
  WorkflowRunRead,
  RunStepRead,
  TraceEventRead,
} from "../../src/types/workflow";

export const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
export const WS = id(1),
  WS2 = id(2),
  KB = id(10),
  FOREIGN = id(11),
  DOC = id(20),
  WF = id(40);
export const TEXT = "Browser evidence: growth depends on body length.\n";
export const USER = {
  id: id(100),
  email: "browser-fixture@example.test",
  full_name: "Browser Fixture",
  is_active: true,
  role: "user",
  created_at: "2026-11-24T00:00:00Z",
  onboarding_completed_at: "2026-11-24T00:00:00Z",
  access_token: "controlled-browser-only",
};
const timestamp = "2026-11-24T00:00:00Z";
export const base = (
  key = KB,
  workspace_id = WS,
  name = "Browser knowledge",
): K.KnowledgeBaseRead => ({
  id: key,
  workspace_id,
  name,
  description: "Synthetic browser fixture",
  created_by_user_id: USER.id,
  created_at: timestamp,
  updated_at: null,
});
export const document = (): K.KnowledgeDocumentRead => ({
  id: DOC,
  workspace_id: WS,
  knowledge_base_id: KB,
  created_by_user_id: USER.id,
  filename: "证据.txt",
  mime_type: "text/plain",
  size_bytes: Buffer.byteLength(TEXT),
  sha256: "0".repeat(64),
  parse_status: "ready",
  parse_error_code: null,
  page_count: 1,
  parse_metadata: {},
  created_at: timestamp,
  updated_at: null,
});
export const source = {
  chunk_id: id(21),
  document_id: DOC,
  filename: "证据.txt",
  page_start: 1,
  page_end: null,
  similarity_score: 0.75,
};
export function graph(mode: "explicit" | "bound" | "ordinary" = "ordinary"): WorkflowGraph {
  const kinds =
    mode === "explicit"
      ? (["start", "knowledge", "agent", "end"] as const)
      : (["start", "agent", "end"] as const);
  const nodes = kinds.map((kind, i) => ({
    id: kind,
    kind,
    config:
      kind === "agent"
        ? {
            runner: "langgraph",
            instruction: "Answer using evidence",
            ...(mode === "bound" ? { knowledge_base_id: KB } : {}),
          }
        : kind === "knowledge"
          ? { knowledge_base_id: KB, query_source: "literal", query: "growth", top_k: 5 }
          : {},
    metadata: { position: { x: i * 240, y: 0 } },
  }));
  return {
    entry_node_id: "start",
    nodes,
    edges: nodes.slice(1).map((node, i) => ({
      id: `e${i}`,
      source: nodes[i]!.id,
      target: node.id,
      condition: null,
      metadata: {},
    })),
    schema_version: 1,
    metadata: { fixture: "preserve" },
  };
}
function valid(graph: WorkflowGraph) {
  if (!graph.nodes?.length || !graph.edges || graph.schema_version !== 1) return false;
  const reached = new Set<string>();
  const active = new Set<string>();
  const visit = (key: string): boolean => {
    if (active.has(key)) return false;
    if (reached.has(key)) return true;
    if (!graph.nodes.some((n) => n.id === key)) return false;
    reached.add(key);
    active.add(key);
    for (const edge of graph.edges.filter((e) => e.source === key))
      if (!visit(edge.target)) return false;
    active.delete(key);
    return true;
  };
  return (
    new Set(graph.nodes.map((n) => n.id)).size === graph.nodes.length &&
    visit(graph.entry_node_id) &&
    reached.size === graph.nodes.length &&
    graph.nodes.every(
      (n) =>
        n.kind !== "knowledge" ||
        (n.config.knowledge_base_id === KB &&
          Number.isInteger(n.config.top_k) &&
          Number(n.config.top_k) >= 1 &&
          Number(n.config.top_k) <= 5 &&
          (n.config.query_source === "literal"
            ? typeof n.config.query === "string" &&
              n.config.query.trim() &&
              !("input_key" in n.config)
            : n.config.query_source === "workflow_input" &&
              typeof n.config.input_key === "string" &&
              n.config.input_key.trim() &&
              !("query" in n.config))),
    )
  );
}
export function initial(mode: "explicit" | "bound" | "ordinary" = "ordinary") {
  const workflow: WorkflowRead = {
    id: WF,
    workspace_id: WS,
    user_id: USER.id,
    name: "Browser workflow",
    description: "Synthetic",
    definition: graph(mode),
    revision: 3,
    created_at: timestamp,
    updated_at: null,
  };
  return {
    role: "owner" as "owner" | "admin" | "member",
    bases: [base(), base(FOREIGN, WS2, "Other workspace secret")],
    documents: [] as K.KnowledgeDocumentRead[],
    workflow,
    runs: [] as WorkflowRunRead[],
    steps: {} as Record<string, RunStepRead[]>,
    traces: {} as Record<string, TraceEventRead[]>,
    runPhase: "pending" as WorkflowRunRead["status"],
    indexPhase: "not_indexed" as K.KnowledgeIndexStatus,
    generation: null as string | null,
    job: null as K.KnowledgeIndexJobRead | null,
    searchError: false,
    emptySearch: false,
    askStatus: "answered" as K.KnowledgeAskStatus,
    missingSources: false,
    validated: "",
    calls: [] as { method: string; path: string; query: string; body: unknown }[],
    unexpected: [] as string[],
    denySteps: 0,
    indexPosts: 0,
    patches: 0,
  };
}
export type BrowserState = ReturnType<typeof initial>;
const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
export async function install(page: Page, state: BrowserState) {
  // Same controlled authentication surface as the existing workflow browser spec.
  // This never replaces or disables the real setup project dependency.
  await page.addInitScript(
    (user) =>
      localStorage.setItem(
        "auth-storage",
        JSON.stringify({ state: { user, isAuthenticated: true }, version: 0 }),
      ),
    USER,
  );
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    return url.origin === new URL(process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000").origin
      ? route.continue()
      : route.abort();
  });
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname,
      method = req.method();
    const multipart = req.headers()["content-type"]?.startsWith("multipart/form-data");
    const body: unknown = multipart
      ? req.postDataBuffer()?.toString("utf8")
      : req.postData()
        ? req.postDataJSON()
        : undefined;
    state.calls.push({ method, path, query: url.search, body });
    if (path === "/api/auth/me") return json(route, 200, USER);
    const workspaces = [WS, WS2].map((key, i) => ({
      id: key,
      name: `Browser workspace ${i + 1}`,
      description: null,
      owner_id: USER.id,
      created_at: timestamp,
      updated_at: null,
    }));
    if (path === "/api/workspaces") return json(route, 200, { items: workspaces, total: 2 });
    if (/^\/api\/workspaces\/[^/]+\/members$/.test(path))
      return json(route, 200, [
        {
          workspace_id: path.split("/")[3],
          user_id: USER.id,
          role: state.role,
          created_at: timestamp,
          updated_at: null,
        },
      ]);
    if (workspaces.some((w) => path === `/api/workspaces/${w.id}`))
      return json(
        route,
        200,
        workspaces.find((w) => path.endsWith(w.id)),
      );
    const match = path.match(
      /^\/api\/workspaces\/([^/]+)\/knowledge-bases(?:\/([^/]+))?(?:\/(.*))?$/,
    );
    if (match) {
      const [, ws, key, tail] = match;
      if (method !== "GET" && state.role === "member" && !["search", "ask"].includes(tail ?? ""))
        return json(route, 403, { detail: "Forbidden" });
      if (!key) {
        if (method === "GET") {
          const rows = state.bases.filter((b) => b.workspace_id === ws);
          const skip = Number(url.searchParams.get("skip") ?? 0);
          const limit = Number(url.searchParams.get("limit") ?? 50);
          return json(route, 200, { items: rows.slice(skip, skip + limit), total: rows.length });
        }
        if (method === "POST") {
          const data = body as K.KnowledgeBaseCreate;
          const created = {
            ...base(id(12), ws),
            name: data.name,
            description: data.description ?? null,
          };
          state.bases.push(created);
          return json(route, 201, created);
        }
      }
      const selected = state.bases.find((b) => b.id === key && b.workspace_id === ws);
      if (!selected) return json(route, 404, { detail: "Not found" });
      if (!tail) {
        if (method === "GET") return json(route, 200, selected);
        if (method === "PATCH") {
          Object.assign(selected, body);
          return json(route, 200, selected);
        }
        if (method === "DELETE") {
          state.bases = state.bases.filter((b) => b.id !== key);
          return route.fulfill({ status: 204 });
        }
      }
      if (tail === "search")
        return state.searchError
          ? json(route, 503, { detail: "PRIVATE_PROVIDER_DETAIL" })
          : json(route, 200, {
              query: (body as K.KnowledgeSearchRequest).query,
              total: state.emptySearch ? 0 : 1,
              embedding_model: "fixture-embedding",
              results: state.emptySearch
                ? []
                : [
                    {
                      ...source,
                      knowledge_base_id: key,
                      chunk_index: 0,
                      content:
                        '<img src="https://invalid.test/x" onerror="bad()"> Browser evidence',
                      start_offset: 0,
                      end_offset: 80,
                    },
                  ],
            });
      if (tail === "ask")
        return json(route, 200, {
          answer: "Actual fixture answer [invented citation 999]",
          status: state.askStatus,
          sources: state.askStatus === "no_evidence" || state.missingSources ? [] : [source],
        });
      if (tail === "documents") {
        if (method === "GET")
          return json(route, 200, {
            items: state.documents.filter(
              (d) => d.workspace_id === ws && d.knowledge_base_id === key,
            ),
            total: state.documents.filter(
              (d) => d.workspace_id === ws && d.knowledge_base_id === key,
            ).length,
          });
        if (method === "POST") {
          expect(multipart).toBe(true);
          expect(String(body)).toContain('name="file"');
          expect(String(body)).toContain(TEXT);
          state.documents.push(document());
          return json(route, 201, state.documents[0]);
        }
      }
      if (tail?.startsWith(`documents/${DOC}`) && state.documents.length) {
        const doc = state.documents[0]!;
        if (tail.endsWith("/download"))
          return route.fulfill({
            status: 200,
            contentType: "text/plain",
            headers: {
              "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(doc.filename)}`,
            },
            body: Buffer.from(TEXT),
          });
        if (tail.endsWith("/content"))
          return json(route, 200, {
            document_id: DOC,
            content: TEXT,
            page_count: 1,
            parse_metadata: {},
          });
        if (tail.endsWith("/index")) {
          if (method === "POST") {
            state.indexPosts++;
            state.indexPhase = "pending";
            state.job = {
              id: id(60 + state.indexPosts),
              document_id: DOC,
              status: "pending",
              embedding_model: "fixture-embedding",
              embedding_dimensions: 1536,
              index_generation_id: id(70 + state.indexPosts),
              chunking_config_version: "v1",
              attempt_count: 0,
              error_code: null,
              created_at: timestamp,
            };
            return json(route, 202, state.job);
          }
          if (state.indexPhase === "succeeded")
            state.generation = state.job?.index_generation_id ?? id(70);
          return json(route, 200, {
            document_id: DOC,
            job_id: state.job?.id ?? null,
            status: state.indexPhase,
            active_generation_id: state.generation,
            chunk_count: state.generation ? 1 : 0,
            embedding_model: state.generation ? "fixture-embedding" : null,
            index_version: state.generation ? "v1" : null,
            error_code: state.indexPhase === "failed" ? "EMBEDDING_TIMEOUT" : null,
          });
        }
        if (method === "DELETE") {
          state.documents = [];
          return route.fulfill({ status: 204 });
        }
        return json(route, 200, doc);
      }
    }
    if (path === "/api/workflows/validate") {
      const definition = body as WorkflowGraph,
        ok = valid(definition);
      if (ok) state.validated = JSON.stringify(definition);
      return json(route, 200, {
        is_valid: ok,
        issues: ok
          ? []
          : [
              {
                code: "isolated_node",
                message: "Controlled fixture rejected an invalid graph",
                node_id: null,
                edge_id: null,
              },
            ],
      });
    }
    if (path === `/api/workflows/${WF}`) {
      if (method === "PATCH") {
        const definition = (body as { definition: WorkflowGraph }).definition;
        if (!valid(definition) || JSON.stringify(definition) !== state.validated)
          return json(route, 422, { detail: "Validate before save" });
        state.workflow.definition = structuredClone(definition);
        state.workflow.revision++;
        state.patches++;
      }
      return json(route, 200, state.workflow);
    }
    if (path === `/api/workflows/${WF}/runs/async` && method === "POST") {
      const run: WorkflowRunRead = {
        id: id(80 + state.runs.length),
        workflow_id: WF,
        workflow_revision: state.workflow.revision,
        definition_snapshot: structuredClone(state.workflow.definition),
        status: "pending",
        input: (body as { input: Record<string, unknown> }).input,
        node_outputs: {},
        output: null,
        error: null,
        started_at: null,
        finished_at: null,
        created_at: timestamp,
        updated_at: null,
      };
      state.runs.unshift(run);
      return json(route, 202, run);
    }
    if (path === `/api/workflows/${WF}/runs`)
      return json(route, 200, { items: state.runs, total: state.runs.length });
    const runMatch = path.match(
      new RegExp(`^/api/workflows/${WF}/runs/([^/]+)(?:/(steps|trace))?$`),
    );
    if (runMatch) {
      const run = state.runs.find((r) => r.id === runMatch[1]);
      if (!run) return json(route, 404, { detail: "Not found" });
      if (runMatch[2] === "steps")
        return state.denySteps
          ? json(route, state.denySteps, { detail: "unavailable" })
          : json(route, 200, state.steps[run.id] ?? []);
      if (runMatch[2] === "trace") return json(route, 200, state.traces[run.id] ?? []);
      run.status = state.runPhase;
      return json(route, 200, run);
    }
    state.unexpected.push(`${method} ${path}`);
    return json(route, 404, { detail: "Unconfigured controlled endpoint" });
  });
}
export function complete(state: BrowserState) {
  const run = state.runs[0]!;
  state.runPhase = "completed";
  run.finished_at = timestamp;
  state.steps[run.id] = run.definition_snapshot.nodes
    .filter((n) => ["knowledge", "agent"].includes(n.kind))
    .map((node, i) => ({
      id: id(90 + i),
      run_id: run.id,
      sequence: i + 1,
      node_id: node.id,
      node_kind: node.kind,
      status: "completed",
      input: {},
      output:
        node.kind === "knowledge"
          ? { query: "growth", total: 1, results: [{ ...source, content: TEXT }] }
          : "knowledge_base_id" in node.config
            ? {
                answer: "Actual workflow answer",
                status: state.askStatus,
                sources: state.askStatus === "no_evidence" ? [] : [source],
              }
            : { ordinary: "ordinary Agent output" },
      error: null,
      metadata: {},
      started_at: timestamp,
      finished_at: timestamp,
      duration_ms: 0,
    }));
  state.traces[run.id] = [
    {
      id: id(99),
      run_id: run.id,
      step_id: null,
      kind: "node_completed",
      payload: { fixture: "trace only; never sources" },
      created_at: timestamp,
    },
  ];
}

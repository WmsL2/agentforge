/**
 * Centralized, typed React Query key factory.
 *
 * One source of truth for cache keys so queries dedupe and
 * mutations can invalidate precisely.
 */
export const qk = {
  auth: {
    me: () => ["auth", "me"] as const,
  },

  health: () => ["health"] as const,

  organizations: {
    all: () => ["organizations"] as const,

    list: () => ["organizations", "list"] as const,

    members: (orgId: string) => ["organizations", orgId, "members"] as const,
  },

  invitations: {
    all: () => ["invitations"] as const,

    list: (orgId: string) => ["invitations", orgId] as const,
  },

  billing: {
    all: () => ["billing"] as const,

    credits: () => ["billing", "credits"] as const,

    creditsTransactions: () => ["billing", "credits", "transactions"] as const,

    subscription: () => ["billing", "subscription"] as const,

    invoices: () => ["billing", "invoices"] as const,

    paymentMethods: () => ["billing", "payment-methods"] as const,

    usageTimeline: (days: number) => ["billing", "usage", "timeline", days] as const,
  },

  conversations: {
    all: () => ["conversations"] as const,

    list: () => ["conversations", "list"] as const,

    count: () => ["conversations", "count"] as const,

    messages: (id: string) => ["conversations", id, "messages"] as const,
  },

  workspaces: {
    all: (userId: string) => ["workspaces", userId] as const,

    list: (userId: string) => ["workspaces", userId, "list"] as const,

    detail: (userId: string, workspaceId: string) =>
      ["workspaces", userId, "detail", workspaceId] as const,

    members: (userId: string, workspaceId: string) =>
      ["workspaces", userId, "members", workspaceId] as const,
  },

  workflows: {
    all: (userId: string) => ["workflows", userId] as const,

    workspace: (userId: string, workspaceId: string) =>
      ["workflows", userId, "workspace", workspaceId] as const,

    list: (userId: string, workspaceId: string, skip: number, limit: number) =>
      ["workflows", userId, "workspace", workspaceId, "list", skip, limit] as const,

    detail: (userId: string, workflowId: string) =>
      ["workflows", userId, "detail", workflowId] as const,
  },

  workflowRuns: {
    workflow: (userId: string, workflowId: string) =>
      ["workflow-runs", userId, workflowId] as const,

    list: (userId: string, workflowId: string, skip: number, limit: number) =>
      ["workflow-runs", userId, workflowId, "list", skip, limit] as const,

    detail: (userId: string, workflowId: string, runId: string) =>
      ["workflow-runs", userId, workflowId, "detail", runId] as const,

    steps: (userId: string, workflowId: string, runId: string) =>
      ["workflow-runs", userId, workflowId, "steps", runId] as const,

    trace: (userId: string, workflowId: string, runId: string) =>
      ["workflow-runs", userId, workflowId, "trace", runId] as const,

    approval: (userId: string, workflowId: string, runId: string) =>
      ["workflow-runs", userId, workflowId, "approval", runId] as const,
  },

  knowledge: {
    root: () => ["knowledge"] as const,
    user: (u: string) => ["knowledge", u] as const,
    workspace: (u: string, w: string) => ["knowledge", u, w] as const,
    lists: (u: string, w: string) => ["knowledge", u, w, "list"] as const,
    list: (u: string, w: string, skip = 0, limit = 50) =>
      ["knowledge", u, w, "list", skip, limit] as const,
    base: (u: string, w: string, b: string) => ["knowledge", u, w, "base", b] as const,
    documentLists: (u: string, w: string, b: string) =>
      ["knowledge", u, w, "base", b, "documents"] as const,
    documents: (u: string, w: string, b: string, skip = 0, limit = 50) =>
      ["knowledge", u, w, "base", b, "documents", skip, limit] as const,
    document: (u: string, w: string, b: string, d: string) =>
      ["knowledge", u, w, "base", b, "document", d] as const,
    content: (u: string, w: string, b: string, d: string) =>
      ["knowledge", u, w, "base", b, "document", d, "content"] as const,
    index: (u: string, w: string, b: string, d: string) =>
      ["knowledge", u, w, "base", b, "document", d, "index"] as const,
  },

  kb: {
    all: () => ["kb"] as const,

    list: () => ["kb", "list"] as const,

    detail: (id: string) => ["kb", id] as const,

    documents: (id: string) => ["kb", id, "documents"] as const,
  },

  rag: {
    stats: () => ["rag", "stats"] as const,

    collections: () => ["rag", "collections"] as const,
  },

  admin: {
    stats: () => ["admin", "stats"] as const,

    events: () => ["admin", "events"] as const,

    users: (params?: unknown) => ["admin", "users", params] as const,

    conversations: (params?: unknown) => ["admin", "conversations", params] as const,
  },
} as const;

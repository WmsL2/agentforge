import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { aborted, authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { qk } from "@/lib/query-keys";

const requests = new Set<{ key: QueryKey; controller: AbortController }>();
const clients = new Set<QueryClient>();
const listeners = new Set<(prefix: QueryKey) => void>();
export const within = (key: QueryKey, prefix: QueryKey) => prefix.every((v, i) => key[i] === v);

/** Invalidate leases synchronously before cancelling/removing cached data. */
export function clearKnowledgeScope(client: QueryClient, prefix: QueryKey) {
  for (const request of requests) if (within(request.key, prefix)) request.controller.abort();
  for (const listener of listeners) listener(prefix);
  void client.cancelQueries({ queryKey: prefix });
  client.removeQueries({ queryKey: prefix });
  for (const mutation of client.getMutationCache().getAll()) {
    if (
      within(
        (mutation.state.variables as { resourceKey?: QueryKey } | undefined)?.resourceKey ??
          mutation.options.mutationKey ??
          [],
        prefix,
      )
    )
      client.getMutationCache().remove(mutation);
  }
}

export function bindKnowledgeLifecycle(client: QueryClient) {
  clients.add(client);
  const unsubscribe = useAuthStore.subscribe((state, previous) => {
    if (
      state.user?.id !== previous.user?.id ||
      state.isAuthenticated !== previous.isAuthenticated
    ) {
      if (previous.user?.id) clearKnowledgeScope(client, qk.knowledge.user(previous.user.id));
    }
  });
  return () => {
    clients.delete(client);
    unsubscribe();
  };
}

export function confirmedKnowledgeWorkspaceLoss(userId: string, workspaceId: string) {
  for (const client of clients)
    clearKnowledgeScope(client, qk.knowledge.workspace(userId, workspaceId));
}

export function onKnowledgeClear(listener: (prefix: QueryKey) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export async function knowledgeRequest<T>(
  key: QueryKey,
  signal: AbortSignal | undefined,
  run: (signal: AbortSignal, valid: () => boolean) => Promise<T>,
): Promise<T> {
  const identity = authIdentity();
  if (!identity.userId || identity.userId !== key[1]) aborted();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const request = { key, controller };
  requests.add(request);
  const valid = () => !controller.signal.aborted && sameAuthIdentity(identity);
  try {
    if (!valid()) aborted();
    const data = await run(controller.signal, valid);
    if (!valid()) aborted();
    return data;
  } finally {
    signal?.removeEventListener("abort", abort);
    requests.delete(request);
  }
}

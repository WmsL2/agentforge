import type { QueryKey } from "@tanstack/react-query";
import { aborted, authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { useAuthStore } from "@/stores/auth-store";

/** Keep resource prefixes for invalidation, but never share a flight/cache across auth sessions. */
export function workflowRunReadKey(key: QueryKey, identity = authIdentity()) {
  return [...key, "auth", identity.generation, identity.transitionEpoch] as const;
}

export async function workflowRunRequest<T>(
  userId: string,
  identity: ReturnType<typeof authIdentity>,
  signal: AbortSignal,
  read: (signal: AbortSignal, identityGuard: () => boolean) => Promise<T>,
): Promise<T> {
  if (!identity.userId || identity.userId !== userId || !sameAuthIdentity(identity)) aborted();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const valid = () => !controller.signal.aborted && sameAuthIdentity(identity);
  const unsubscribe = useAuthStore.subscribe(() => {
    if (!sameAuthIdentity(identity)) abort();
  });
  try {
    if (!valid()) aborted();
    const result = await read(controller.signal, valid);
    if (!valid()) aborted();
    return result;
  } finally {
    unsubscribe();
    signal.removeEventListener("abort", abort);
  }
}

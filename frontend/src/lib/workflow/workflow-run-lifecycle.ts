import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-client";
import { aborted, authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { useAuthStore } from "@/stores/auth-store";

/** Keep resource prefixes for invalidation, but never share a flight/cache across auth sessions. */
export function workflowRunReadKey(key: QueryKey, identity = authIdentity()) {
  return [...key, "auth", identity.generation, identity.transitionEpoch] as const;
}

/** A denial outlives transient errors; false alone is never evidence of a verified read. */
export const workflowRunDenialKey = (readKey: QueryKey) =>
  [...readKey, "authorization-denied"] as const;
export function workflowRunReadRetry(count: number, error: Error) {
  return (
    count < 1 &&
    error.name !== "AbortError" &&
    !(error instanceof ApiError && [403, 404].includes(error.status))
  );
}

export async function workflowRunRequest<T>(
  userId: string,
  identity: ReturnType<typeof authIdentity>,
  signal: AbortSignal,
  read: (signal: AbortSignal, identityGuard: () => boolean) => Promise<T>,
  authorization?: { client: QueryClient; key: QueryKey },
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
    // Only this exact resource's successful, identity-checked HTTP read can authorize it again.
    if (authorization)
      authorization.client.setQueryData(workflowRunDenialKey(authorization.key), false);
    return result;
  } catch (error) {
    if (authorization && valid() && error instanceof ApiError && [403, 404].includes(error.status))
      authorization.client.setQueryData(workflowRunDenialKey(authorization.key), true);
    throw error;
  } finally {
    unsubscribe();
    signal.removeEventListener("abort", abort);
  }
}

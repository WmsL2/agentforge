/** Single-page ordering for HTTP operations which may set/clear auth cookies.
 * Never abort a started cookie writer to release this queue: wait for its response.
 * This module has no store/client imports, so the store can invalidate probes too.
 */
export type AuthOperation = "login" | "logout" | "probe";
let epoch = 0;
let transition: "login" | "logout" | null = null;
let probesBlocked = false;
let cookieTail: Promise<void> = Promise.resolve();

export const authTransitionEpoch = () => epoch;
export const isAuthTransition = () => transition !== null;
export const canProbeAuthentication = (authenticated = false) =>
  !transition && (!probesBlocked || authenticated);
export function blockAuthProbes() {
  probesBlocked = true;
  epoch++;
}
export function resumeAuthProbes() {
  probesBlocked = false;
}

export function coordinateAuthentication<T>(
  kind: AuthOperation,
  authenticated: boolean,
  onStart: () => void,
  operation: (current: () => boolean) => Promise<T>,
): Promise<T> {
  if (kind === "probe" && !canProbeAuthentication(authenticated)) {
    return Promise.reject(new DOMException("Authentication transition", "AbortError"));
  }
  if (kind !== "probe") {
    epoch++;
    transition = kind;
    probesBlocked = true;
    onStart(); // Hide old identity and cancel Knowledge before any await.
  }
  const ticket = epoch;
  const current = () => ticket === epoch;
  const task = cookieTail.then(async () => {
    if (kind === "probe" && !current())
      throw new DOMException("Stale authentication", "AbortError");
    try {
      const result = await operation(current);
      if (!current()) throw new DOMException("Stale authentication", "AbortError");
      if (kind === "login") probesBlocked = false;
      return result;
    } finally {
      if (kind !== "probe" && current()) transition = null;
    }
  });
  cookieTail = task.then(
    () => {},
    () => {},
  );
  return task;
}

import { useAuthStore } from "@/stores/auth-store";

let generation = 0;
useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id || state.isAuthenticated !== previous.isAuthenticated)
    generation++;
});
export function authIdentity() {
  const state = useAuthStore.getState();
  return { userId: state.isAuthenticated ? state.user?.id : undefined, generation };
}
export function sameAuthIdentity(identity: ReturnType<typeof authIdentity>) {
  const current = authIdentity();
  return current.userId === identity.userId && current.generation === identity.generation;
}
export function aborted(): never {
  throw new DOMException("Request cancelled", "AbortError");
}

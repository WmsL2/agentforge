import { useAuthStore } from "@/stores/auth-store";

import { authTransitionEpoch, isAuthTransition } from "./auth-transition";

let generation = 0;
useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id || state.isAuthenticated !== previous.isAuthenticated)
    generation++;
});
export function authIdentity() {
  const state = useAuthStore.getState();
  return {
    userId: state.isAuthenticated && !isAuthTransition() ? state.user?.id : undefined,
    generation,
    transitionEpoch: authTransitionEpoch(),
  };
}
export function sameAuthIdentity(identity: ReturnType<typeof authIdentity>) {
  const current = authIdentity();
  return (
    current.userId === identity.userId &&
    current.generation === identity.generation &&
    current.transitionEpoch === identity.transitionEpoch
  );
}
export function aborted(): never {
  throw new DOMException("Request cancelled", "AbortError");
}

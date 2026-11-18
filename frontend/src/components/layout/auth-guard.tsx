"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores";
import { isAuthTransition } from "@/lib/auth-transition";
import { ROUTES } from "@/lib/constants";
import { Spinner } from "@/components/ui";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { isAuthenticated, checkAuth } = useAuthStore();
  const [checking, setChecking] = useState(!isAuthenticated);

  useEffect(() => {
    if (isAuthenticated) return;

    const verify = async () => {
      try {
        await checkAuth();
        const state = useAuthStore.getState();
        if (!state.isAuthenticated && !isAuthTransition()) router.replace(ROUTES.LOGIN);
      } catch {
        router.replace(ROUTES.LOGIN);
      } finally {
        setChecking(false);
      }
    };

    verify();
  }, [isAuthenticated, router, checkAuth]);

  if (checking && !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center" role="status" aria-live="polite">
        <Spinner className="text-muted-foreground h-6 w-6" />
        <span className="sr-only">Checking authentication...</span>
      </div>
    );
  }

  if (!isAuthenticated) return null;
  return <>{children}</>;
}

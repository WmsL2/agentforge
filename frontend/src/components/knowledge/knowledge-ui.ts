import { useCallback, useEffect, useRef } from "react";
import { ApiError } from "@/lib/api-client";
import { authIdentity, sameAuthIdentity } from "@/lib/auth-identity";
import { getKnowledgeErrorCode } from "@/lib/knowledge/knowledge-error";
import type { useTranslations } from "next-intl";

export type KnowledgeTranslator = ReturnType<typeof useTranslations>;
export function knowledgeError(error: unknown, t: KnowledgeTranslator) {
  const code = getKnowledgeErrorCode(error);
  if (code === "WORKSPACE_PERMISSION_DENIED") return t("errors.forbidden");
  if (error instanceof ApiError) {
    const key = (
      {
        401: "unauthorized",
        403: "forbidden",
        404: "notFound",
        409: "conflict",
        422: "validation",
      } as Record<number, string>
    )[error.status];
    if (key) return t(`errors.${key}`);
  }
  return t("errors.server");
}
export function isAbort(error: unknown) {
  return (
    typeof error === "object" && error !== null && "name" in error && error.name === "AbortError"
  );
}
export function useKnowledgeLease() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return useCallback(() => {
    const identity = authIdentity();
    return () => mounted.current && sameAuthIdentity(identity);
  }, []);
}
export function knowledgeDate(value: string | null, locale: string) {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "—";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(value),
  );
}

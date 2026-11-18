import { ApiError } from "@/lib/api-client";
/** Preserve the original ApiError/data; classify only stable backend codes. */
export function getKnowledgeErrorCode(error: unknown): string | undefined {
  if (!(error instanceof ApiError) || !error.data || typeof error.data !== "object")
    return undefined;
  const data = error.data as Record<string, unknown>;
  const structured = data.error;
  if (!structured || typeof structured !== "object") return undefined;
  const code = (structured as Record<string, unknown>).code;
  return typeof code === "string" ? code : undefined;
}

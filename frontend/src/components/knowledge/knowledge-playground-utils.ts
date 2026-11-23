import { ApiError } from "@/lib/api-client";
import { getKnowledgeErrorCode } from "@/lib/knowledge/knowledge-error";
import { knowledgeError, type KnowledgeTranslator } from "./knowledge-ui";
export const PLAYGROUND_TEXT_LIMIT = 10_000;
export const PLAYGROUND_CODES = [
  "KNOWLEDGE_SEARCH_QUERY_INVALID",
  "KNOWLEDGE_SEARCH_TOP_K_INVALID",
  "KNOWLEDGE_SEARCH_MIN_SCORE_INVALID",
  "KNOWLEDGE_RETRIEVAL_DATABASE_ERROR",
  "KNOWLEDGE_INDEX_MODEL_INCOMPATIBLE",
  "EMBEDDING_TIMEOUT",
  "EMBEDDING_PROVIDER_UNAVAILABLE",
  "EMBEDDING_CONFIGURATION_MISMATCH",
  "KNOWLEDGE_AGENT_DISABLED",
  "KNOWLEDGE_AGENT_MODEL_NOT_CONFIGURED",
  "KNOWLEDGE_AGENT_TIMEOUT",
  "KNOWLEDGE_AGENT_EXECUTION_FAILED",
  "KNOWLEDGE_AGENT_INVALID_RESPONSE",
  "EMBEDDING_RATE_LIMITED",
  "EMBEDDING_API_KEY_MISSING",
  "EMBEDDING_DIMENSIONS_INCOMPATIBLE",
  "EMBEDDING_CONFIGURATION_INVALID",
  "EMBEDDING_MODEL_MISMATCH",
  "EMBEDDING_PROVIDER_REJECTED",
  "EMBEDDING_COUNT_MISMATCH",
  "EMBEDDING_DIMENSION_MISMATCH",
  "EMBEDDING_VALUE_INVALID",
  "EMBEDDING_ZERO_VECTOR",
] as const;
export function playgroundError(error: unknown, t: KnowledgeTranslator) {
  if (error instanceof ApiError && error.status === 0) return t("playground.networkError");
  const code = getKnowledgeErrorCode(error);
  return code && PLAYGROUND_CODES.includes(code as (typeof PLAYGROUND_CODES)[number])
    ? t(`playground.errors.${code}`)
    : knowledgeError(error, t);
}
/** Python str.strip treats U+001C..001F and U+0085 as whitespace, but not FEFF. */
export function normalizePlaygroundText(text: string) {
  return text.replace(
    /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu,
    "",
  );
}
export function validatePlaygroundText(text: string): string | undefined {
  const length = Array.from(normalizePlaygroundText(text)).length;
  return !length ? "required" : length > 2000 ? "tooLong" : undefined;
}
export function searchParameters(query: string, top: string, minimum: string) {
  const textError = validatePlaygroundText(query);
  if (textError) return { error: textError } as const;
  const normalizedTop = top.trim();
  const top_k = Number(normalizedTop);
  if (!/^\d+$/.test(normalizedTop) || !Number.isSafeInteger(top_k) || top_k < 1 || top_k > 20)
    return { error: "topK" } as const;
  const score = minimum.trim();
  const min_score = score === "" ? null : Number(score);
  if (
    min_score !== null &&
    (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(score) ||
      !Number.isFinite(min_score) ||
      min_score < -1 ||
      min_score > 1)
  )
    return { error: "minScore" } as const;
  return { payload: { query: normalizePlaygroundText(query), top_k, min_score } } as const;
}

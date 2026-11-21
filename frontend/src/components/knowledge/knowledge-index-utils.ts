import { getKnowledgeErrorCode } from "@/lib/knowledge/knowledge-error";
import { knowledgeError, type KnowledgeTranslator } from "./knowledge-ui";
export const INDEX_CONFIRM_MS = 30_000;
export const INDEX_STATES = ["not_indexed", "pending", "running", "succeeded", "failed"] as const;
export const INDEX_CODES = [
  "DOCUMENT_NOT_READY_FOR_INDEXING",
  "DOCUMENT_CONTENT_CHANGED",
  "DOCUMENT_HAS_NO_INDEXABLE_TEXT",
  "DOCUMENT_CHUNK_LIMIT_EXCEEDED",
  "EMBEDDING_RATE_LIMITED",
  "EMBEDDING_TIMEOUT",
  "EMBEDDING_PROVIDER_UNAVAILABLE",
  "EMBEDDING_API_KEY_MISSING",
  "EMBEDDING_DIMENSIONS_INCOMPATIBLE",
  "EMBEDDING_CONFIGURATION_INVALID",
  "EMBEDDING_CONFIGURATION_MISMATCH",
  "EMBEDDING_MODEL_MISMATCH",
  "EMBEDDING_PROVIDER_REJECTED",
  "EMBEDDING_COUNT_MISMATCH",
  "EMBEDDING_DIMENSION_MISMATCH",
  "EMBEDDING_VALUE_INVALID",
  "EMBEDDING_ZERO_VECTOR",
  "KNOWLEDGE_INDEX_INTERNAL_ERROR",
] as const;
export function indexReason(code: string | null, t: KnowledgeTranslator) {
  return code && INDEX_CODES.includes(code as (typeof INDEX_CODES)[number])
    ? t(`documents.index.errors.${code}`)
    : t("documents.index.errors.unknown");
}
export function indexError(error: unknown, t: KnowledgeTranslator) {
  const code = getKnowledgeErrorCode(error);
  return code && INDEX_CODES.includes(code as (typeof INDEX_CODES)[number])
    ? indexReason(code, t)
    : knowledgeError(error, t);
}

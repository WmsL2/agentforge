import { ApiError } from "@/lib/api-client";
import { getKnowledgeErrorCode } from "@/lib/knowledge/knowledge-error";
import { knowledgeError, type KnowledgeTranslator } from "./knowledge-ui";

export const DOCUMENT_PAGE_SIZE = 10;
export const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;
export const PREVIEW_CHAR_LIMIT = 50_000;
export const DOCUMENT_CODES = [
  "DOCUMENT_EMPTY",
  "DOCUMENT_TOO_LARGE",
  "DOCUMENT_TYPE_UNSUPPORTED",
  "DOCUMENT_MIME_MISMATCH",
  "DOCUMENT_SIGNATURE_MISMATCH",
  "DOCX_ARCHIVE_LIMIT",
  "DOCUMENT_CONTENT_UNAVAILABLE",
  "DOCUMENT_PARSE_TIMEOUT",
  "PDF_CORRUPT",
  "PDF_ENCRYPTED",
  "PDF_PAGE_LIMIT_EXCEEDED",
  "PDF_NO_EXTRACTABLE_TEXT",
  "PDF_PARSE_FAILED",
  "DOCX_PARSE_FAILED",
  "DOCX_NO_EXTRACTABLE_TEXT",
  "DOCUMENT_TEXT_LIMIT_EXCEEDED",
  "TEXT_NOT_UTF8",
] as const;
export function parseReason(code: string | null, t: KnowledgeTranslator) {
  return code && DOCUMENT_CODES.includes(code as (typeof DOCUMENT_CODES)[number])
    ? t(`documents.errors.${code}`)
    : t("documents.errors.unknownParse");
}
export function documentError(error: unknown, t: KnowledgeTranslator) {
  const code = getKnowledgeErrorCode(error);
  if (code && DOCUMENT_CODES.includes(code as (typeof DOCUMENT_CODES)[number]))
    return parseReason(code, t);
  if (error instanceof ApiError && error.status === 413)
    return t("documents.errors.DOCUMENT_TOO_LARGE");
  if (error instanceof ApiError && error.status === 400) return t("errors.validation");
  return knowledgeError(error, t);
}
const mimes: Record<string, string[]> = {
  pdf: ["application/pdf"],
  docx: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  txt: ["text/plain"],
  md: ["text/markdown", "text/plain"],
  markdown: ["text/markdown", "text/plain"],
};
/** Only absent browser MIME is completed; known mismatches are never relabelled. */
export function prepareDocument(file?: File): { file: File } | { error: string } {
  if (!file) return { error: "chooseFile" };
  if (!file.size) return { error: "DOCUMENT_EMPTY" };
  if (file.size > MAX_DOCUMENT_BYTES) return { error: "DOCUMENT_TOO_LARGE" };
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const allowed = Object.hasOwn(mimes, extension) ? mimes[extension] : undefined;
  if (!allowed) return { error: "DOCUMENT_TYPE_UNSUPPORTED" };
  const mime = file.type.split(";", 1)[0]!.trim().toLowerCase();
  if (mime && !allowed.includes(mime)) return { error: "DOCUMENT_MIME_MISMATCH" };
  return {
    file: mime
      ? file
      : new File([file], file.name, { type: allowed[0], lastModified: file.lastModified }),
  };
}
export function safeFilename(name: string) {
  return (
    name
      .replace(/[\\/<>:"|?*\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, "_")
      .replace(/^[. ]+|[. ]+$/g, "")
      .slice(0, 180) || "document"
  );
}
/** Blob bytes are passed through. Delay revocation until the browser consumes the click. */
export function saveDocument(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  try {
    anchor.href = url;
    anchor.download = safeFilename(filename);
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
export function documentMatches(
  document: { id: string; workspace_id: string; knowledge_base_id: string },
  workspace: string,
  base: string,
  id = document.id,
) {
  return (
    document.id === id && document.workspace_id === workspace && document.knowledge_base_id === base
  );
}

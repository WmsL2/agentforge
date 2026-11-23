/** Match Python UUID string spellings, while API reads still verify ownership. */
export function canonicalKnowledgeUuid(value: string): string | null {
  const hex = value
    .replaceAll("urn:", "")
    .replaceAll("uuid:", "")
    .replace(/^[{}]+|[{}]+$/g, "")
    .replaceAll("-", "");
  if (!/^[0-9a-f]{32}$/i.test(hex)) return null;
  const v = hex.toLowerCase();
  return `${v.slice(0, 8)}-${v.slice(8, 12)}-${v.slice(12, 16)}-${v.slice(16, 20)}-${v.slice(20)}`;
}
export const isKnowledgeUuid = (value: string) => canonicalKnowledgeUuid(value) !== null;
export function normalizeKnowledgeQuery(text: string) {
  return text.replace(
    /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu,
    "",
  );
}
export function validKnowledgeTopK(text: string) {
  return (
    /^\d+$/.test(text) &&
    Number.isSafeInteger(Number(text)) &&
    Number(text) >= 1 &&
    Number(text) <= 5
  );
}

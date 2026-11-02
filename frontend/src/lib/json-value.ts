export type JsonNumberProblem = "nonFinite" | "unsafeInteger" | "precisionLoss";

export type SafeJsonResult =
  { ok: true; value: unknown } | { ok: false; problem: "syntax" | JsonNumberProblem };

const JSON_NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;

function decimalSignature(token: string): string {
  const [mantissa = "", exponentText] = token.toLowerCase().split("e");
  const negative = mantissa.startsWith("-");
  const unsigned = negative ? mantissa.slice(1) : mantissa;
  const [integer, fraction = ""] = unsigned.split(".");
  let digits = `${integer}${fraction}`.replace(/^0+/, "") || "0";
  let exponent = Number(exponentText ?? 0) - fraction.length;
  while (digits.length > 1 && digits.endsWith("0")) {
    digits = digits.slice(0, -1);
    exponent += 1;
  }
  return `${negative && digits !== "0" ? "-" : ""}${digits}e${exponent}`;
}

function numberProblem(json: string): JsonNumberProblem | null {
  let inString = false;
  let escaped = false;
  for (let index = 0; index < json.length; index += 1) {
    const character = json.charAt(index);
    if (inString) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') inString = false;
      continue;
    }
    if (character === '"') {
      inString = true;
      continue;
    }
    if (character !== "-" && (character < "0" || character > "9")) continue;
    JSON_NUMBER.lastIndex = index;
    const match = JSON_NUMBER.exec(json);
    if (!match) continue;
    const token = match[0];
    const value = Number(token);
    if (!Number.isFinite(value)) return "nonFinite";
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) return "unsafeInteger";
    if (decimalSignature(token) !== decimalSignature(String(value))) return "precisionLoss";
    index += token.length - 1;
  }
  return null;
}

export function parseSafeJson(text: string): SafeJsonResult {
  try {
    const value: unknown = JSON.parse(text);
    const problem = numberProblem(text);
    return problem ? { ok: false, problem } : { ok: true, value };
  } catch {
    return { ok: false, problem: "syntax" };
  }
}

export function isJsonObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

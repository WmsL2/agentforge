function normalizeErrorValue(
  value: unknown,
): string | null {
  if (typeof value === "string") {
    const message = value.trim();

    return message || null;
  }

  if (
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }

  if (Array.isArray(value)) {
    const messages = value
      .map(normalizeErrorValue)
      .filter(
        (message): message is string =>
          Boolean(message),
      );

    return messages.length > 0
      ? messages.join("; ")
      : null;
  }

  if (
    value !== null &&
    typeof value === "object"
  ) {
    const record = value as Record<
      string,
      unknown
    >;

    for (const key of [
      "detail",
      "message",
      "msg",
      "error",
    ]) {
      if (!(key in record)) {
        continue;
      }

      const message =
        normalizeErrorValue(
          record[key],
        );

      if (message) {
        return message;
      }
    }
  }

  return null;
}

export function getApiErrorMessage(
  data: unknown,
  fallback = "Request failed",
): string {
  return (
    normalizeErrorValue(data) ??
    fallback
  );
}
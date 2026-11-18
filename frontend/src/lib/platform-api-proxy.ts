import { NextRequest, NextResponse } from "next/server";

import { backendFetch, BackendApiError } from "@/lib/server-api";

type ProxyMethod = "GET" | "POST" | "PATCH" | "DELETE";

interface PlatformApiProxyOptions {
  path: string;
  knowledge?: boolean;
  multipart?: boolean;
  download?: boolean;
  method?: ProxyMethod;
  query?: readonly string[];
  successStatus?: number;
  location?: (data: unknown) => string | undefined;
}

const NO_STORE_HEADERS = { "Cache-Control": "no-store" };

function json(data: unknown, status: number, headers?: HeadersInit) {
  return NextResponse.json(data, {
    status,
    headers: { ...NO_STORE_HEADERS, ...headers },
  });
}

function rejectsCrossSiteMutation(request: NextRequest, method: ProxyMethod): boolean {
  if (method === "GET") return false;

  if (request.headers.get("sec-fetch-site")?.toLowerCase() === "cross-site") {
    return true;
  }

  const origin = request.headers.get("origin");
  if (!origin) return false;

  try {
    return new URL(origin).origin !== request.nextUrl.origin;
  } catch {
    return true;
  }
}

function selectedQuery(request: NextRequest, allowed: readonly string[]): Record<string, string> {
  const query: Record<string, string> = {};
  for (const name of allowed) {
    const value = request.nextUrl.searchParams.get(name);
    if (value !== null) query[name] = value;
  }
  return query;
}

export function encodePathSegment(value: string): string {
  return encodeURIComponent(value);
}

export async function proxyPlatformApi(
  request: NextRequest,
  {
    path,
    knowledge = false,
    multipart = false,
    download = false,
    method = "GET",
    query: allowedQuery = [],
    successStatus = 200,
    location,
  }: PlatformApiProxyOptions,
): Promise<NextResponse> {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return json({ detail: "Not authenticated" }, 401);
  }

  if (rejectsCrossSiteMutation(request, method)) {
    return json({ error: { code: "CSRF_REJECTED", message: "Cross-site request rejected" } }, 403);
  }

  try {
    let body: string | FormData | undefined;
    if (multipart) {
      try {
        const incoming = await request.formData();
        const file = incoming.get("file");
        if (!file || typeof file === "string") return json({ detail: "Expected file field" }, 422);
        body = new FormData();
        body.append("file", file, file.name);
      } catch {
        return json({ detail: "Invalid multipart request" }, 400);
      }
    } else {
      body = method === "GET" || method === "DELETE" ? undefined : await request.text();
    }
    const query = selectedQuery(request, allowedQuery);
    const data = await backendFetch<unknown>(path, {
      method,
      ...(knowledge
        ? { cache: "no-store" as const, redirect: "error" as const, signal: request.signal }
        : {}),
      ...(download ? { rawResponse: true } : {}),
      params: Object.keys(query).length ? query : undefined,
      headers: { Authorization: `Bearer ${accessToken}` },
      body: body || undefined,
    });

    if (download) {
      const upstream = data as Response;
      const disposition = upstream.headers.get("Content-Disposition");
      // Keep backend filename parameters (including RFC 5987 Unicode); force attachment.
      const filename = disposition?.includes(";")
        ? disposition.slice(disposition.indexOf(";"))
        : "";
      return new NextResponse(upstream.body, {
        status: 200,
        headers: {
          "Content-Type": upstream.headers.get("Content-Type") || "application/octet-stream",
          "Content-Disposition": `attachment${filename}`,
          "Cache-Control": "private, no-store",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }
    if (successStatus === 204) {
      return new NextResponse(null, { status: 204, headers: NO_STORE_HEADERS });
    }

    const responseHeaders: HeadersInit = {};
    const frontendLocation = location?.(data);
    if (frontendLocation) responseHeaders.Location = frontendLocation;
    return json(data, successStatus, responseHeaders);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return json(
        error.data ?? {
          error: { code: "UPSTREAM_ERROR", message: "Backend request failed" },
        },
        error.status,
      );
    }

    return json(
      { error: { code: "UPSTREAM_UNAVAILABLE", message: "Backend service unavailable" } },
      502,
    );
  }
}

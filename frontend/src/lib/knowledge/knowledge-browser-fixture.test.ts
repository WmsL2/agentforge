import { beforeEach, expect, it } from "vitest";
import type { Page, Route } from "@playwright/test";
import {
  initial,
  install,
  document,
  base,
  id,
  WS,
  WS2,
  KB,
  FOREIGN,
  DOC,
  TEXT,
  type BrowserState,
} from "../../../e2e/fixtures/knowledge-api";

// Exercise only the HTTP fixture router, not a replacement for browser execution or React tests.
let state: BrowserState;
let handler: (route: Route) => Promise<unknown>;
beforeEach(async () => {
  state = initial();
  state.documents = [document()];
  await install(
    {
      addInitScript: async () => {},
      route: async (pattern: string, callback: typeof handler) => {
        if (pattern === "**/api/**") handler = callback;
      },
    } as unknown as Page,
    state,
  );
});
async function request(path: string, method = "GET", multipart = false) {
  let response: { status: number; body?: string | Buffer } | undefined;
  await handler({
    request: () => ({
      url: () => `http://localhost:3000/api${path}`,
      method: () => method,
      headers: () => (multipart ? { "content-type": "multipart/form-data; boundary=fixture" } : {}),
      postData: () => undefined,
      postDataBuffer: () =>
        Buffer.from(
          `--fixture\r\nContent-Disposition: form-data; name="file"; filename="证据.txt"\r\n\r\n${TEXT}\r\n--fixture--`,
        ),
    }),
    fulfill: async (value: typeof response) => {
      response = value;
    },
  } as unknown as Route);
  if (!response) throw new Error("Fixture must return an HTTP response");
  return response;
}
const path = (workspace = WS, knowledgeBase = KB, doc = DOC) =>
  `/workspaces/${workspace}/knowledge-bases/${knowledgeBase}/documents/${doc}`;
it.each(["", "/content", "/download", "/index"])(
  "document %s enforces exact ownership and IDs without mutation",
  async (action) => {
    state.bases.push(base(id(12), WS, "Second base"));
    for (const [ws, kb, doc] of [
      [WS2, FOREIGN, DOC],
      [WS, id(12), DOC],
      [WS, KB, `${DOC}-suffix`],
    ]) {
      for (const method of action === "/index"
        ? ["GET", "POST"]
        : action === ""
          ? ["GET", "DELETE"]
          : ["GET"]) {
        const response = await request(path(ws, kb, doc) + action, method);
        expect(response.status).toBe(404);
        expect(String(response.body)).not.toContain(TEXT.trim());
        expect(state.documents).toHaveLength(1);
        expect(state.indexPosts).toBe(0);
      }
    }
  },
);
it("unknown document subroutes cannot expose content or delete a document", async () => {
  expect((await request(path() + "/content/extra", "DELETE")).status).toBe(404);
  expect(state.documents).toHaveLength(1);
});
it("upload returns the newly created document in the requested base, not the first row", async () => {
  const response = await request(
    `/workspaces/${WS2}/knowledge-bases/${FOREIGN}/documents`,
    "POST",
    true,
  );
  expect(response.status).toBe(201);
  const created = JSON.parse(String(response.body));
  expect(created).toMatchObject({ workspace_id: WS2, knowledge_base_id: FOREIGN });
  expect(created.id).not.toBe(DOC);
  expect(state.documents).toHaveLength(2);
});
it("deletion removes only the matched document", async () => {
  state.documents.push({
    ...document(),
    id: id(22),
    workspace_id: WS2,
    knowledge_base_id: FOREIGN,
  });
  expect((await request(path(), "DELETE")).status).toBe(204);
  expect(state.documents.map((d) => d.id)).toEqual([id(22)]);
});
it("document index metadata is scoped to the requested document", async () => {
  state.documents.push({ ...document(), id: id(22) });
  await request(path(), "POST"); // Metadata does not accept POST and must not delete data.
  expect((await request(path() + "/index", "POST")).status).toBe(202);
  const other = await request(path(WS, KB, id(22)) + "/index");
  expect(JSON.parse(String(other.body))).toMatchObject({
    document_id: id(22),
    status: "not_indexed",
    job_id: null,
  });
});

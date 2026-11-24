import { test, expect } from "@playwright/test";
import {
  initial,
  install,
  document,
  WS,
  WS2,
  KB,
  DOC,
  TEXT,
  source,
} from "./fixtures/knowledge-api";

test.use({ storageState: ".playwright/.auth/user.json" });

test("Knowledge navigation and persisted create/read/update/delete with cancellation", async ({
  page,
}) => {
  const state = initial();
  await install(page, state);
  await page.goto("/dashboard");
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Knowledge bases", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create knowledge base", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill("Created browser base");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("link", { name: "Created browser base", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Created browser base", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill("Updated browser base");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Updated browser base", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  expect(state.bases.some((b) => b.name === "Updated browser base")).toBe(true);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("link", { name: "Updated browser base", exact: true })).toHaveCount(
    0,
  );
  expect(state.bases.some((b) => b.name === "Updated browser base")).toBe(false);
  expect(
    state.calls.filter((c) => ["POST", "PATCH", "DELETE"].includes(c.method)).map((c) => c.method),
  ).toEqual(["POST", "PATCH", "DELETE"]);
  expect(state.calls.find((c) => c.method === "POST")?.path).toBe(
    `/api/workspaces/${WS}/knowledge-bases`,
  );
});

for (const role of ["owner", "admin", "member"] as const) {
  test(`Workspace scope and ${role} Knowledge permissions`, async ({ page }) => {
    const state = initial();
    state.role = role;
    await install(page, state);
    await page.goto(`/knowledge?workspace_id=${WS}`);
    await expect(page.getByRole("link", { name: "Browser knowledge", exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Other workspace secret", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Create knowledge base", exact: true }),
    ).toHaveCount(role === "member" ? 0 : 1);
    await page.getByRole("combobox", { name: "Workspace", exact: true }).click();
    await page.getByRole("option", { name: "Browser workspace 2", exact: true }).click();
    await expect(
      page.getByRole("link", { name: "Other workspace secret", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Browser knowledge", exact: true })).toHaveCount(0);
    expect(
      state.calls.some(
        (c) => c.path === `/api/workspaces/${WS2}/knowledge-bases` && c.method === "GET",
      ),
    ).toBe(true);
  });
}

test("Document multipart upload, metadata, preview, exact download bytes and confirmed deletion", async ({
  page,
}) => {
  const state = initial();
  await install(page, state);
  await page.goto(`/knowledge/${KB}?workspace_id=${WS}`);
  await page.getByRole("button", { name: "Upload document", exact: true }).click();
  await page
    .getByLabel("File", { exact: true })
    .setInputFiles({ name: "证据.txt", mimeType: "text/plain", buffer: Buffer.from(TEXT) });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Upload document", exact: true })
    .click();
  await page.getByRole("button", { name: "证据.txt", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Document details" });
  await expect(dialog.getByText("SHA-256", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Preview text", exact: true }).click();
  await expect(dialog.locator("pre")).toContainText(TEXT.trim());
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download original", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("证据.txt");
  const stream = await download.createReadStream();
  const bytes: Buffer[] = [];
  for await (const chunk of stream!) bytes.push(Buffer.from(chunk));
  expect(Buffer.concat(bytes)).toEqual(Buffer.from(TEXT));
  await dialog.press("Escape");
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "Delete document 证据.txt", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  expect(state.documents).toHaveLength(1);
  await page.getByRole("button", { name: "Delete document 证据.txt", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete document", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "证据.txt", exact: true })).toHaveCount(0);
  expect(
    state.calls.some((c) => c.method === "DELETE" && c.path.endsWith(`/documents/${DOC}`)),
  ).toBe(true);
});

test("Invalid file fails before any upload request", async ({ page }) => {
  const state = initial();
  await install(page, state);
  await page.goto(`/knowledge/${KB}?workspace_id=${WS}`);
  await page.getByRole("button", { name: "Upload document", exact: true }).click();
  await page
    .getByLabel("File", { exact: true })
    .setInputFiles({ name: ".txt", mimeType: "text/plain", buffer: Buffer.from(TEXT) });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Upload document", exact: true })
    .click();
  await expect(
    page.getByText("This file extension is not supported.", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.filter((c) => c.method === "POST" && c.path.endsWith("/documents")),
  ).toHaveLength(0);
});

test("Index acceptance, running, success and failed reindex retain the active generation", async ({
  page,
}) => {
  const state = initial();
  state.documents = [document()];
  await install(page, state);
  await page.goto(`/knowledge/${KB}?workspace_id=${WS}`);
  await page.getByRole("button", { name: "证据.txt", exact: true }).click();
  const panel = page.getByRole("region", { name: "Index status", exact: true });
  await panel.getByRole("button", { name: "Build index", exact: true }).click();
  await expect(panel).toContainText("Index request accepted.");
  await expect(panel.getByRole("button", { name: "Build index", exact: true })).toHaveCount(0);
  expect(state.indexPosts).toBe(1);
  state.indexPhase = "running";
  await expect(panel).toContainText("Running", { timeout: 10_000 });
  state.indexPhase = "succeeded";
  await panel.getByRole("button", { name: "Refresh index status", exact: true }).click();
  await expect(panel).toContainText("A successful index is currently active.");
  const active = state.generation;
  await panel.getByRole("button", { name: "Rebuild index", exact: true }).click();
  await panel.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(state.indexPosts).toBe(1);
  await panel.getByRole("button", { name: "Rebuild index", exact: true }).click();
  await panel.getByRole("button", { name: "Confirm rebuild", exact: true }).click();
  await expect.poll(() => state.indexPosts).toBe(2);
  state.indexPhase = "failed";
  await panel.getByRole("button", { name: "Refresh index status", exact: true }).click();
  await expect(panel).toContainText(
    "The latest build failed. The previous successful index remains active.",
  );
  expect(state.generation).toBe(active);
});

test("Search and Ask use actual parameters, plain text and only backend sources", async ({
  page,
}) => {
  const state = initial();
  await install(page, state);
  await page.goto(`/knowledge/${KB}?workspace_id=${WS}`);
  await page.getByLabel("Query", { exact: true }).fill("growth");
  await page.getByLabel("Top K", { exact: true }).fill("3");
  await page.getByRole("button", { name: "Search knowledge", exact: true }).click();
  const results = page.getByRole("region", { name: "Search results", exact: true });
  await expect(results).toContainText(source.chunk_id);
  await expect(results).toContainText("0.75");
  await expect(results.locator("img")).toHaveCount(0);
  expect(state.calls.find((c) => c.path.endsWith("/search"))?.body).toEqual({
    query: "growth",
    top_k: 3,
    min_score: null,
  });
  state.emptySearch = true;
  await page.getByRole("button", { name: "Search knowledge", exact: true }).click();
  await expect(page.getByText("No matching results", { exact: true })).toBeVisible();
  state.searchError = true;
  await page.getByRole("button", { name: "Search knowledge", exact: true }).click();
  await expect(page.getByText("Unable to complete this request", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching results", { exact: true })).toHaveCount(0);
  await expect(page.getByText("PRIVATE_PROVIDER_DETAIL", { exact: false })).toHaveCount(0);
  await page.getByRole("tab", { name: "Ask knowledge", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("What supports growth?");
  await page.getByRole("button", { name: "Ask knowledge", exact: true }).click();
  const answer = page.getByRole("region", { name: "Answer", exact: true });
  await expect(answer).toContainText("Actual fixture answer");
  await expect(answer).toContainText(source.document_id);
  expect(state.calls.find((c) => c.path.endsWith("/ask"))?.body).toEqual({
    question: "What supports growth?",
  });
  state.missingSources = true;
  await page.getByRole("button", { name: "Ask knowledge", exact: true }).click();
  await expect(answer).toContainText("No sources were returned. No citations have been added.");
  state.askStatus = "no_evidence";
  await page.getByRole("button", { name: "Ask knowledge", exact: true }).click();
  await expect(
    page.getByText("The knowledge base does not contain enough evidence to answer this question.", {
      exact: true,
    }),
  ).toBeVisible();
});

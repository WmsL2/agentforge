import { test, expect, type Page } from "@playwright/test";
import {
  initial,
  install,
  complete,
  graph,
  WS,
  KB,
  FOREIGN,
  WF,
  source,
  type BrowserState,
} from "./fixtures/knowledge-api";

test.use({ storageState: ".playwright/.auth/user.json" });
const node = (page: Page, key: string) => page.locator(`.react-flow__node[data-id="${key}"]`);
async function connect(page: Page, from: string, to: string) {
  const source = node(page, from).locator(".react-flow__handle.source");
  const target = node(page, to).locator(".react-flow__handle.target");
  await expect(source).toBeVisible();
  await expect(target).toBeVisible();
  const start = await source.boundingBox(),
    end = await target.boundingBox();
  if (!start || !end) throw new Error("Visible connection handles must have bounds");
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect(page.locator(`.react-flow__edge[data-id="${from}-to-${to}"]`)).toHaveCount(1);
}
async function open(page: Page, state: BrowserState) {
  await install(page, state);
  await page.goto(`/workflows/${WF}?workspace_id=${WS}`);
  await expect(page.getByRole("heading", { name: "Browser workflow", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
}
async function apply(page: Page) {
  await page.getByRole("button", { name: "Apply configuration", exact: true }).click();
}
async function save(page: Page, state: BrowserState) {
  const count = state.patches;
  await page.getByRole("button", { name: "Save graph", exact: true }).click();
  await expect.poll(() => state.patches).toBe(count + 1);
  await expect(page.getByRole("button", { name: "Run workflow", exact: true })).toBeEnabled();
}

test("Create Knowledge node, persist literal and input modes with exclusive fields and metadata", async ({
  page,
}) => {
  const state = initial();
  await open(page, state);
  await page.getByRole("button", { name: "Add Knowledge", exact: true }).click();
  const fitView = page.locator(".react-flow__controls-fitview");
  await expect(fitView).toHaveAttribute("aria-label", "Fit View");
  await expect(fitView).toHaveAttribute("title", "Fit View");
  await fitView.click();
  await node(page, "knowledge-1").click();
  const picker = page.getByLabel("Knowledge base", { exact: true });
  await expect(picker.locator(`option[value="${KB}"]`)).toHaveCount(1);
  await expect(picker.locator(`option[value="${FOREIGN}"]`)).toHaveCount(0);
  await picker.selectOption(KB);
  await page.getByLabel("Literal query text", { exact: true }).fill("growth literal");
  await page.getByLabel("Top K (1–5)", { exact: true }).fill("3");
  await apply(page);
  // Connect the added branch through real React Flow handles; no graph state injection.
  await connect(page, "start", "knowledge-1");
  await connect(page, "knowledge-1", "end");
  await save(page, state);
  expect(state.workflow.definition.edges).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ source: "start", target: "knowledge-1" }),
      expect.objectContaining({ source: "knowledge-1", target: "end" }),
    ]),
  );
  expect(state.workflow.definition.nodes.find((n) => n.id === "knowledge-1")?.config).toEqual({
    knowledge_base_id: KB,
    query_source: "literal",
    query: "growth literal",
    top_k: 3,
  });
  expect(state.workflow.definition.metadata).toEqual({ fixture: "preserve" });
  await page.reload();
  await node(page, "knowledge-1").click();
  await expect(page.getByLabel("Literal query text", { exact: true })).toHaveValue(
    "growth literal",
  );
  await page.getByLabel("Query source", { exact: true }).selectOption("workflow_input");
  await page.getByLabel("Workflow input key", { exact: true }).fill("question");
  await apply(page);
  await save(page, state);
  expect(state.workflow.definition.nodes.find((n) => n.id === "knowledge-1")?.config).toEqual({
    knowledge_base_id: KB,
    query_source: "workflow_input",
    input_key: "question",
    top_k: 3,
  });
  await page.reload();
  await node(page, "knowledge-1").click();
  await expect(page.getByLabel("Workflow input key", { exact: true })).toHaveValue("question");
  expect(state.calls.filter((c) => c.method === "PATCH")).toHaveLength(2);
});

test("Ordinary Agent binds, persists and clears Knowledge without foreign options", async ({
  page,
}) => {
  const state = initial();
  await open(page, state);
  await node(page, "agent").click();
  const picker = page.getByLabel("Bind knowledge base (optional)", { exact: true });
  await expect(picker).toHaveValue("");
  await expect(picker.locator(`option[value="${KB}"]`)).toHaveCount(1);
  await expect(picker.locator(`option[value="${FOREIGN}"]`)).toHaveCount(0);
  await picker.selectOption(KB);
  await apply(page);
  await save(page, state);
  await page.reload();
  await node(page, "agent").click();
  await expect(picker).toHaveValue(KB);
  await picker.selectOption("");
  await apply(page);
  await save(page, state);
  expect(state.workflow.definition.nodes.find((n) => n.kind === "agent")?.config).toEqual({
    runner: "langgraph",
    instruction: "Answer using evidence",
  });
  await page.reload();
  await node(page, "agent").click();
  await expect(picker).toHaveValue("");
});

test("Invalid historical binding remains unchanged and cannot be applied as verified", async ({
  page,
}) => {
  const state = initial("bound");
  state.workflow.definition.nodes.find((n) => n.kind === "agent")!.config.knowledge_base_id =
    FOREIGN;
  await open(page, state);
  await node(page, "agent").click();
  await expect(page.getByLabel("Bind knowledge base (optional)", { exact: true })).toHaveValue(
    FOREIGN,
  );
  await expect(
    page.getByText("The current knowledge base or its access is unavailable.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Instruction", { exact: false }).fill("Changed draft");
  await expect(
    page.getByRole("button", { name: "Apply configuration", exact: true }),
  ).toBeDisabled();
  expect(state.patches).toBe(0);
  expect(
    state.workflow.definition.nodes.find((n) => n.kind === "agent")?.config.knowledge_base_id,
  ).toBe(FOREIGN);
});

for (const mode of ["explicit", "bound"] as const) {
  test(`${mode} workflow submits pending, refreshes running/completed and displays persisted Steps and Trace`, async ({
    page,
  }) => {
    const state = initial(mode);
    await open(page, state);
    await page
      .getByLabel("Workflow input (JSON object)", { exact: true })
      .fill('{"question":"growth"}');
    await page.getByRole("button", { name: "Run workflow", exact: true }).click();
    await expect.poll(() => state.runs.length).toBe(1);
    const run = state.runs[0]!;
    await expect(page.getByText(/Run accepted for saved revision r3/)).toBeVisible();
    expect(run.workflow_id).toBe(WF);
    expect(run.input).toEqual({ question: "growth" });
    state.runPhase = "running";
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.locator("p").filter({ hasText: /^Status: running$/ })).toBeVisible();
    complete(state);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    const result = page.getByRole("region", {
      name: mode === "explicit" ? "Knowledge Retrieval" : "Knowledge Agent Answer",
      exact: true,
    });
    await expect(result).toContainText(source.chunk_id);
    await expect(result).toContainText(
      mode === "explicit" ? "Browser evidence" : "Actual workflow answer",
    );
    await expect(page.getByText("node_completed", { exact: true })).toBeVisible();
    await expect(
      page
        .locator("summary")
        .filter({ hasText: /^Output$/ })
        .first(),
    ).toBeVisible();
    expect(
      state.calls.filter((c) => c.path.endsWith("/runs/async") && c.method === "POST"),
    ).toHaveLength(1);
    const raw = page
      .locator("details pre")
      .filter({ hasText: mode === "explicit" ? "Browser evidence" : "Actual workflow answer" });
    await expect(raw).toHaveCount(1);
    const gate = () => {
      let release!: () => void;
      const wait = new Promise<void>((resolve) => {
        release = resolve;
      });
      return { wait, release };
    };
    const first = gate(),
      retry = gate(),
      authorized = gate();
    state.stepResponses.push(
      { status: 403 },
      { status: 503, wait: first.wait },
      { status: 503, wait: retry.wait },
      { status: 200, wait: authorized.wait },
    );
    const stepResponse = (status: number, ordinal: number) =>
      page.waitForResponse(
        (r) =>
          r.url().endsWith("/steps") &&
          r.status() === status &&
          state.stepResponseStarts.length === ordinal,
      );
    const hidden = async () => {
      await expect(result).toHaveCount(0);
      await expect(raw).toHaveCount(0);
    };
    const denial = stepResponse(403, 1);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await (await denial).finished();
    await expect(
      page.getByText("Run steps could not be loaded. The run itself has not been marked failed.", {
        exact: true,
      }),
    ).toBeVisible();
    await hidden();
    expect(state.stepResponseStarts).toEqual([403]);

    const first503 = stepResponse(503, 2),
      retry503 = stepResponse(503, 3);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect.poll(() => state.stepResponseStarts).toEqual([403, 503]);
    await hidden(); // First transient response is still held.
    first.release();
    await (await first503).finished();
    await expect.poll(() => state.stepResponseStarts).toEqual([403, 503, 503]);
    await hidden(); // The automatic retry is now held; recovery is not yet allowed.
    retry.release();
    await (await retry503).finished();
    // Wait for a browser paint after the completed retry, rather than an arbitrary sleep.
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    await hidden();
    expect(state.stepResponseStarts).toEqual([403, 503, 503]);

    const recovery = stepResponse(200, 4);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect.poll(() => state.stepResponseStarts).toEqual([403, 503, 503, 200]);
    await hidden(); // Even the authorized request must finish before restoring cached bodies.
    authorized.release();
    await (await recovery).finished();
    await expect(result).toBeVisible();
    await expect(raw).toHaveCount(1);
    expect(state.stepResponses).toHaveLength(0);
  });
}

for (const bound of [true, false]) {
  test(`Historical snapshot binding=${bound} is independent of the opposite current revision`, async ({
    page,
  }) => {
    const state = initial(bound ? "bound" : "ordinary");
    await open(page, state);
    await page.getByRole("button", { name: "Run workflow", exact: true }).click();
    await expect.poll(() => state.runs.length).toBe(1);
    complete(state);
    state.workflow.definition = graph(bound ? "ordinary" : "bound");
    state.workflow.revision = 4;
    await page.reload();
    await page.getByRole("button", { name: new RegExp(state.runs[0]!.id) }).click();
    const result = page.getByRole("region", { name: "Knowledge Agent Answer", exact: true });
    if (bound) await expect(result).toContainText("Actual workflow answer");
    else {
      await expect(page.locator("pre").filter({ hasText: "ordinary Agent output" })).toBeVisible();
      await expect(result).toHaveCount(0);
    }
    expect(state.runs[0]!.workflow_revision).toBe(3);
  });
}

test("Knowledge Agent no_evidence is not a failed Run or invented source", async ({ page }) => {
  const state = initial("bound");
  state.askStatus = "no_evidence";
  await open(page, state);
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect.poll(() => state.runs.length).toBe(1);
  complete(state);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  const result = page.getByRole("region", { name: "Knowledge Agent Answer", exact: true });
  await expect(result).toContainText("Insufficient supporting evidence");
  await expect(result.getByRole("listitem")).toHaveCount(0);
  await expect(page.locator("p").filter({ hasText: /^Status: completed$/ })).toBeVisible();
});

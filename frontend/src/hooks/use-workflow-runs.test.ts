import { describe, expect, it } from "vitest";

import { qk } from "@/lib/query-keys";

import { workflowRunRefetchInterval } from "./use-workflow-runs";

describe("workflow run query isolation and polling", () => {
  it("isolates users, workflows, runs, and pagination", () => {
    expect(qk.workflowRuns.list("user-a", "workflow-a", 0, 10)).not.toEqual(
      qk.workflowRuns.list("user-b", "workflow-a", 0, 10),
    );
    expect(qk.workflowRuns.list("user-a", "workflow-a", 0, 10)).not.toEqual(
      qk.workflowRuns.list("user-a", "workflow-b", 0, 10),
    );
    expect(qk.workflowRuns.list("user-a", "workflow-a", 0, 10)).not.toEqual(
      qk.workflowRuns.list("user-a", "workflow-a", 10, 10),
    );
    expect(qk.workflowRuns.detail("user-a", "workflow-a", "run-a")).not.toEqual(
      qk.workflowRuns.detail("user-a", "workflow-a", "run-b"),
    );
  });

  it("polls active runs, slows paused runs, and stops for every terminal state", () => {
    expect(workflowRunRefetchInterval("pending")).toBe(3000);
    expect(workflowRunRefetchInterval("running")).toBe(3000);
    expect(workflowRunRefetchInterval("paused")).toBe(10000);
    expect(workflowRunRefetchInterval("completed")).toBe(false);
    expect(workflowRunRefetchInterval("failed")).toBe(false);
    expect(workflowRunRefetchInterval("cancelled")).toBe(false);
    expect(workflowRunRefetchInterval(undefined)).toBe(false);
  });
});

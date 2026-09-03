import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  Database,
  GitBranch,
  Github,
  KeyRound,
  Layers3,
  Network,
  PlayCircle,
  ServerCog,
  ShieldCheck,
  Workflow,
} from "lucide-react";

import type { Locale } from "@/i18n";
import { APP_DESCRIPTION, APP_NAME, ROUTES } from "@/lib/constants";
import { pageMetadata } from "@/lib/seo";

const PRODUCT_NAME = "AgentForge";
const REPOSITORY_URL = "https://github.com/WmsL2/agentforge";

const FOUNDATION_CAPABILITIES = [
  {
    title: "Application foundation",
    description:
      "FastAPI backend and Next.js frontend provide the HTTP, UI, routing, and application shell.",
    icon: Layers3,
  },
  {
    title: "Authentication & sessions",
    description:
      "JWT-based authentication, users, sessions, protected routes, and backend authorization are in place.",
    icon: KeyRound,
  },
  {
    title: "Persistence layer",
    description:
      "PostgreSQL, SQLAlchemy, repositories, services, and Alembic migrations form the persistence foundation.",
    icon: Database,
  },
  {
    title: "Async infrastructure",
    description:
      "Redis and Celery provide the broker and background execution infrastructure required by later platform work.",
    icon: ServerCog,
  },
  {
    title: "Delivery baseline",
    description:
      "Docker Compose and GitHub Actions provide repeatable local environments and continuous integration.",
    icon: Boxes,
  },
  {
    title: "Quality baseline",
    description:
      "Ruff, pytest, ESLint, TypeScript, Vitest, Playwright, build checks, and CI guard the engineering foundation.",
    icon: CheckCircle2,
  },
] as const;

const PLATFORM_EXPANSION = [
  {
    title: "Agent Runtime",
    description:
      "A runtime abstraction for model execution, agent loops, state transitions, and pluggable execution backends.",
    icon: PlayCircle,
  },
  {
    title: "Tool / MCP Platform",
    description:
      "Tool registration, schema normalization, execution policy, MCP connectivity, and controlled tool invocation.",
    icon: Network,
  },
  {
    title: "Durable Execution",
    description:
      "Checkpoint persistence, pause and resume semantics, recovery, and Human-in-the-Loop control points.",
    icon: GitBranch,
  },
  {
    title: "Run Observability",
    description:
      "Structured Run, Step, and Trace records for debugging, replay, operational visibility, and auditability.",
    icon: ShieldCheck,
  },
  {
    title: "Workspace / RBAC",
    description:
      "Enterprise resource boundaries and role-based access control for future multi-user platform operation.",
    icon: Boxes,
  },
] as const;

const ROADMAP = [
  {
    version: "v0.1",
    title: "Foundation",
    status: "Completed",
    description:
      "Establish and validate the engineering foundation before building AgentForge-owned platform capabilities.",
  },
  {
    version: "v0.2",
    title: "Workflow Core",
    status: "Current",
    description:
      "Validated workflow definitions, DAG validation, deterministic execution, run lifecycle, persistence, and history.",
  },
  {
    version: "Later",
    title: "Platform Expansion",
    status: "Planned",
    description:
      "Add durable execution, Tool/MCP integration, observability, enterprise resource boundaries, and richer orchestration.",
  },
] as const;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const { locale } = await params;

  return pageMetadata({
    title: APP_NAME,
    description: APP_DESCRIPTION,
    path: "/",
    locale,
  });
}

export default function HomePage() {
  return (
    <div className="bg-background text-foreground min-h-screen">
      <header className="border-foreground/10 bg-background/90 sticky top-0 z-40 border-b backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <a href="#main" className="font-display text-lg font-semibold tracking-tight">
            {PRODUCT_NAME}
          </a>

          <nav
            aria-label="Primary navigation"
            className="text-foreground/65 hidden items-center gap-6 text-sm md:flex"
          >
            <a className="hover:text-foreground transition-colors" href="#foundation">
              Foundation
            </a>
            <a className="hover:text-foreground transition-colors" href="#architecture">
              Architecture
            </a>
            <a className="hover:text-foreground transition-colors" href="#roadmap">
              Roadmap
            </a>
          </nav>

          <div className="flex items-center gap-2">
            <Link
              href={ROUTES.LOGIN}
              className="text-foreground/70 hover:text-foreground hidden rounded-lg px-3 py-2 text-sm font-medium transition-colors sm:inline-flex"
            >
              Sign in
            </Link>
            <Link
              href={ROUTES.DASHBOARD}
              className="bg-foreground text-background hover:bg-foreground/90 inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
            >
              Open app
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="border-foreground/10 relative overflow-hidden border-b">
          <div
            aria-hidden
            className="from-brand/10 via-background to-background absolute inset-0 bg-gradient-to-br"
          />

          <div className="relative mx-auto grid max-w-7xl gap-14 px-5 py-20 sm:px-8 md:py-28 lg:grid-cols-[1.15fr_0.85fr] lg:items-center lg:py-32">
            <div>
              <div className="border-foreground/10 bg-foreground/[0.03] mb-6 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-xs">
                <span className="bg-brand h-2 w-2 rounded-full" />
                v0.2 · Workflow Core
              </div>

              <h1 className="font-display max-w-4xl text-4xl leading-[1.05] font-bold tracking-tight sm:text-5xl lg:text-6xl">
                Enterprise infrastructure for{" "}
                <span className="text-foreground/55">agent workflows.</span>
              </h1>

              <p className="text-foreground/65 mt-7 max-w-2xl text-base leading-7 sm:text-lg sm:leading-8">
                {PRODUCT_NAME} is an Enterprise Agent Workflow Platform. v0.1 established the
                reliable full-stack engineering foundation; v0.2 adds the AgentForge-owned Workflow
                Core for definition, validation, persistence, deterministic execution, and run
                lifecycle/history.
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href={ROUTES.DASHBOARD}
                  className="bg-foreground text-background hover:bg-foreground/90 inline-flex h-11 items-center gap-2 rounded-lg px-5 text-sm font-semibold transition-colors"
                >
                  Open dashboard
                  <ArrowRight className="h-4 w-4" />
                </Link>

                <a
                  href={REPOSITORY_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="border-foreground/15 hover:border-foreground/30 hover:bg-foreground/[0.03] inline-flex h-11 items-center gap-2 rounded-lg border px-5 text-sm font-semibold transition-colors"
                >
                  <Github className="h-4 w-4" />
                  View source
                </a>
              </div>

              <p className="text-foreground/45 mt-5 max-w-2xl text-sm leading-6">
                v0.2 implements the Workflow Core, not Agent Runtime, Tool/MCP execution,
                checkpoints, HITL, durable execution, or enterprise RBAC.
              </p>
            </div>

            <div className="border-foreground/10 bg-card/70 rounded-3xl border p-5 shadow-sm backdrop-blur sm:p-7">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-foreground/45 font-mono text-xs tracking-wider uppercase">
                    Platform status
                  </p>
                  <h2 className="font-display mt-1 text-xl font-semibold">
                    Foundation plus Workflow Core
                  </h2>
                </div>
                <div className="bg-brand/15 flex h-11 w-11 items-center justify-center rounded-xl">
                  <Layers3 className="h-5 w-5" />
                </div>
              </div>

              <div className="mt-7 space-y-3">
                <div className="border-foreground/10 bg-background rounded-2xl border p-4">
                  <div className="flex items-center justify-between gap-4">
                    <span className="font-medium">Web engineering foundation</span>
                    <span className="bg-brand/15 rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold uppercase">
                      Validated
                    </span>
                  </div>
                  <p className="text-foreground/55 mt-2 text-sm leading-6">
                    Auth, database, Redis, Celery, frontend, Docker, tests, and CI.
                  </p>
                </div>

                <div className="border-foreground/10 bg-background rounded-2xl border p-4">
                  <div className="flex items-center justify-between gap-4">
                    <span className="font-medium">Workflow Core</span>
                    <span className="bg-brand/15 rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold uppercase">
                      Current
                    </span>
                  </div>
                  <p className="text-foreground/55 mt-2 text-sm leading-6">
                    Definition, DAG validation, deterministic execution, run persistence, and history.
                  </p>
                </div>
              </div>

              <div className="border-foreground/10 mt-5 border-t pt-5">
                <p className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
                  Design principle
                </p>
                <p className="text-foreground/75 mt-2 text-sm leading-6">
                  Reuse mature web infrastructure. Own the agent platform architecture.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section id="foundation" className="mx-auto max-w-7xl px-5 py-20 sm:px-8 md:py-24">
          <div className="max-w-3xl">
            <p className="text-brand font-mono text-xs font-semibold tracking-wider uppercase">
              v0.1 Foundation · completed
            </p>
            <h2 className="font-display mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              What is implemented today
            </h2>
            <p className="text-foreground/60 mt-4 text-base leading-7">
              These capabilities belong to the engineering foundation. They make the platform
              deployable, testable, and support the AgentForge-owned Workflow Core in v0.2.
            </p>
          </div>

          <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {FOUNDATION_CAPABILITIES.map((capability) => {
              const Icon = capability.icon;

              return (
                <article
                  key={capability.title}
                  className="border-foreground/10 bg-card rounded-2xl border p-6"
                >
                  <div className="bg-foreground/[0.06] flex h-10 w-10 items-center justify-center rounded-xl">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="font-display mt-5 text-lg font-semibold">{capability.title}</h3>
                  <p className="text-foreground/60 mt-2 text-sm leading-6">
                    {capability.description}
                  </p>
                </article>
              );
            })}
          </div>
        </section>

        <section id="architecture" className="border-foreground/10 bg-foreground/[0.025] border-y">
          <div className="mx-auto max-w-7xl px-5 py-20 sm:px-8 md:py-24">
            <div className="max-w-3xl">
              <p className="text-brand font-mono text-xs font-semibold tracking-wider uppercase">
                Ownership boundary
              </p>
              <h2 className="font-display mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
                Mature foundation. Self-built platform core.
              </h2>
              <p className="text-foreground/60 mt-4 text-base leading-7">
                AgentForge is not defined by the starter stack. The starter stack provides common
                web engineering capabilities; the Agent Platform Core is the part designed and
                implemented specifically for AgentForge.
              </p>
            </div>

            <div className="mt-12 grid gap-6 lg:grid-cols-[1fr_auto_1fr] lg:items-stretch">
              <div className="border-foreground/10 bg-background rounded-3xl border p-7">
                <div className="flex items-center gap-3">
                  <div className="bg-foreground/[0.06] flex h-10 w-10 items-center justify-center rounded-xl">
                    <ServerCog className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
                      Inherited foundation
                    </p>
                    <h3 className="font-display text-xl font-semibold">
                      Web Engineering Foundation
                    </h3>
                  </div>
                </div>

                <div className="text-foreground/65 mt-6 flex flex-wrap gap-2 text-sm">
                  {[
                    "FastAPI",
                    "Authentication",
                    "PostgreSQL",
                    "SQLAlchemy",
                    "Redis",
                    "Celery",
                    "Next.js",
                    "Docker",
                    "CI",
                  ].map((item) => (
                    <span
                      key={item}
                      className="border-foreground/10 bg-foreground/[0.03] rounded-lg border px-3 py-1.5"
                    >
                      {item}
                    </span>
                  ))}
                </div>

                <p className="text-foreground/55 mt-6 text-sm leading-6">
                  Purpose: provide reliable application infrastructure without spending project
                  effort rebuilding solved web engineering problems.
                </p>
              </div>

              <div className="hidden items-center justify-center lg:flex">
                <ArrowRight className="text-foreground/30 h-7 w-7" />
              </div>

              <div className="border-brand/30 bg-brand/[0.04] rounded-3xl border p-7">
                <div className="flex items-center gap-3">
                  <div className="bg-brand/15 flex h-10 w-10 items-center justify-center rounded-xl">
                    <Workflow className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
                      AgentForge owned
                    </p>
                    <h3 className="font-display text-xl font-semibold">Agent Platform Core</h3>
                  </div>
                </div>

                <div className="text-foreground/65 mt-6 flex flex-wrap gap-2 text-sm">
                  {[
                    "Workflow Core",
                    "Agent Runtime",
                    "Tool / MCP",
                    "Checkpoint / HITL",
                    "Run / Step / Trace",
                    "Workspace / RBAC",
                  ].map((item) => (
                    <span
                      key={item}
                      className="border-brand/20 bg-background/60 rounded-lg border px-3 py-1.5"
                    >
                      {item}
                    </span>
                  ))}
                </div>

                <p className="text-foreground/55 mt-6 text-sm leading-6">
                  Workflow Core is implemented in v0.2. Agent Runtime, Tool/MCP, checkpoints,
                  observability, and workspace boundaries remain planned expansion work.
                </p>
              </div>
            </div>

            <div className="mt-12">
              <div className="mb-6 flex items-center gap-3">
                <GitBranch className="h-5 w-5" />
                <h3 className="font-display text-xl font-semibold">Planned platform expansion</h3>
              </div>

              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {PLATFORM_EXPANSION.map((capability) => {
                  const Icon = capability.icon;

                  return (
                    <article
                      key={capability.title}
                      className="border-foreground/10 bg-background rounded-2xl border p-5"
                    >
                      <div className="flex items-center gap-3">
                        <Icon className="text-foreground/70 h-5 w-5" />
                        <h4 className="font-semibold">{capability.title}</h4>
                      </div>
                      <p className="text-foreground/55 mt-3 text-sm leading-6">
                        {capability.description}
                      </p>
                    </article>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        <section id="roadmap" className="mx-auto max-w-7xl px-5 py-20 sm:px-8 md:py-24">
          <div className="max-w-3xl">
            <p className="text-brand font-mono text-xs font-semibold tracking-wider uppercase">
              Development roadmap
            </p>
            <h2 className="font-display mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Build the platform in layers
            </h2>
            <p className="text-foreground/60 mt-4 text-base leading-7">
              Each version should leave the repository in a validated state before the next platform
              layer is added.
            </p>
          </div>

          <div className="mt-10 grid gap-4 lg:grid-cols-3">
            {ROADMAP.map((item) => (
              <article
                key={`${item.version}-${item.title}`}
                className="border-foreground/10 bg-card rounded-2xl border p-6"
              >
                <div className="flex items-center justify-between gap-4">
                  <span className="font-mono text-sm font-semibold">{item.version}</span>
                  <span
                    className={
                      item.status === "Current"
                        ? "bg-brand/15 rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold uppercase"
                        : "border-foreground/15 text-foreground/50 rounded-full border px-2.5 py-1 font-mono text-[11px] font-semibold uppercase"
                    }
                  >
                    {item.status}
                  </span>
                </div>

                <h3 className="font-display mt-5 text-xl font-semibold">{item.title}</h3>
                <p className="text-foreground/60 mt-3 text-sm leading-6">{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="border-foreground/10 bg-foreground/[0.025] border-t">
          <div className="mx-auto max-w-7xl px-5 py-16 sm:px-8">
            <div className="border-foreground/10 bg-card grid gap-8 rounded-3xl border p-7 md:grid-cols-[1fr_auto] md:items-center md:p-10">
              <div>
                <p className="text-brand font-mono text-xs font-semibold tracking-wider uppercase">
                  AgentForge v0.2
                </p>
                <h2 className="font-display mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
                  Foundation established. Workflow Core is current.
                </h2>
                <p className="text-foreground/60 mt-3 max-w-2xl text-sm leading-6 sm:text-base">
                  Inspect the repository, run the stack locally, or continue into the authenticated
                  application shell.
                </p>
              </div>

              <div className="flex flex-wrap gap-3 md:justify-end">
                <a
                  href={REPOSITORY_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="border-foreground/15 hover:border-foreground/30 inline-flex h-11 items-center gap-2 rounded-lg border px-5 text-sm font-semibold transition-colors"
                >
                  <Github className="h-4 w-4" />
                  Repository
                </a>
                <Link
                  href={ROUTES.DASHBOARD}
                  className="bg-foreground text-background hover:bg-foreground/90 inline-flex h-11 items-center gap-2 rounded-lg px-5 text-sm font-semibold transition-colors"
                >
                  Open app
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-foreground/10 border-t">
        <div className="text-foreground/50 mx-auto flex max-w-7xl flex-col gap-3 px-5 py-8 text-sm sm:px-8 md:flex-row md:items-center md:justify-between">
          <p>
            {PRODUCT_NAME} · {APP_DESCRIPTION}
          </p>
          <p>v0.2 Workflow Core</p>
        </div>
      </footer>
    </div>
  );
}

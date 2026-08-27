import Link from "next/link";
import {
  CheckCircle2,
  Layers3,
} from "lucide-react";

import {
  APP_DESCRIPTION,
  APP_NAME,
  ROUTES,
} from "@/lib/constants";

const FOUNDATION_CAPABILITIES = [
  "JWT authentication and session management",
  "PostgreSQL persistence with SQLAlchemy and Alembic",
  "Redis and Celery background infrastructure",
  "Docker, automated tests, and continuous integration",
] as const;

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="bg-background text-foreground min-h-screen lg:grid lg:grid-cols-[1.1fr_minmax(0,560px)]">
      <main
        id="main"
        className="theme-light bg-background text-foreground relative flex flex-col"
      >
        <header className="flex h-16 items-center px-6 sm:px-10">
          <Link
            href={ROUTES.HOME}
            className="font-display text-foreground inline-flex items-center gap-2 text-base font-bold tracking-tight"
          >
            <span
              aria-hidden
              className="bg-brand inline-block h-2.5 w-2.5 rounded-full"
            />

            {APP_NAME}
          </Link>
        </header>

        <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
          <div className="w-full max-w-md">
            {children}
          </div>
        </div>

        <footer className="text-foreground/50 px-6 py-6 font-mono text-[11px] tracking-wider uppercase sm:px-10">
          © {new Date().getFullYear()} {APP_NAME}
        </footer>
      </main>

      <aside className="hidden p-5 lg:block lg:p-6">
        <div className="theme-dark bg-background text-foreground border-foreground/10 relative flex h-full flex-col justify-between overflow-hidden rounded-3xl border p-10 shadow-2xl lg:p-12">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
          >
            <div className="bg-grid absolute inset-0 opacity-[0.55]" />

            <div className="bg-brand/[0.28] absolute -top-32 -right-20 h-[460px] w-[460px] rounded-full blur-[120px]" />

            <div className="bg-brand/[0.12] absolute -bottom-20 -left-10 h-[320px] w-[420px] rounded-full blur-[140px]" />
          </div>

          <div className="relative z-10">
            <span className="eyebrow-badge inline-flex items-center gap-2">
              <Layers3
                className="h-3 w-3"
                aria-hidden
              />

              AgentForge v0.1 · Foundation
            </span>
          </div>

          <div className="relative z-10 max-w-[30rem]">
            <h2 className="text-display-lg text-foreground mb-6 leading-[1.05]">
              Enterprise infrastructure for agent workflows.
            </h2>

            <p className="text-foreground/65 max-w-md text-base leading-relaxed">
              {APP_DESCRIPTION}. The current release establishes
              the application foundation required before the
              AgentForge-owned workflow and runtime core is built.
            </p>

            <ul className="mt-10 space-y-3">
              {FOUNDATION_CAPABILITIES.map((capability) => (
                <li
                  key={capability}
                  className="text-foreground/85 flex items-start gap-3 text-sm"
                >
                  <CheckCircle2
                    aria-hidden
                    className="text-brand mt-0.5 h-4 w-4 shrink-0"
                  />

                  <span>{capability}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="border-foreground/10 bg-card/40 relative z-10 max-w-md rounded-2xl border p-5 backdrop-blur-xl">
            <p className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
              Architecture boundary
            </p>

            <p className="text-foreground/85 mt-3 text-sm leading-relaxed">
              Mature web engineering capabilities form the
              foundation. Workflow Engine, Agent Runtime,
              Tool/MCP, durable execution, observability, and
              enterprise resource boundaries are developed as
              AgentForge-owned platform capabilities in later
              versions.
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}
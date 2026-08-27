import Link from "next/link";

import { ROUTES } from "@/lib/constants";

interface FooterColumn {
  title: string;
  links: {
    label: string;
    href: string;
  }[];
}

interface MarketingFooterProps {
  brand: string;
  tagline?: string;
  operationalLabel?: string;
  columns: FooterColumn[];
  legal?: {
    label: string;
    href: string;
  }[];
}

export function MarketingFooter({
  brand,
  tagline,
  operationalLabel,
  columns,
  legal = [],
}: MarketingFooterProps) {
  return (
    <footer className="theme-dark bg-background text-foreground grain relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-64 left-1/2 -z-10 h-[560px] w-[860px] -translate-x-1/2 rounded-full blur-3xl"
        style={{
          background:
            "radial-gradient(circle, oklch(from var(--color-brand) l c h / 0.22), transparent 65%)",
        }}
      />

      <div
        aria-hidden
        className="bg-dots pointer-events-none absolute inset-0 -z-10 opacity-70"
      />

      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{
          background:
            "linear-gradient(to right, transparent, oklch(from var(--color-foreground) l c h / 0.18), transparent)",
        }}
      />

      <div className="relative mx-auto w-full max-w-7xl px-6 py-20 md:px-10 md:py-24">
        <div className="grid gap-12 md:grid-cols-2 lg:grid-cols-[1.6fr_1fr_1fr]">
          <div className="max-w-sm">
            <Link
              href={ROUTES.HOME}
              className="font-display text-foreground inline-flex items-center gap-2.5 text-2xl font-bold tracking-tight"
            >
              <span
                aria-hidden
                className="bg-brand inline-block h-3 w-3 animate-pulse rounded-full"
                style={{
                  boxShadow:
                    "0 0 20px var(--color-brand), 0 0 6px var(--color-brand)",
                }}
              />

              {brand}
            </Link>

            {tagline && (
              <p className="text-foreground/60 mt-5 text-base leading-relaxed">
                {tagline}
              </p>
            )}
          </div>

          {columns.map((column) => (
            <div key={column.title}>
              <h3 className="eyebrow text-foreground/45 mb-4">
                {column.title}
              </h3>

              <ul className="space-y-3">
                {column.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-foreground/70 hover:text-foreground text-sm font-medium transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="border-foreground/10 mt-16 border-t pt-8">
          <div className="text-foreground/50 flex flex-col gap-5 font-mono text-xs md:flex-row md:items-center md:justify-between">
            {operationalLabel && (
              <p className="inline-flex items-center gap-2">
                <span
                  className="bg-brand h-1.5 w-1.5 animate-pulse rounded-full"
                  style={{
                    boxShadow: "0 0 10px var(--color-brand)",
                  }}
                />

                {operationalLabel}
              </p>
            )}

            {legal.length > 0 && (
              <ul className="flex flex-wrap items-center gap-x-6 gap-y-2">
                {legal.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="hover:text-foreground/90 transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            <p>
              © {new Date().getFullYear()} {brand}
            </p>
          </div>
        </div>
      </div>
    </footer>
  );
}
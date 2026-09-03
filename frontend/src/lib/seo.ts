/**
 * Single source of truth for AgentForge SEO metadata.
 *
 * Public-page metadata helpers such as the root layout, per-page metadata,
 * sitemap, robots, manifest, and Open Graph image generation read from here.
 *
 * ENV:
 * NEXT_PUBLIC_SITE_URL = canonical site origin without a trailing slash.
 * Local development falls back to http://localhost:3000.
 */

import type { Metadata } from "next";

import { defaultLocale, locales } from "@/i18n";
import { APP_DESCRIPTION, APP_NAME } from "@/lib/constants";

export const SITE = {
  name: APP_NAME,

  /**
   * Product identity used by title templates and Open Graph defaults.
   *
   * Keep this aligned with the AgentForge ownership boundary: v0.1 established
   * the engineering foundation, and v0.2 adds the self-built Workflow Core.
   */
  tagline: APP_DESCRIPTION,

  /**
   * Default public description.
   *
   * This describes the implemented Workflow Core without presenting later
   * runtime, tool, or durable-execution capabilities as complete.
   */
  description:
    "AgentForge is an enterprise agent workflow platform: v0.1 established the full-stack foundation, and v0.2 adds a self-built Workflow Core for validated DAG definitions, deterministic execution, and run history.",

  /** Canonical absolute origin. No trailing slash. */
  url:
    (process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") as string | undefined) ??
    "http://localhost:3000",

  /**
   * Twitter/X handle for twitter:site.
   * Keep empty until an official AgentForge account exists.
   */
  twitter: "",

  /** Theme color used by metadata consumers such as browser chrome and PWA surfaces. */
  themeColor: "#0E0E0C",

  /**
   * Product and architecture keywords.
   *
   * These identify the domain AgentForge is being built for. They do not imply
   * that Agent Runtime, Tool/MCP, or durable-execution capabilities are complete.
   */
  keywords: [
    "AgentForge",
    "enterprise agent workflow platform",
    "AI agent platform",
    "agent workflow",
    "workflow orchestration",
    "agent runtime",
    "tool execution",
    "Model Context Protocol",
    "MCP",
    "durable execution",
    "Human-in-the-Loop",
    "HITL",
    "agent observability",
  ],

  /** Locale defaults inherited from the application i18n configuration. */
  defaultLocale,
  locales: [...locales],
} as const;

/** Map application locale codes to BCP-47 / Open Graph locale values. */
export const OG_LOCALE: Record<(typeof locales)[number], string> = {
  en: "en_US",
  pl: "pl_PL",
};

interface PageMetaInput {
  /** Page-specific title fragment. The helper appends the AgentForge brand when needed. */
  title: string;

  /** Page-specific description. */
  description: string;

  /**
   * Path without the locale prefix.
   *
   * Examples:
   * "/" or "/about".
   */
  path?: string;

  /** Active locale. Defaults to the configured site locale. */
  locale?: (typeof locales)[number];

  /** Prevent search-engine indexing for internal or non-public pages. */
  noindex?: boolean;

  /** Override the default dynamically generated Open Graph image. */
  ogImage?: string;
}

/** Build a complete Next.js Metadata object for a public AgentForge page. */
export function pageMetadata(input: PageMetaInput): Metadata {
  const locale = input.locale ?? SITE.defaultLocale;
  const path = normalizePath(input.path ?? "/");
  const localizedPath = path === "/" ? `/${locale}` : `/${locale}${path}`;
  const canonical = `${SITE.url}${localizedPath}`;

  const title =
    input.title === SITE.name ? SITE.name : `${input.title} | ${SITE.name}`;

  const ogImageUrl = input.ogImage ?? `${SITE.url}/opengraph-image`;

  return {
    title,
    description: input.description,
    keywords: [...SITE.keywords],

    alternates: {
      canonical,
      languages: Object.fromEntries(
        SITE.locales.map((loc) => [
          loc,
          `${SITE.url}${path === "/" ? `/${loc}` : `/${loc}${path}`}`,
        ]),
      ),
    },

    openGraph: {
      title,
      description: input.description,
      url: canonical,
      siteName: SITE.name,
      type: "website",
      locale: OG_LOCALE[locale],
      alternateLocale: SITE.locales
        .filter((loc) => loc !== locale)
        .map((loc) => OG_LOCALE[loc]),
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${SITE.name} — ${SITE.tagline}`,
        },
      ],
    },

    twitter: {
      card: "summary_large_image",
      title,
      description: input.description,
      images: [ogImageUrl],
      ...(SITE.twitter
        ? {
            site: SITE.twitter,
            creator: SITE.twitter,
          }
        : {}),
    },

    robots: input.noindex
      ? {
          index: false,
          follow: false,
        }
      : {
          index: true,
          follow: true,
          "max-image-preview": "large",
          "max-snippet": -1,
        },
  };
}

function normalizePath(path: string): string {
  if (!path.startsWith("/")) {
    return `/${path}`;
  }

  if (path.length > 1 && path.endsWith("/")) {
    return path.slice(0, -1);
  }

  return path;
}

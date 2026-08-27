import type { MetadataRoute } from "next";

import { SITE } from "@/lib/seo";

/**
 * Public-only sitemap.
 *
 * Authenticated application routes such as dashboard, chat, admin, and
 * settings are intentionally excluded.
 *
 * Several starter-template marketing routes are still preserved as temporary
 * compatibility redirects during the AgentForge v0.1 takeover. They remain in
 * PUBLIC_PATHS for now and will be reviewed together in the dedicated public
 * route / sitemap cleanup.
 *
 * Template blog posts are deliberately excluded because they are no longer
 * AgentForge content.
 */
type Freq = MetadataRoute.Sitemap[number]["changeFrequency"];

const PUBLIC_PATHS: {
  path: string;
  changeFrequency: Freq;
  priority: number;
}[] = [
  { path: "/", changeFrequency: "weekly", priority: 1.0 },
  { path: "/pricing", changeFrequency: "weekly", priority: 0.9 },
  { path: "/about", changeFrequency: "monthly", priority: 0.7 },
  { path: "/changelog", changeFrequency: "weekly", priority: 0.6 },
  { path: "/help", changeFrequency: "weekly", priority: 0.7 },
  { path: "/contact", changeFrequency: "monthly", priority: 0.6 },
  { path: "/security", changeFrequency: "monthly", priority: 0.6 },
  { path: "/community", changeFrequency: "monthly", priority: 0.6 },
  { path: "/legal/terms", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/privacy", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/cookies", changeFrequency: "yearly", priority: 0.3 },
  { path: "/login", changeFrequency: "yearly", priority: 0.3 },
  { path: "/register", changeFrequency: "yearly", priority: 0.5 },
];

function entryFor(
  path: string,
  changeFrequency: Freq,
  priority: number,
  lastModified: Date,
): MetadataRoute.Sitemap {
  const out: MetadataRoute.Sitemap = [];

  for (const locale of SITE.locales) {
    const tail = path === "/" ? "" : path;
    const url = `${SITE.url}/${locale}${tail}`;
    const languages: Record<string, string> = Object.fromEntries(
      SITE.locales.map((l) => [l, `${SITE.url}/${l}${tail}`]),
    );

    languages["x-default"] = `${SITE.url}/${SITE.defaultLocale}${tail}`;

    out.push({
      url,
      lastModified,
      changeFrequency,
      priority,
      alternates: { languages },
    });
  }

  return out;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const entries: MetadataRoute.Sitemap = [];

  for (const { path, changeFrequency, priority } of PUBLIC_PATHS) {
    entries.push(...entryFor(path, changeFrequency, priority, now));
  }

  return entries;
}
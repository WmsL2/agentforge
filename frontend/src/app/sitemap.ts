import type { MetadataRoute } from "next";

import { SITE } from "@/lib/seo";

/**
 * Public sitemap for canonical AgentForge pages.
 *
 * Authenticated application routes are intentionally excluded.
 * Starter-template marketing URLs that remain only as compatibility redirects
 * are also excluded because they are not canonical AgentForge content.
 */
type Freq = MetadataRoute.Sitemap[number]["changeFrequency"];

const PUBLIC_PATHS: {
  path: string;
  changeFrequency: Freq;
  priority: number;
}[] = [
  { path: "/", changeFrequency: "weekly", priority: 1.0 },
  { path: "/legal/terms", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/privacy", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/cookies", changeFrequency: "yearly", priority: 0.3 },
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
      SITE.locales.map((localeCode) => [
        localeCode,
        `${SITE.url}/${localeCode}${tail}`,
      ]),
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
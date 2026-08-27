import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Transitional compatibility route for the removed template blog.
 *
 * The starter template shipped with generic engineering and product articles
 * that are not AgentForge project publications and must not be presented as
 * AgentForge-owned content.
 *
 * Existing template navigation may still reference `/blog`, so keep this
 * lightweight route temporarily and redirect visitors to the AgentForge
 * landing page. A real AgentForge blog can be introduced later with verified
 * project-owned content.
 */
export default async function BlogPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}
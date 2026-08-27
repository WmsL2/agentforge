import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Compatibility route for historical starter-template blog URLs.
 *
 * Template MDX posts are removed from AgentForge v0.1 because they are not
 * AgentForge-authored product content. Preserve the dynamic URL temporarily so
 * previously generated links do not fail while the remaining public marketing
 * routes are being cleaned up.
 */
export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ locale: Locale; slug: string }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}
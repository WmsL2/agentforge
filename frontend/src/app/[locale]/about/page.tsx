import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Transitional compatibility route for the removed template about page.
 *
 * The starter template included generic SaaS company storytelling, team
 * profiles, product statistics, pricing links, and sales-oriented calls to
 * action that did not describe the AgentForge v0.1 Foundation release.
 *
 * Some remaining template navigation still references `/about`, so keep this
 * lightweight route temporarily and redirect visitors to the AgentForge
 * landing page. The route can be removed once the remaining marketing
 * navigation and public-route metadata are cleaned up during v0.1.
 */
export default async function AboutPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}

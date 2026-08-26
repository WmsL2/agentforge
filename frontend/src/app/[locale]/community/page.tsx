import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Transitional compatibility route for the removed template community page.
 *
 * The starter template advertised community channels and programs that are not
 * part of the current AgentForge v0.1 Foundation release.
 *
 * Some remaining template navigation still references `/community`, so keep
 * this lightweight route temporarily and redirect visitors to the AgentForge
 * landing page. The route can be removed once the remaining marketing
 * navigation and public-route metadata are cleaned up during v0.1.
 */
export default async function CommunityPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}
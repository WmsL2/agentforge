import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Transitional compatibility route for the removed template changelog.
 *
 * The original starter template shipped with its own fictional release
 * history. Those entries do not describe AgentForge and must not be presented
 * as AgentForge product releases.
 *
 * Existing template navigation may still reference `/changelog`, so keep this
 * lightweight route temporarily and redirect visitors to the AgentForge
 * landing page. The route can be removed once the remaining marketing
 * navigation and public-route metadata are cleaned up during v0.1.
 */
export default async function ChangelogPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}
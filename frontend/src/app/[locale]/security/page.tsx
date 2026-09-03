import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Transitional compatibility route for the removed template security page.
 *
 * The starter template included broad security, infrastructure, policy, and
 * vulnerability-reporting claims that do not represent a formally established
 * AgentForge security or compliance program in the v0.1 Foundation
 * release.
 *
 * Some remaining template navigation and legal content still reference
 * `/security`, so keep this lightweight route temporarily and redirect
 * visitors to the AgentForge landing page. The route can be removed or
 * replaced with a verified AgentForge security page once the remaining public
 * surface is cleaned up.
 */
export default async function SecurityPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}

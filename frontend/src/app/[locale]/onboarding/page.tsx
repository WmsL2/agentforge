import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";
import { ROUTES } from "@/lib/constants";

/**
 * Transitional compatibility route for the removed starter-template
 * onboarding flow.
 *
 * AgentForge v0.1 does not expose the template's framework-selection,
 * data-connection, or team-invitation setup wizard. Existing links are kept
 * temporarily and redirected to the authenticated dashboard.
 */
export default async function OnboardingPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}${ROUTES.DASHBOARD}`);
}
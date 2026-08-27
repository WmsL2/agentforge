import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";
import { ROUTES } from "@/lib/constants";

/**
 * Compatibility route for historical starter-template onboarding step URLs.
 *
 * The original wizard advertised framework selection, data connection, and
 * team setup that do not represent the AgentForge v0.1 Foundation product.
 * Preserve the URL temporarily and redirect authenticated users toward the
 * actual application surface.
 */
export default async function OnboardingStepPage({
  params,
}: {
  params: Promise<{ locale: Locale; step: string }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}${ROUTES.DASHBOARD}`);
}
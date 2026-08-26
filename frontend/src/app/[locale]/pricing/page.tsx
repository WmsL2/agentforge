import { redirect } from "next/navigation";

import type { Locale } from "@/i18n";

/**
 * Transitional compatibility route for the removed template pricing surface.
 *
 * AgentForge v0.1 is a Foundation release and does not provide commercial
 * subscription plans, billing tiers, trials, or sales pricing.
 *
 * Some remaining template navigation still references `/pricing`. Keep this
 * route temporarily so those links do not become dead links while the rest of
 * the generic marketing surface is removed during the v0.1 takeover.
 */
export default async function PricingPage({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}) {
  const { locale } = await params;

  redirect(`/${locale}`);
}
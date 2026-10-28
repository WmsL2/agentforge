"use client";

import { useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { WorkflowDetail } from "@/components/workflow/workflow-detail";
import { useAuth } from "@/hooks";

export default function WorkflowDetailPage() {
  const t = useTranslations("workflows");
  const { user } = useAuth();
  if (!user) return <LoadingState label={t("loading")} />;
  return <WorkflowDetail userId={user.id} />;
}

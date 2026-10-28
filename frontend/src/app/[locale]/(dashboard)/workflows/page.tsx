"use client";

import { useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { WorkflowManagement } from "@/components/workflow/workflow-management";
import { useAuth } from "@/hooks";

export default function WorkflowsPage() {
  const t = useTranslations("workflows");
  const { user } = useAuth();
  if (!user) return <LoadingState label={t("loading")} />;
  return <WorkflowManagement userId={user.id} />;
}

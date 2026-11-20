"use client";
import { useTranslations } from "next-intl";
import { LoadingState } from "@/components/states";
import { useAuth } from "@/hooks";
import { KnowledgeManagement } from "@/components/knowledge/knowledge-management";

export default function KnowledgePage() {
  const t = useTranslations("knowledgeManagement");
  const { user, isLoading } = useAuth();
  if (!user || isLoading) return <LoadingState label={t("loading")} />;
  return <KnowledgeManagement userId={user.id} />;
}

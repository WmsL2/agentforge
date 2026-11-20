"use client";
import { useTranslations } from "next-intl";
import { LoadingState } from "@/components/states";
import { useAuth } from "@/hooks";
import { KnowledgeManagement } from "@/components/knowledge/knowledge-management";
import { useParams } from "next/navigation";

export default function KnowledgePage() {
  const t = useTranslations("knowledgeManagement");
  const { user, isLoading } = useAuth();
  const { knowledgeBaseId } = useParams<{ knowledgeBaseId: string }>();
  if (!user || isLoading) return <LoadingState label={t("loading")} />;
  return <KnowledgeManagement userId={user.id} knowledgeBaseId={knowledgeBaseId} />;
}

"use client";

import Link from "next/link";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, GitBranch, Network } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { useWorkflow } from "@/hooks";
import { ApiError, getApiErrorMessage } from "@/lib/api-client";
import { localizeHref } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";

export function WorkflowDetail({ userId }: { userId: string }) {
  const t = useTranslations("workflows");
  const params = useParams<{ workflowId: string }>();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const workflowId = params.workflowId;
  const query = useWorkflow(userId, workflowId);

  if (query.isLoading) return <LoadingState variant="skeleton-card" />;
  if (query.isError) {
    const description =
      query.error instanceof ApiError && query.error.status === 404
        ? t("errors.notFound")
        : getApiErrorMessage(
            query.error instanceof ApiError ? query.error.data : query.error,
            t("errors.server"),
          );
    return (
      <ErrorState
        title={t("errors.loadWorkflow")}
        description={description}
        cta={{ label: t("retry"), onClick: () => void query.refetch() }}
      />
    );
  }

  const workflow = query.data!;
  const workspaceId = searchParams.get("workspace_id") ?? workflow.workspace_id;
  const backHref = `${localizeHref(pathname, ROUTES.WORKFLOWS)}?workspace_id=${encodeURIComponent(workspaceId)}`;

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        eyebrow={t("detailEyebrow")}
        title={workflow.name}
        description={workflow.description || t("noDescription")}
        breadcrumbs={[{ label: t("title"), href: backHref }, { label: workflow.name }]}
        actions={
          <Button variant="outline" asChild>
            <Link href={backHref}>
              <ArrowLeft className="h-4 w-4" />
              {t("backToWorkflows")}
            </Link>
          </Button>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <SummaryCard
          label={t("columns.revision")}
          value={`r${workflow.revision}`}
          icon={GitBranch}
        />
        <SummaryCard
          label={t("nodes")}
          value={String(workflow.definition.nodes.length)}
          icon={Network}
        />
        <SummaryCard
          label={t("edges")}
          value={String(workflow.definition.edges.length)}
          icon={Network}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("definitionSummary")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {workflow.definition.nodes.map((node) => (
              <Badge key={node.id} variant="outline">
                {node.id}: {node.kind}
              </Badge>
            ))}
          </div>
          <p className="text-muted-foreground text-sm">{t("editorComingSoon")}</p>
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof GitBranch;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 pt-6">
        <div className="bg-muted flex h-10 w-10 items-center justify-center rounded-lg">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-muted-foreground text-xs uppercase">{label}</p>
          <p className="text-xl font-semibold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

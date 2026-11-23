"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ApiError } from "@/lib/api-client";
import { useKnowledgeSearch, useKnowledgeAsk } from "@/hooks/use-knowledge";
import { onKnowledgeClear, within } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import {
  Button,
  Card,
  CardContent,
  FormField,
  Input,
  Textarea,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui";
import { EmptyState, LoadingState, ErrorState } from "@/components/states";
import { Search } from "lucide-react";
import type {
  KnowledgeSearchRequest,
  KnowledgeSearchResponse,
  KnowledgeAskRequest,
  KnowledgeAskResponse,
  KnowledgeAgentSourceRead,
} from "@/types";
import { isAbort, useKnowledgeLease } from "./knowledge-ui";
import {
  normalizePlaygroundText,
  validatePlaygroundText,
  searchParameters,
  PLAYGROUND_TEXT_LIMIT,
  playgroundError,
} from "./knowledge-playground-utils";

export interface PlaygroundScope {
  userId: string;
  workspaceId: string;
  knowledgeBaseId: string;
  revalidateRead?: () => Promise<boolean>;
  revalidate: () => Promise<boolean>;
  checkBase: () => Promise<void>;
}
export function KnowledgePlayground(scope: PlaygroundScope) {
  const t = useTranslations("knowledgeManagement");
  const [mode, setMode] = useState("search"),
    [revoked, setRevoked] = useState(false);
  const [query, setQuery] = useState(""),
    [top, setTop] = useState("5"),
    [minimum, setMinimum] = useState(""),
    [question, setQuestion] = useState("");
  const key = useMemo(
    () => qk.knowledge.base(scope.userId, scope.workspaceId, scope.knowledgeBaseId),
    [scope.userId, scope.workspaceId, scope.knowledgeBaseId],
  );
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        if (within(key, prefix)) {
          setRevoked(true);
          setQuery("");
          setTop("5");
          setMinimum("");
          setQuestion("");
        }
      }),
    [key],
  );
  if (revoked)
    return (
      <section aria-label={t("playground.title")}>
        <p role="alert">{t("playground.scopeUnavailable")}</p>
      </section>
    );
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <h3 className="text-xl font-semibold">{t("playground.title")}</h3>
        <p>{t("playground.description")}</p>
        <Tabs value={mode} onValueChange={setMode}>
          <TabsList aria-label={t("playground.modes")}>
            <TabsTrigger value="search">{t("playground.search")}</TabsTrigger>
            <TabsTrigger value="ask">{t("playground.ask")}</TabsTrigger>
          </TabsList>
          <TabsContent value="search">
            {mode === "search" && (
              <KnowledgeSearchPanel
                {...scope}
                query={query}
                setQuery={setQuery}
                top={top}
                setTop={setTop}
                minimum={minimum}
                setMinimum={setMinimum}
              />
            )}
          </TabsContent>
          <TabsContent value="ask">
            {mode === "ask" && (
              <KnowledgeAskPanel {...scope} question={question} setQuestion={setQuestion} />
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
/** UI operation lease only; transport/latest-wins still belong to existing Knowledge Hooks. */
function usePlaygroundRequest<I, O>(
  scope: PlaygroundScope,
  operation: { mutateAsync: (input: I) => Promise<O>; cancel: () => void },
) {
  const capture = useKnowledgeLease(),
    t = useTranslations("knowledgeManagement"),
    client = useQueryClient();
  const [data, setData] = useState<O>(),
    [error, setError] = useState<string>(),
    [pending, setPending] = useState(false);
  const sequence = useRef(0),
    resource = useRef(true),
    input = useRef<string | null>(null),
    current = useRef(operation);
  current.current = operation;
  const key = useMemo(
    () => qk.knowledge.base(scope.userId, scope.workspaceId, scope.knowledgeBaseId),
    [scope.userId, scope.workspaceId, scope.knowledgeBaseId],
  );
  useEffect(
    () => () => {
      sequence.current++;
      current.current.cancel();
    },
    [],
  );
  useEffect(
    () =>
      onKnowledgeClear((prefix) => {
        if (within(key, prefix)) {
          resource.current = false;
          sequence.current++;
          current.current.cancel();
          input.current = null;
          setData(undefined);
          setError(undefined);
          setPending(false);
        }
      }),
    [key],
  );
  const cancel = () => {
    sequence.current++;
    operation.cancel();
    input.current = null;
    setData(undefined);
    setError(undefined);
    setPending(false);
  };
  const run = async (payload: I) => {
    const signature = JSON.stringify(payload);
    if (input.current === signature || !resource.current) return;
    const validIdentity = capture(),
      seq = ++sequence.current;
    const valid = () => validIdentity() && resource.current && seq === sequence.current;
    if (!valid()) return;
    operation.cancel();
    input.current = signature;
    setData(undefined);
    setError(undefined);
    setPending(true);
    try {
      // Search and Ask are read operations. Fresh membership, not owner/admin, authorizes them.
      const allowed = await scope.revalidateRead?.();
      if (!valid()) return;
      if (!allowed) {
        setError(t("errors.forbidden"));
        return;
      }
      const result = await operation.mutateAsync(payload);
      if (valid()) setData(result);
    } catch (failure) {
      if (!valid() || isAbort(failure)) return;
      setError(playgroundError(failure, t));
      if (failure instanceof ApiError && [403, 404].includes(failure.status)) {
        resource.current = false;
        input.current = null;
        setPending(false);
        if (failure.status === 403) {
          void scope.revalidate().then((allowed) => {
            if (validIdentity() && seq === sequence.current) resource.current = allowed;
          });
        } else {
          void scope.checkBase().then(() => {
            const base = client.getQueryState<{ id: string; workspace_id: string }>(key);
            if (validIdentity() && seq === sequence.current)
              resource.current = Boolean(
                base?.status === "success" &&
                base.fetchStatus === "idle" &&
                base.data?.id === scope.knowledgeBaseId &&
                base.data.workspace_id === scope.workspaceId,
              );
          });
        }
      }
    } finally {
      if (valid()) {
        input.current = null;
        setPending(false);
      }
    }
  };
  return { data, error, pending, run, cancel };
}
function KnowledgeSearchPanel(
  props: PlaygroundScope & {
    query: string;
    setQuery: (value: string) => void;
    top: string;
    setTop: (value: string) => void;
    minimum: string;
    setMinimum: (value: string) => void;
  },
) {
  const t = useTranslations("knowledgeManagement");
  const operation = useKnowledgeSearch(props.userId, props.workspaceId, props.knowledgeBaseId);
  const request = usePlaygroundRequest<KnowledgeSearchRequest, KnowledgeSearchResponse>(
    props,
    operation,
  );
  const [validation, setValidation] = useState<string>();
  const submit = () => {
    const parsed = searchParameters(props.query, props.top, props.minimum);
    if ("error" in parsed) {
      request.cancel();
      setValidation(parsed.error);
      return;
    }
    setValidation(undefined);
    void request.run(parsed.payload);
  };
  return (
    <div className="space-y-4">
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <FormField label={t("playground.query")} htmlFor="playground-query">
          <Textarea
            id="playground-query"
            value={props.query}
            onChange={(e) => props.setQuery(e.target.value)}
            aria-required="true"
          />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label={t("playground.topK")} htmlFor="playground-top">
            <Input
              id="playground-top"
              inputMode="numeric"
              value={props.top}
              onChange={(e) => props.setTop(e.target.value)}
            />
          </FormField>
          <FormField label={t("playground.minScore")} htmlFor="playground-min">
            <Input
              id="playground-min"
              inputMode="decimal"
              value={props.minimum}
              onChange={(e) => props.setMinimum(e.target.value)}
            />
          </FormField>
        </div>
        {validation && <p role="alert">{t(`playground.validation.${validation}`)}</p>}
        <div className="flex gap-2">
          <Button type="submit">{t("playground.search")}</Button>
          {request.pending && (
            <Button type="button" variant="outline" onClick={request.cancel}>
              {t("cancel")}
            </Button>
          )}
        </div>
      </form>
      {request.pending && <LoadingState label={t("playground.submitting")} />}
      {request.error && (
        <ErrorState
          title={t("playground.requestError")}
          description={request.error}
          cta={{ label: t("retry"), onClick: submit }}
        />
      )}
      {request.data ? (
        <SearchResults data={request.data} knowledgeBaseId={props.knowledgeBaseId} />
      ) : (
        !request.pending && !request.error && <p>{t("playground.initialSearch")}</p>
      )}
    </div>
  );
}
function SearchResults({
  data,
  knowledgeBaseId,
}: {
  data: KnowledgeSearchResponse;
  knowledgeBaseId: string;
}) {
  const t = useTranslations("knowledgeManagement");
  const results = data.results.filter((item) => item.knowledge_base_id === knowledgeBaseId);
  const rejected = results.length !== data.results.length;
  return (
    <section className="space-y-3" aria-label={t("playground.results")}>
      <h4 className="font-semibold">{t("playground.results")}</h4>
      <p className="break-words whitespace-pre-wrap">
        {t("playground.actualQuery")}: {data.query}
      </p>
      <p>
        {t("playground.model")}: {data.embedding_model}
      </p>
      <p>{t("playground.count", { count: results.length })}</p>
      <p>{t("playground.scoreHelp")}</p>
      {rejected && <p role="alert">{t("scopeError")}</p>}
      {!results.length && !rejected && (
        <EmptyState
          icon={Search}
          title={t("playground.empty")}
          description={t("playground.emptyHelp")}
        />
      )}
      {results.map((item, index) => (
        <article key={`${item.chunk_id}/${index}`} className="space-y-2 rounded border p-3">
          <Evidence source={item} />
          <dl>
            {[
              [t("playground.chunkIndex"), item.chunk_index],
              [t("playground.startOffset"), item.start_offset],
              [t("playground.endOffset"), item.end_offset],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <BoundedText text={item.content} />
        </article>
      ))}
    </section>
  );
}
function KnowledgeAskPanel(
  props: PlaygroundScope & { question: string; setQuestion: (value: string) => void },
) {
  const t = useTranslations("knowledgeManagement"),
    operation = useKnowledgeAsk(props.userId, props.workspaceId, props.knowledgeBaseId);
  const request = usePlaygroundRequest<KnowledgeAskRequest, KnowledgeAskResponse>(props, operation);
  const [validation, setValidation] = useState<string>();
  const submit = () => {
    const error = validatePlaygroundText(props.question);
    if (error) {
      request.cancel();
      setValidation(error);
      return;
    }
    setValidation(undefined);
    void request.run({ question: normalizePlaygroundText(props.question) });
  };
  return (
    <div className="space-y-4">
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <FormField label={t("playground.question")} htmlFor="playground-question">
          <Textarea
            id="playground-question"
            value={props.question}
            onChange={(e) => props.setQuestion(e.target.value)}
            aria-required="true"
          />
        </FormField>
        {validation && <p role="alert">{t(`playground.validation.${validation}`)}</p>}
        <div className="flex gap-2">
          <Button type="submit">{t("playground.ask")}</Button>
          {request.pending && (
            <Button type="button" variant="outline" onClick={request.cancel}>
              {t("cancel")}
            </Button>
          )}
        </div>
      </form>
      {request.pending && <LoadingState label={t("playground.submitting")} />}
      {request.error && (
        <ErrorState
          title={t("playground.requestError")}
          description={request.error}
          cta={{ label: t("retry"), onClick: submit }}
        />
      )}
      {request.data ? (
        request.data.status === "no_evidence" ? (
          <p role="status">{t("playground.noEvidence")}</p>
        ) : request.data.status === "answered" ? (
          <section className="space-y-3" aria-label={t("playground.answer")}>
            <h4>{t("playground.answer")}</h4>
            <BoundedText text={request.data.answer} />
            <h4>{t("playground.sources")}</h4>
            {request.data.sources.length ? (
              request.data.sources.map((source, index) => (
                <article key={`${source.chunk_id}/${index}`} className="rounded border p-3">
                  <Evidence source={source} />
                </article>
              ))
            ) : (
              <p>{t("playground.noSources")}</p>
            )}
          </section>
        ) : (
          <p role="alert">{t("playground.invalidResponse")}</p>
        )
      ) : (
        !request.pending && !request.error && <p>{t("playground.initialAsk")}</p>
      )}
    </div>
  );
}
function Evidence({ source }: { source: KnowledgeAgentSourceRead }) {
  const t = useTranslations("knowledgeManagement");
  return (
    <dl className="grid gap-2 sm:grid-cols-2">
      {[
        [t("playground.filename"), source.filename],
        [t("playground.documentId"), source.document_id],
        [t("playground.chunkId"), source.chunk_id],
        [t("playground.pageStart"), source.page_start ?? "—"],
        [t("playground.pageEnd"), source.page_end ?? "—"],
        [
          t("playground.score"),
          Number.isFinite(source.similarity_score) ? String(source.similarity_score) : "—",
        ],
      ].map(([label, value]) => (
        <div key={label}>
          <dt className="text-muted-foreground text-sm">{label}</dt>
          <dd className="break-all whitespace-pre-wrap">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function BoundedText({ text }: { text: string }) {
  const t = useTranslations("knowledgeManagement");
  const preview = Array.from(text.slice(0, PLAYGROUND_TEXT_LIMIT * 2))
    .slice(0, PLAYGROUND_TEXT_LIMIT)
    .join("");
  return (
    <div>
      {preview.length < text.length && (
        <p>{t("playground.truncated", { count: PLAYGROUND_TEXT_LIMIT })}</p>
      )}
      <pre className="max-h-80 overflow-auto rounded border p-3 break-words whitespace-pre-wrap">
        {preview}
      </pre>
    </div>
  );
}

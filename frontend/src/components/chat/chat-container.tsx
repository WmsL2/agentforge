"use client";

import {
  useCallback,
  useEffect,
  useRef,
} from "react";
import { useTranslations } from "next-intl";

import { QuestionPrompt } from "@/components/ui";
import {
  useChat,
  useConversations,
} from "@/hooks";
import { buildAssistantParts } from "@/lib/conversation-to-chat";
import {
  useChatStore,
  useConversationStore,
} from "@/stores";
import type {
  AskUserAnswer,
  AskUserQuestion,
  Decision,
  PendingApproval,
} from "@/types";

import { ChatControls } from "./chat-controls";
import { ChatEmptyState } from "./chat-empty-state";
import { ChatInput } from "./chat-input";
import { FilePreviewPanel } from "./file-preview-panel";
import { MessageList } from "./message-list";
import { PendingMessages } from "./pending-messages";
import { SourcesPanel } from "./sources-panel";
import { ToolApprovalDialog } from "./tool-approval-dialog";

const SCROLL_NEAR_BOTTOM_THRESHOLD_PX = 150;

export function ChatContainer() {
  const {
    currentConversationId,
    currentMessages,
    isLoading: isConversationLoading,
  } = useConversationStore();

  const {
    addMessage: addChatMessage,
  } = useChatStore();

  const {
    fetchConversations,
  } = useConversations();

  const prevConversationIdRef =
    useRef<
      string | null | undefined
    >(undefined);

  const handleConversationCreated =
    useCallback(() => {
      fetchConversations();
    }, [fetchConversations]);

  const {
    messages,
    isConnected,
    isProcessing,
    sendMessage,
    stopGeneration,
    clearMessages,
    queuedMessages,
    cancelQueued,
    clearQueued,
    setModel,
    setTemperature,
    setThinkingEffort,
    pendingApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
  } = useChat({
    conversationId:
      currentConversationId,
    onConversationCreated:
      handleConversationCreated,
  });

  const messagesEndRef =
    useRef<HTMLDivElement>(null);

  const scrollContainerRef =
    useRef<HTMLDivElement>(null);

  const userScrolledUpRef =
    useRef(false);

  useEffect(() => {
    const prevId =
      prevConversationIdRef.current;

    const currId =
      currentConversationId;

    if (prevId === undefined) {
      prevConversationIdRef.current =
        currId;

      return;
    }

    const shouldClear =
      currId === null ||
      (prevId !== null &&
        prevId !== currId);

    if (shouldClear) {
      clearMessages();
      clearQueued();
    }

    prevConversationIdRef.current =
      currId;
  }, [
    currentConversationId,
    clearMessages,
    clearQueued,
  ]);

  useEffect(() => {
    if (currentMessages.length <= 0) {
      return;
    }

    clearMessages();

    currentMessages.forEach(
      (message) => {
        const toolCalls =
          message.tool_calls?.map(
            (toolCall) => ({
              id: toolCall.tool_call_id,
              name: toolCall.tool_name,
              args: toolCall.args,
              result: toolCall.result,
              status: (
                toolCall.status === "failed"
                  ? "error"
                  : toolCall.status
              ) as
                | "pending"
                | "running"
                | "completed"
                | "error",
            }),
          );

        const parts =
          message.role === "assistant"
            ? buildAssistantParts(
                toolCalls ?? [],
                message.content,
                message.id,
                message.thinking,
              )
            : undefined;

        addChatMessage({
          id: message.id,
          role: message.role,
          content: message.content,
          thinking:
            message.thinking ??
            undefined,
          timestamp: new Date(
            message.created_at,
          ),
          conversationId:
            message.conversation_id,
          toolCalls,
          parts,
          user_rating:
            message.user_rating ??
            undefined,
          rating_count:
            message.rating_count ??
            undefined,
          files: message.files,
          fileIds:
            message.files?.map(
              (file) => file.id,
            ),
        });
      },
    );
  }, [
    currentMessages,
    addChatMessage,
    clearMessages,
  ]);

  useEffect(() => {
    const container =
      scrollContainerRef.current;

    if (!container) return;

    const handleScroll = () => {
      const distFromBottom =
        container.scrollHeight -
        container.scrollTop -
        container.clientHeight;

      userScrolledUpRef.current =
        distFromBottom >
        SCROLL_NEAR_BOTTOM_THRESHOLD_PX;
    };

    container.addEventListener(
      "scroll",
      handleScroll,
      {
        passive: true,
      },
    );

    return () =>
      container.removeEventListener(
        "scroll",
        handleScroll,
      );
  }, []);

  useEffect(() => {
    if (userScrolledUpRef.current) {
      return;
    }

    messagesEndRef.current?.scrollIntoView(
      {
        behavior: "smooth",
      },
    );
  }, [messages]);

  const handleRegenerate =
    useCallback(
      (
        assistantMessageId: string,
      ) => {
        const index =
          messages.findIndex(
            (message) =>
              message.id ===
              assistantMessageId,
          );

        if (index < 0) return;

        for (
          let i = index - 1;
          i >= 0;
          i--
        ) {
          const message =
            messages[i];

          if (
            message?.role === "user"
          ) {
            sendMessage(
              message.content,
              message.fileIds,
              message.files,
            );

            return;
          }
        }
      },
      [messages, sendMessage],
    );

  const slashContext = {
    clearChat: clearMessages,

    regenerateLast: () => {
      for (
        let i =
          messages.length - 1;
        i >= 0;
        i--
      ) {
        const message =
          messages[i];

        if (
          message?.role ===
          "assistant"
        ) {
          handleRegenerate(
            message.id,
          );

          return;
        }
      }
    },

    openSettings: () => {
      document
        .querySelector<HTMLButtonElement>(
          "[data-chat-settings-trigger]",
        )
        ?.click();
    },
  };

  return (
    <ChatUI
      messages={messages}
      isConnected={isConnected}
      isProcessing={isProcessing}
      isLoadingConversation={
        currentConversationId !==
          null &&
        isConversationLoading &&
        messages.length === 0
      }
      sendMessage={sendMessage}
      onModelChange={setModel}
      onTemperatureChange={
        setTemperature
      }
      onThinkingEffortChange={
        setThinkingEffort
      }
      onRegenerate={
        handleRegenerate
      }
      slashContext={
        slashContext
      }
      queuedMessages={
        queuedMessages
      }
      onCancelQueued={
        cancelQueued
      }
      messagesEndRef={
        messagesEndRef
      }
      scrollContainerRef={
        scrollContainerRef
      }
      pendingApproval={
        pendingApproval
      }
      onResumeDecisions={
        sendResumeDecisions
      }
      pendingQuestions={
        pendingQuestions
      }
      onAnswerQuestions={
        sendAskUserResponses
      }
      onStop={stopGeneration}
    />
  );
}

interface ChatUIProps {
  messages: import("@/types").ChatMessage[];
  isConnected: boolean;
  isProcessing: boolean;
  isLoadingConversation?: boolean;
  sendMessage: (
    content: string,
    fileIds?: string[],
    files?: import("@/types").ChatMessageFile[],
  ) => void;
  onModelChange?: (
    model: string | null,
  ) => void;
  onTemperatureChange?: (
    temperature: number | null,
  ) => void;
  onThinkingEffortChange?: (
    effort:
      | "low"
      | "medium"
      | "high"
      | null,
  ) => void;
  onRegenerate?: (
    messageId: string,
  ) => void;
  slashContext?: import("./slash-commands").SlashCommandContext;
  queuedMessages?: import("@/hooks/use-chat").QueuedMessage[];
  onCancelQueued?: (
    id: string,
  ) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  pendingApproval?: PendingApproval | null;
  onResumeDecisions?: (
    decisions: Decision[],
  ) => void;
  pendingQuestions?:
    | AskUserQuestion[]
    | null;
  onAnswerQuestions?: (
    answers: AskUserAnswer[],
  ) => void;
  onStop?: () => void;
}

function ChatUI({
  messages,
  isConnected,
  isProcessing,
  isLoadingConversation,
  sendMessage,
  onModelChange,
  onTemperatureChange,
  onThinkingEffortChange,
  onRegenerate,
  slashContext,
  queuedMessages,
  onCancelQueued,
  messagesEndRef,
  scrollContainerRef,
  pendingApproval,
  onResumeDecisions,
  pendingQuestions,
  onAnswerQuestions,
  onStop,
}: ChatUIProps) {
  const tc =
    useTranslations("common");

  return (
    <div className="flex h-full w-full">
      <div className="mx-auto flex h-full max-w-5xl min-w-0 flex-1 flex-col">
        <div
          ref={scrollContainerRef}
          className="flex-1 scrollbar-thin overflow-y-auto px-2 py-4 sm:px-4 sm:py-6"
        >
          {isLoadingConversation ? (
            <ConversationSkeleton />
          ) : messages.length ===
            0 ? (
            <div className="flex h-full items-center">
              <ChatEmptyState
                onPick={(prompt) =>
                  sendMessage(prompt)
                }
              />
            </div>
          ) : (
            <MessageList
              messages={messages}
              onRegenerate={
                onRegenerate
              }
            />
          )}

          <div
            ref={messagesEndRef}
          />
        </div>

        {pendingApproval &&
          onResumeDecisions && (
            <div className="px-2 pb-2 sm:px-4 sm:pb-2">
              <ToolApprovalDialog
                actionRequests={
                  pendingApproval.actionRequests
                }
                reviewConfigs={
                  pendingApproval.reviewConfigs
                }
                onDecisions={
                  onResumeDecisions
                }
                disabled={
                  !isConnected
                }
              />
            </div>
          )}

        {pendingQuestions &&
          pendingQuestions.length >
            0 &&
          onAnswerQuestions && (
            <div className="px-2 pb-2 sm:px-4 sm:pb-2">
              <QuestionPrompt
                questions={
                  pendingQuestions
                }
                disabled={
                  !isConnected
                }
                onComplete={
                  onAnswerQuestions
                }
              />
            </div>
          )}

        <div className="px-2 pb-2 sm:px-4 sm:pb-4">
          {queuedMessages &&
            queuedMessages.length >
              0 &&
            onCancelQueued && (
              <PendingMessages
                messages={
                  queuedMessages
                }
                onCancel={
                  onCancelQueued
                }
              />
            )}

          <div className="bg-card border-border focus-within:border-foreground/30 rounded-2xl border transition-colors">
            <div className="px-3 pt-3 sm:px-4 sm:pt-4">
              <ChatInput
                onSend={sendMessage}
                disabled={
                  !isConnected ||
                  !!pendingApproval ||
                  !!(
                    pendingQuestions &&
                    pendingQuestions.length
                  )
                }
                isProcessing={
                  isProcessing
                }
                onStop={onStop}
                slashContext={
                  slashContext
                }
              />
            </div>

            <div className="border-foreground/8 flex items-center justify-between border-t px-3 py-2 sm:px-4">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 font-mono text-[10px] tracking-wider uppercase ${
                    isConnected
                      ? "text-muted-foreground"
                      : "text-destructive"
                  }`}
                >
                  <span
                    className={`inline-block h-1.5 w-1.5 rounded-full ${
                      isConnected
                        ? "bg-emerald-500"
                        : "bg-destructive"
                    }`}
                  />

                  {isConnected
                    ? tc("live")
                    : tc("offline")}
                </span>
              </div>

              <div className="flex items-center gap-1">
                <ChatControls
                  onModelChange={
                    onModelChange
                  }
                  onTemperatureChange={
                    onTemperatureChange
                  }
                  onThinkingEffortChange={
                    onThinkingEffortChange
                  }
                />
              </div>
            </div>
          </div>

          <p className="text-foreground/40 mt-2 text-center font-mono text-[10px] tracking-wider uppercase">
            AI can make mistakes. Verify
            important information.
          </p>
        </div>
      </div>

      <FilePreviewPanel />
      <SourcesPanel />
    </div>
  );
}

function ConversationSkeleton() {
  return (
    <div className="space-y-6 py-4 sm:py-6">
      <div className="flex gap-2 sm:gap-4">
        <div className="bg-foreground/10 h-8 w-8 shrink-0 animate-pulse rounded-full sm:h-9 sm:w-9" />

        <div className="flex max-w-[85%] flex-1 flex-col gap-2">
          <div className="bg-foreground/10 h-4 w-1/3 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-4/5 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-2/3 animate-pulse rounded-md" />
        </div>
      </div>

      <div className="flex flex-row-reverse gap-2 sm:gap-4">
        <div className="bg-foreground/10 h-8 w-8 shrink-0 animate-pulse rounded-full sm:h-9 sm:w-9" />

        <div className="flex max-w-[85%] flex-1 flex-col items-end gap-2">
          <div className="bg-foreground/10 h-4 w-1/4 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-3/5 animate-pulse rounded-md" />
        </div>
      </div>

      <div className="flex gap-2 sm:gap-4">
        <div className="bg-foreground/10 h-8 w-8 shrink-0 animate-pulse rounded-full sm:h-9 sm:w-9" />

        <div className="flex max-w-[85%] flex-1 flex-col gap-2">
          <div className="bg-foreground/8 h-4 w-3/4 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-1/2 animate-pulse rounded-md" />
        </div>
      </div>
    </div>
  );
}
"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Image from "next/image";
import {
  FileText,
  Mic,
  MicOff,
  Paperclip,
  Send,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  Badge,
  Button,
  Spinner,
} from "@/components/ui";
import {
  getFileUrl,
  type FileUploadResponse,
  uploadFile,
} from "@/lib/file-api";
import {
  getErrorMessage,
  MAX_UPLOAD_SIZE_MB,
} from "@/lib/utils";

interface ChatInputProps {
  onSend: (
    message: string,
    fileIds?: string[],
    files?: FileUploadResponse[],
  ) => void;
  disabled?: boolean;
  isProcessing?: boolean;
  onStop?: () => void;
}

export function ChatInput({
  onSend,
  disabled,
  isProcessing,
  onStop,
}: ChatInputProps) {
  const [
    message,
    setMessage,
  ] = useState("");

  const [
    attachedFiles,
    setAttachedFiles,
  ] =
    useState<
      FileUploadResponse[]
    >([]);

  const [
    isUploading,
    setIsUploading,
  ] = useState(false);

  const [
    isListening,
    setIsListening,
  ] = useState(false);

  const [
    isDragging,
    setIsDragging,
  ] = useState(false);

  const textareaRef =
    useRef<HTMLTextAreaElement>(
      null,
    );

  const fileInputRef =
    useRef<HTMLInputElement>(
      null,
    );

  const recognitionRef =
    useRef<SpeechRecognition | null>(
      null,
    );

  const dragDepth = useRef(0);

  useEffect(() => {
    if (
      !isProcessing &&
      !isUploading &&
      textareaRef.current
    ) {
      textareaRef.current.focus();
    }
  }, [
    isProcessing,
    isUploading,
  ]);

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }

    textareaRef.current.style.height =
      "auto";

    textareaRef.current.style.height =
      `${Math.min(
        textareaRef.current.scrollHeight,
        200,
      )}px`;
  }, [message]);

  const handleSubmit = (
    event: React.FormEvent,
  ) => {
    event.preventDefault();

    const trimmed =
      message.trim();

    if (
      !trimmed &&
      attachedFiles.length === 0
    ) {
      return;
    }

    if (
      disabled ||
      isUploading
    ) {
      return;
    }

    const fileIds =
      attachedFiles.length > 0
        ? attachedFiles.map(
            (file) => file.id,
          )
        : undefined;

    const files =
      attachedFiles.length > 0
        ? attachedFiles
        : undefined;

    onSend(
      trimmed ||
        "Analyze the attached file(s)",
      fileIds,
      files,
    );

    setMessage("");
    setAttachedFiles([]);
  };

  const handleKeyDown = (
    event: React.KeyboardEvent,
  ) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey
    ) {
      event.preventDefault();
      handleSubmit(event);
    }
  };

  const toggleMic =
    useCallback(() => {
      if (isListening) {
        recognitionRef.current?.stop();
        setIsListening(false);
        return;
      }

      const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

      if (!SpeechRecognition) {
        toast.info(
          "Voice input is only supported in Chrome. Use Chrome for speech-to-text.",
        );

        return;
      }

      const recognition =
        new SpeechRecognition();

      recognition.continuous = true;
      recognition.interimResults =
        true;

      recognition.lang =
        navigator.language ||
        "en-US";

      let finalTranscript = "";

      recognition.onresult = (
        event: SpeechRecognitionEvent,
      ) => {
        let interim = "";

        for (
          let i =
            event.resultIndex;
          i <
          event.results.length;
          i++
        ) {
          const result =
            event.results[i];

          if (!result) {
            continue;
          }

          if (result.isFinal) {
            finalTranscript +=
              result[0]
                ?.transcript ?? "";
          } else {
            interim +=
              result[0]
                ?.transcript ?? "";
          }
        }

        setMessage(
          () =>
            finalTranscript +
            (interim
              ? `\u200B${interim}`
              : ""),
        );
      };

      recognition.onend = () => {
        setIsListening(false);

        setMessage((previous) =>
          previous.replace(
            /\u200B/g,
            "",
          ),
        );
      };

      recognition.onerror = () => {
        setIsListening(false);

        toast.error(
          "Speech recognition error",
        );
      };

      recognitionRef.current =
        recognition;

      recognition.start();

      setIsListening(true);

      finalTranscript = message;
    }, [
      isListening,
      message,
    ]);

  const uploadFiles =
    useCallback(
      async (files: File[]) => {
        if (
          files.length === 0
        ) {
          return;
        }

        for (const file of files) {
          if (
            file.size >
            MAX_UPLOAD_SIZE_MB *
              1024 *
              1024
          ) {
            toast.error(
              `${file.name}: File too large. Maximum ${MAX_UPLOAD_SIZE_MB}MB.`,
            );

            continue;
          }

          setIsUploading(true);

          try {
            const result =
              await uploadFile(file);

            setAttachedFiles(
              (previous) => [
                ...previous,
                result,
              ],
            );
          } catch (error) {
            toast.error(
              `${file.name}: ${getErrorMessage(
                error,
                "Upload failed",
              )}`,
            );
          } finally {
            setIsUploading(false);
          }
        }
      },
      [],
    );

  const handleFileSelect =
    useCallback(
      async (
        event: React.ChangeEvent<HTMLInputElement>,
      ) => {
        const files =
          event.target.files;

        if (
          !files ||
          files.length === 0
        ) {
          return;
        }

        event.target.value = "";

        await uploadFiles(
          Array.from(files),
        );
      },
      [uploadFiles],
    );

  const isFileDrag = (
    event: React.DragEvent,
  ) =>
    Array.from(
      event.dataTransfer.types,
    ).includes("Files");

  const handleDragEnter = (
    event: React.DragEvent,
  ) => {
    if (!isFileDrag(event)) {
      return;
    }

    event.preventDefault();

    dragDepth.current += 1;

    setIsDragging(true);
  };

  const handleDragOver = (
    event: React.DragEvent,
  ) => {
    if (isFileDrag(event)) {
      event.preventDefault();
    }
  };

  const handleDragLeave = (
    event: React.DragEvent,
  ) => {
    if (!isFileDrag(event)) {
      return;
    }

    dragDepth.current -= 1;

    if (
      dragDepth.current <= 0
    ) {
      dragDepth.current = 0;
      setIsDragging(false);
    }
  };

  const handleDrop = (
    event: React.DragEvent,
  ) => {
    if (!isFileDrag(event)) {
      return;
    }

    event.preventDefault();

    dragDepth.current = 0;

    setIsDragging(false);

    const files =
      Array.from(
        event.dataTransfer.files,
      );

    if (files.length) {
      void uploadFiles(files);
    }
  };

  const removeFile = (
    fileId: string,
  ) => {
    setAttachedFiles(
      (previous) =>
        previous.filter(
          (file) =>
            file.id !== fileId,
        ),
    );
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="relative"
      onDragEnter={
        handleDragEnter
      }
      onDragOver={
        handleDragOver
      }
      onDragLeave={
        handleDragLeave
      }
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="border-foreground/40 bg-card/95 text-foreground absolute inset-0 z-30 flex items-center justify-center rounded-2xl border-2 border-dashed text-sm font-medium backdrop-blur-sm">
          <span className="flex items-center gap-2">
            <Upload className="h-4 w-4" />
            Drop files to attach
          </span>
        </div>
      )}

      {attachedFiles.length >
        0 && (
        <div className="flex flex-wrap items-center gap-2 pb-2">
          {attachedFiles.map(
            (file) => (
              <div
                key={file.id}
                className="relative"
              >
                {file.file_type ===
                "image" ? (
                  <div className="group relative h-16 w-16 overflow-hidden rounded-lg border">
                    <Image
                      src={getFileUrl(
                        file.id,
                      )}
                      alt={
                        file.filename
                      }
                      fill
                      className="object-cover"
                      unoptimized
                    />

                    <button
                      type="button"
                      onClick={() =>
                        removeFile(
                          file.id,
                        )
                      }
                      className="bg-destructive text-destructive-foreground absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full opacity-0 transition-opacity group-hover:opacity-100"
                      aria-label={`Remove ${file.filename}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ) : (
                  <Badge
                    variant="secondary"
                    className="gap-1.5 pr-1"
                  >
                    <FileText className="h-3 w-3" />

                    <span className="max-w-[150px] truncate text-xs">
                      {
                        file.filename
                      }
                    </span>

                    <button
                      type="button"
                      onClick={() =>
                        removeFile(
                          file.id,
                        )
                      }
                      className="hover:bg-muted ml-0.5 rounded p-0.5"
                      aria-label={`Remove ${file.filename}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                )}
              </div>
            ),
          )}

          {isUploading && (
            <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed">
              <Spinner className="text-muted-foreground h-5 w-5" />
            </div>
          )}
        </div>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(event) =>
            setMessage(
              event.target.value,
            )
          }
          onKeyDown={
            handleKeyDown
          }
          placeholder="Type a message..."
          disabled={disabled}
          rows={1}
          className="placeholder:text-muted-foreground min-h-[40px] flex-1 resize-none scrollbar-thin bg-transparent py-2.5 text-sm focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 sm:text-base"
        />

        <div className="flex shrink-0 items-center gap-0.5 pb-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={toggleMic}
            disabled={disabled}
            className="h-9 w-9"
            title={
              isListening
                ? "Stop recording"
                : "Voice input"
            }
            aria-label={
              isListening
                ? "Stop recording"
                : "Voice input"
            }
          >
            {isListening ? (
              <MicOff className="h-4 w-4 animate-pulse text-red-500" />
            ) : (
              <Mic className="text-muted-foreground h-4 w-4" />
            )}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() =>
              fileInputRef.current?.click()
            }
            disabled={
              disabled ||
              isUploading
            }
            className="h-9 w-9"
            title="Attach file"
            aria-label="Attach file"
          >
            {isUploading ? (
              <Spinner className="text-muted-foreground h-4 w-4" />
            ) : (
              <Paperclip className="text-muted-foreground h-4 w-4" />
            )}
          </Button>

          <input
            ref={fileInputRef}
            type="file"
            onChange={
              handleFileSelect
            }
            accept="image/jpeg,image/png,image/gif,image/webp,.txt,.md,.csv,.json,.py,.js,.ts,.tsx,.html,.css,.yaml,.yml,.toml,.xml,.sql,.sh,.pdf,.docx"
            multiple
            className="hidden"
          />

          {isProcessing &&
          onStop ? (
            <Button
              type="button"
              size="icon"
              onClick={onStop}
              className="h-9 w-9 rounded-lg"
              title="Stop generating"
            >
              <span
                className="h-3 w-3 rounded-[3px] bg-current"
                aria-hidden="true"
              />

              <span className="sr-only">
                Stop generating
              </span>
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={
                disabled ||
                isUploading ||
                (!message.trim() &&
                  attachedFiles.length ===
                    0)
              }
              className="h-9 w-9 rounded-lg"
            >
              {isProcessing ? (
                <Spinner className="h-4 w-4" />
              ) : (
                <Send className="h-4 w-4" />
              )}

              <span className="sr-only">
                Send message
              </span>
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
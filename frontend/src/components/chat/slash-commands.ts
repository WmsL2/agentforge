/**
 * Built-in chat command registry.
 *
 * These commands are defined locally in the frontend and do not
 * require user-specific persistence or backend configuration.
 */

export type SlashCommandAction =
  | {
      kind: "client";
      run: (
        ctx: SlashCommandContext,
      ) => void;
    }
  | {
      kind: "send-as-message";
      replaceWith: string;
    };

export interface SlashCommand {
  name: string;
  description: string;
  aliases?: string[];
  action: SlashCommandAction;
}

export interface SlashCommandContext {
  clearChat: () => void;

  regenerateLast: () => void;

  openSettings: () => void;
}

export const BUILTIN_COMMANDS: SlashCommand[] =
  [
    {
      name: "clear",
      description:
        "Clear the current chat (does not delete the conversation).",
      aliases: ["reset"],
      action: {
        kind: "client",
        run: (ctx) =>
          ctx.clearChat(),
      },
    },
    {
      name: "regen",
      description:
        "Regenerate the last assistant response.",
      aliases: [
        "regenerate",
        "retry",
      ],
      action: {
        kind: "client",
        run: (ctx) =>
          ctx.regenerateLast(),
      },
    },
    {
      name: "settings",
      description:
        "Open chat settings (model, temperature, thinking).",
      action: {
        kind: "client",
        run: (ctx) =>
          ctx.openSettings(),
      },
    },
    {
      name: "summarize",
      description:
        "Ask the agent to summarize the conversation so far.",
      action: {
        kind: "send-as-message",
        replaceWith:
          "Please give me a concise summary of our conversation so far — key topics, decisions, and any open questions.",
      },
    },
    {
      name: "explain",
      description:
        "Ask the agent to explain its last response in simpler terms.",
      action: {
        kind: "send-as-message",
        replaceWith:
          "Explain your last response again, in simpler terms — assume I don't have technical background.",
      },
    },
  ];

export function searchCommands(
  commands: SlashCommand[],
  query: string,
): SlashCommand[] {
  const normalizedQuery =
    query
      .toLowerCase()
      .replace(/^\/+/, "");

  if (!normalizedQuery) {
    return commands;
  }

  const prefixMatches =
    commands.filter((command) =>
      [
        command.name,
        ...(command.aliases ?? []),
      ].some((candidate) =>
        candidate.startsWith(
          normalizedQuery,
        ),
      ),
    );

  if (prefixMatches.length > 0) {
    return prefixMatches;
  }

  return commands.filter(
    (command) =>
      command.name.includes(
        normalizedQuery,
      ) ||
      command.aliases?.some(
        (alias) =>
          alias.includes(
            normalizedQuery,
          ),
      ) ||
      command.description
        .toLowerCase()
        .includes(
          normalizedQuery,
        ),
  );
}
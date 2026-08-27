"use client";

import {
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Command } from "cmdk";
import {
  Activity,
  ArrowRight,
  Bell,
  BookOpen,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Palette,
  Plus,
  Search,
  Settings,
  Shield,
  Star,
  UserCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import {
  BACKEND_URL,
  ROUTES,
} from "@/lib/constants";
import { isAppAdmin } from "@/lib/utils";

interface ConversationItem {
  id: string;
  title: string | null;
  updated_at?: string | null;
}

const API_DOCS_URL = `${BACKEND_URL.replace(/\/$/, "")}/docs`;

export function CommandPalette() {
  const router = useRouter();
  const t = useTranslations("nav");

  const {
    user,
    logout,
  } = useAuth();

  const inputRef =
    useRef<HTMLInputElement>(null);

  const [open, setOpen] =
    useState(false);

  const [search, setSearch] =
    useState("");

  const [conversations, setConversations] =
    useState<ConversationItem[]>([]);

  useEffect(() => {
    const handler = (
      event: KeyboardEvent,
    ) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "k"
      ) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };

    const openHandler = () => {
      setOpen(true);
    };

    document.addEventListener(
      "keydown",
      handler,
    );

    window.addEventListener(
      "command-palette:open",
      openHandler,
    );

    return () => {
      document.removeEventListener(
        "keydown",
        handler,
      );

      window.removeEventListener(
        "command-palette:open",
        openHandler,
      );
    };
  }, []);

  useEffect(() => {
    if (!open) return;

    const frame =
      window.requestAnimationFrame(() => {
        inputRef.current?.focus();
      });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (conversations.length > 0) return;

    apiClient
      .get<{
        items: ConversationItem[];
      }>("/conversations?limit=10")
      .then((data) =>
        setConversations(data.items),
      )
      .catch(() =>
        setConversations([]),
      );
  }, [
    open,
    conversations.length,
  ]);

  const go = (href: string) => {
    setOpen(false);
    setSearch("");
    router.push(href);
  };

  const openApiDocs = () => {
    setOpen(false);
    setSearch("");

    window.open(
      API_DOCS_URL,
      "_blank",
      "noopener,noreferrer",
    );
  };

  const handleOpenChange = (
    nextOpen: boolean,
  ) => {
    setOpen(nextOpen);

    if (!nextOpen) {
      setSearch("");
    }
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={handleOpenChange}
      label="Command palette"
      shouldFilter
      overlayClassName="bg-background/50 fixed inset-0 z-[60] backdrop-blur-sm"
      contentClassName="border-foreground/15 bg-card text-foreground fixed left-1/2 top-[12vh] z-[61] w-[min(92vw,640px)] -translate-x-1/2 overflow-hidden rounded-2xl border shadow-2xl"
    >
      <div className="border-foreground/10 flex items-center gap-3 border-b px-4 py-3">
        <Search className="text-foreground/45 h-4 w-4" />

        <Command.Input
          ref={inputRef}
          value={search}
          onValueChange={setSearch}
          placeholder="Search or jump to…"
          className="text-foreground placeholder:text-foreground/45 flex-1 bg-transparent text-sm outline-none"
        />

        <kbd className="border-foreground/15 text-foreground/55 hidden rounded-md border px-1.5 py-0.5 font-mono text-[10px] sm:inline-block">
          ESC
        </kbd>
      </div>

      <Command.List className="max-h-[60vh] overflow-y-auto px-2 py-2">
        <Command.Empty className="text-foreground/55 px-4 py-10 text-center text-sm">
          No matches.
        </Command.Empty>

        <Group heading="Quick actions">
          <PaletteItem
            icon={Plus}
            label="Start new chat"
            onSelect={() =>
              go(ROUTES.CHAT)
            }
          />
        </Group>

        {conversations.length > 0 && (
          <Group heading="Recent conversations">
            {conversations
              .slice(0, 8)
              .map((conversation) => (
                <PaletteItem
                  key={conversation.id}
                  icon={MessageSquare}
                  label={
                    conversation.title?.trim() ||
                    "Untitled conversation"
                  }
                  onSelect={() =>
                    go(
                      `${ROUTES.CHAT}?id=${conversation.id}`,
                    )
                  }
                />
              ))}
          </Group>
        )}

        <Group heading={t("navigate")}>
          <PaletteItem
            icon={LayoutDashboard}
            label={t("dashboard")}
            onSelect={() =>
              go(ROUTES.DASHBOARD)
            }
          />

          <PaletteItem
            icon={MessageSquare}
            label={t("chat")}
            onSelect={() =>
              go(ROUTES.CHAT)
            }
          />

          <PaletteItem
            icon={UserCircle}
            label={t("profile")}
            onSelect={() =>
              go(ROUTES.PROFILE)
            }
          />

          <PaletteItem
            icon={Settings}
            label={t("settings")}
            onSelect={() =>
              go(ROUTES.SETTINGS)
            }
          />

          <PaletteItem
            icon={BookOpen}
            label={t("apiDocs")}
            onSelect={openApiDocs}
          />
        </Group>

        <Group
          heading={t("settingsSection")}
        >
          <PaletteItem
            icon={UserCircle}
            label={t("profile")}
            onSelect={() =>
              go(
                ROUTES.SETTINGS_PROFILE,
              )
            }
          />

          <PaletteItem
            icon={Shield}
            label={t("account")}
            onSelect={() =>
              go(
                ROUTES.SETTINGS_ACCOUNT,
              )
            }
          />

          <PaletteItem
            icon={Palette}
            label={t("appearance")}
            onSelect={() =>
              go(
                ROUTES.SETTINGS_APPEARANCE,
              )
            }
          />

          <PaletteItem
            icon={Bell}
            label={t("notifications")}
            onSelect={() =>
              go(
                ROUTES.SETTINGS_NOTIFICATIONS,
              )
            }
          />
        </Group>

        {isAppAdmin(user) && (
          <Group heading={t("admin")}>
            <PaletteItem
              icon={Star}
              label={t(
                "responseRatings",
              )}
              onSelect={() =>
                go(
                  ROUTES.ADMIN_RATINGS,
                )
              }
            />

            <PaletteItem
              icon={Activity}
              label={t(
                "allConversations",
              )}
              onSelect={() =>
                go(
                  ROUTES.ADMIN_CONVERSATIONS,
                )
              }
            />
          </Group>
        )}

        <Group heading={t("account")}>
          <PaletteItem
            icon={LogOut}
            label={t("logout")}
            onSelect={() => {
              setOpen(false);
              setSearch("");
              logout();
            }}
          />
        </Group>
      </Command.List>

      <div className="border-foreground/10 text-foreground/45 flex items-center justify-between border-t px-4 py-2 font-mono text-[10px] tracking-wider uppercase">
        <span className="inline-flex items-center gap-1.5">
          <kbd className="border-foreground/15 rounded border px-1 py-0.5">
            ↑↓
          </kbd>

          Navigate
        </span>

        <span className="inline-flex items-center gap-1.5">
          <kbd className="border-foreground/15 rounded border px-1 py-0.5">
            ↵
          </kbd>

          Open
        </span>
      </div>
    </Command.Dialog>
  );
}

function Group({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:text-foreground/45 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:uppercase"
    >
      {children}
    </Command.Group>
  );
}

function PaletteItem({
  icon: Icon,
  label,
  onSelect,
  shortcut,
}: {
  icon: LucideIcon;
  label: string;
  onSelect: () => void;
  shortcut?: string;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="text-foreground/85 hover:bg-foreground/5 data-[selected=true]:bg-foreground/8 data-[selected=true]:text-foreground flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors"
    >
      <Icon className="h-4 w-4 shrink-0 opacity-70" />

      <span className="flex-1 truncate">
        {label}
      </span>

      {shortcut ? (
        <kbd className="border-foreground/15 text-foreground/55 rounded border px-1.5 py-0.5 font-mono text-[10px]">
          {shortcut}
        </kbd>
      ) : (
        <ArrowRight className="text-foreground/30 h-3.5 w-3.5 opacity-0 transition-opacity data-[selected=true]:opacity-100" />
      )}
    </Command.Item>
  );
}
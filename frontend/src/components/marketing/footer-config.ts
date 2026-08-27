import { BACKEND_URL, ROUTES } from "@/lib/constants";

/**
 * Public navigation configuration for the current AgentForge foundation.
 *
 * Only verified AgentForge surfaces are exposed here. Starter-template
 * marketing destinations such as pricing, blog, community, contact, and
 * security are intentionally excluded.
 */
type T = (key: string) => string;

export interface FooterColumn {
  title: string;
  links: {
    label: string;
    href: string;
  }[];
}

/**
 * Icon keys supported by PillNav mega-menu items.
 *
 * The current public navigation uses plain links, but the complete type is
 * retained because PillNav still provides reusable dropdown support.
 */
export type NavIcon =
  | "sparkles"
  | "workflow"
  | "insights"
  | "changelog"
  | "support"
  | "sales"
  | "knowledge"
  | "research"
  | "help"
  | "api"
  | "security"
  | "community"
  | "blog";

export interface NavMenuItem {
  label: string;
  href: string;
  description?: string;
  icon?: NavIcon;
}

export interface NavItem {
  label: string;
  href?: string;
  items?: NavMenuItem[];
  featured?: {
    label: string;
    href: string;
  };
}

/**
 * Minimal public navigation for AgentForge v0.1.
 *
 * The landing page is the canonical product surface. API documentation remains
 * available because the FastAPI backend is part of the validated foundation.
 */
export function buildMarketingNav(t: T): NavItem[] {
  return [
    {
      label: t("nav.platform"),
      href: ROUTES.HOME,
    },
    {
      label: t("footer.apiDocs"),
      href: `${BACKEND_URL}/docs`,
    },
  ];
}

/**
 * Footer links intentionally mirror only currently supported public surfaces.
 */
export function buildFooterColumns(t: T): FooterColumn[] {
  return [
    {
      title: t("footer.product"),
      links: [
        {
          label: t("nav.platform"),
          href: ROUTES.HOME,
        },
      ],
    },
    {
      title: t("footer.resources"),
      links: [
        {
          label: t("footer.apiDocs"),
          href: `${BACKEND_URL}/docs`,
        },
      ],
    },
  ];
}

/**
 * Legal documents remain canonical public AgentForge pages.
 */
export function buildFooterLegal(t: T) {
  return [
    {
      label: t("footer.terms"),
      href: ROUTES.LEGAL_TERMS,
    },
    {
      label: t("footer.privacy"),
      href: ROUTES.LEGAL_PRIVACY,
    },
    {
      label: t("footer.cookies"),
      href: ROUTES.LEGAL_COOKIES,
    },
  ];
}
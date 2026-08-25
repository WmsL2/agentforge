import { redirect } from "next/navigation";

const AGENTFORGE_REPOSITORY = "https://github.com/WmsL2/agentforge";

/**
 * Transitional compatibility route.
 *
 * The original template exposed a marketing contact/sales form at this path.
 * AgentForge does not provide that SaaS sales-contact workflow.
 *
 * Existing template links still reference `/contact`, so keep this route
 * temporarily and redirect visitors to the project repository. The route can
 * be removed once the remaining marketing pages and navigation are rewritten
 * during the v0.1 template takeover.
 */
export default function ContactPage() {
  redirect(AGENTFORGE_REPOSITORY);
}
import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/analytics")({
  head: () => ({ meta: [{ title: "CashPilot AI | Analytics & Negotiation" }] }),
  component: () => <ScreenFrame src="/screens/analytics.html" title="Analytics" />,
});

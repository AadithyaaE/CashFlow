import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/dashboard")({
  head: () => ({ meta: [{ title: "CashPilot AI | Dashboard" }] }),
  component: () => <ScreenFrame src="/screens/dashboard.html" title="Dashboard" />,
});

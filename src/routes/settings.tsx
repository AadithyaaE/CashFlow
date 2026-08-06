import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/settings")({
  head: () => ({ meta: [{ title: "CashPilot AI | Settings" }] }),
  component: () => <ScreenFrame src="/screens/settings.html" title="Settings" />,
});

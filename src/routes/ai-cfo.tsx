import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/ai-cfo")({
  head: () => ({ meta: [{ title: "CashPilot AI | AI CFO" }] }),
  component: () => <ScreenFrame src="/screens/ai-cfo.html" title="AI CFO" />,
});

import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/runway")({
  head: () => ({ meta: [{ title: "CashPilot AI | Cash Runway & Scenario Simulator" }] }),
  component: () => <ScreenFrame src="/screens/runway.html" title="Runway" />,
});

import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/invoices")({
  head: () => ({ meta: [{ title: "CashPilot AI | Invoice Intelligence" }] }),
  component: () => <ScreenFrame src="/screens/invoices.html" title="Invoices" />,
});

import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "CashPilot AI | Your AI CFO for Smarter Cash Flow" },
      { name: "description", content: "Upload invoices, receipts, and bank statements. Let AI predict cash shortages and recommend the best next action." },
    ],
  }),
  component: () => <ScreenFrame src="/screens/index.html" title="Landing" />,
});

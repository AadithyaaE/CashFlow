import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "CashPilot AI | Log In" },
      { name: "description", content: "Sign in to your CashPilot AI account." },
    ],
  }),
  component: () => <ScreenFrame src="/screens/login.html" title="Log In" />,
});

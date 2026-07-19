import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/forgot-password")({
  head: () => ({
    meta: [{ title: "CashPilot AI | Forgot Password" }],
  }),
  component: () => <ScreenFrame src="/screens/forgot-password.html" title="Forgot Password" />,
});

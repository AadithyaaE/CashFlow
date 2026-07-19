import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/reset-password")({
  head: () => ({
    meta: [{ title: "CashPilot AI | Reset Password" }],
  }),
  component: () => <ScreenFrame src="/screens/reset-password.html" title="Reset Password" />,
});

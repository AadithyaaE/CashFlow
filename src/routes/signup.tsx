import { createFileRoute } from "@tanstack/react-router";
import ScreenFrame from "@/components/ScreenFrame";

export const Route = createFileRoute("/signup")({
  head: () => ({
    meta: [
      { title: "CashPilot AI | Sign Up" },
      { name: "description", content: "Create your CashPilot AI account." },
    ],
  }),
  component: () => <ScreenFrame src="/screens/signup.html" title="Sign Up" />,
});

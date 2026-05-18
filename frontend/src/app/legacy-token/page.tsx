"use client";

import { useRouter } from "next/navigation";
import { TokenGate } from "@/components/TokenGate";

export default function LegacyTokenPage() {
  const router = useRouter();
  return <TokenGate onConfigured={() => router.replace("/")} />;
}

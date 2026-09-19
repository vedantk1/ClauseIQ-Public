import React from "react";
import { AppHeader } from "@/components/shell/AppHeader";

export function LibraryHeader({ onNavigate, current = "library" }: {
  onNavigate?: (destination: string) => void;
  current?: "library" | "import";
} = {}) {
  return <AppHeader current={current === "library" ? "library" : undefined}
    onNavigate={onNavigate} navigationLabel="Library navigation" />;
}

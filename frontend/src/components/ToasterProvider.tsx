"use client";

import { Toaster } from "react-hot-toast";

export default function ToasterProvider() {
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: "var(--bg-surface)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-muted)",
        },
        success: {
          iconTheme: {
            primary: "var(--accent-green)",
            secondary: "var(--bg-surface)",
          },
        },
        error: {
          iconTheme: {
            primary: "var(--accent-rose)",
            secondary: "var(--bg-surface)",
          },
        },
      }}
    />
  );
}

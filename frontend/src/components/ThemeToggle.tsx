/**
 * Switch between the two dark appearance choices.
 */
"use client";

import React from "react";
import { Palette } from "lucide-react";
import { useTheme } from "../hooks/useTheme";
import Button from "./Button";

interface ThemeToggleProps {
  className?: string;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}

export default function ThemeToggle({
  className = "",
  size = "md",
  showLabel = false,
}: ThemeToggleProps) {
  const { toggleTheme, themeLabel, nextThemeLabel } = useTheme();

  const sizeClasses = {
    sm: "w-8 h-8 text-sm",
    md: "w-10 h-10 text-base",
    lg: "w-12 h-12 text-lg",
  };

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {showLabel && (
        <span className="text-sm text-text-secondary">
          {themeLabel}
        </span>
      )}
      <Button
        onClick={toggleTheme}
        variant="ghost"
        size="sm"
        className={`${sizeClasses[size]} p-2 rounded-lg transition-all duration-300 hover:bg-bg-elevated focus:ring-2 focus:ring-accent-purple focus:ring-offset-2 focus:ring-offset-bg-surface`}
        title={`Switch to ${nextThemeLabel} theme`}
        aria-label={`Switch to ${nextThemeLabel} theme`}
      >
        <Palette className="w-5 h-5" aria-hidden="true" />
      </Button>
    </div>
  );
}

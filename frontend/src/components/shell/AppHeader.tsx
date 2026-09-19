"use client";

import React from "react";
import Link from "next/link";
import { BookOpen, MoreHorizontal, Palette, Settings } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import styles from "./AppHeader.module.css";

type Destination = { href: string; label: string };

export interface AppHeaderProps {
  current?: "library" | "settings";
  children?: React.ReactNode;
  onNavigate?: (destination: string) => void;
  /** Workspace navigation must pass through its unsaved-work guard. */
  guarded?: boolean;
  moreItems?: Destination[];
  navigationLabel?: string;
}

const secondaryItems: Destination[] = [
  { href: "/about", label: "About ClauseIQ" },
];

export function AppHeader({ current, children, onNavigate, guarded = false,
  moreItems = [], navigationLabel = "Main navigation" }: AppHeaderProps) {
  const { nextThemeLabel, toggleTheme } = useTheme();

  function closeMenu(target?: HTMLElement) {
    const menu = target?.closest("details");
    if (menu) menu.open = false;
  }

  function destination(href: string, label: React.ReactNode, className: string, active = false) {
    if (guarded && onNavigate) return <button type="button" className={className}
      aria-current={active ? "page" : undefined} onClick={event => {
        closeMenu(event?.currentTarget);
        onNavigate(href);
      }}>{label}</button>;
    return <Link href={href} className={className} aria-current={active ? "page" : undefined}
      onClick={(event: React.MouseEvent<HTMLAnchorElement>) => {
        // Preserve ordinary modified-link behaviour for Library/Import.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
        closeMenu(event.currentTarget);
        if (!onNavigate) return;
        event.preventDefault();
        onNavigate(href);
      }}>{label}</Link>;
  }

  return <header className={styles.header} data-document={children ? "true" : undefined}>
    <div className={styles.identity}>
      {destination("/documents", "ClauseIQ", styles.brand)}
      {children && <div className={styles.context}>{children}</div>}
    </div>
    <nav className={styles.navigation} aria-label={navigationLabel}>
      {destination("/documents", <><BookOpen size={19} aria-hidden="true" /><span>Library</span></>, styles.link, current === "library")}
      {destination("/settings", <><Settings size={19} aria-hidden="true" /><span>Settings</span></>, styles.link, current === "settings")}
      <button type="button" className={styles.theme} onClick={toggleTheme}
        title={`Switch to ${nextThemeLabel} theme`} aria-label={`Switch to ${nextThemeLabel} theme`}>
        <Palette size={20} aria-hidden="true" />
      </button>
      <details className={styles.more} onKeyDown={event => {
        if (event.key !== "Escape" || !event.currentTarget.open) return;
        event.preventDefault();
        event.currentTarget.open = false;
        event.currentTarget.querySelector("summary")?.focus();
      }}>
        <summary><MoreHorizontal size={20} aria-hidden="true" /><span>More</span></summary>
        <div className={styles.menu}>
          {[...moreItems, ...secondaryItems].map(item => <React.Fragment key={item.href}>
            {destination(item.href, item.label, styles.menuLink)}
          </React.Fragment>)}
        </div>
      </details>
    </nav>
  </header>;
}

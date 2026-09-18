"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import clsx from "clsx";
import ThemeToggle from "./ThemeToggle";

const links = [
  { href: "/", label: "Upload" },
  { href: "/documents", label: "Documents" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
  { href: "/about", label: "About" },
];

export default function NavBar() {
  const path = usePathname();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const navigation = links.map(({ href, label }) => (
    <Link key={href} href={href} onClick={() => setIsMenuOpen(false)}
      aria-current={path === href ? "page" : undefined}
      className={clsx("block px-3 py-2 text-sm font-medium rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-purple",
        path === href ? "text-text-primary bg-bg-elevated" : "text-text-secondary hover:text-text-primary hover:bg-bg-elevated")}
    >{label}</Link>
  ));

  return <nav className="bg-bg-surface border-b border-border-muted" aria-label="Main navigation">
    <div className="max-w-7xl mx-auto px-6 lg:px-8 flex h-16 items-center justify-between gap-4">
      <Link href="/" className="font-heading text-xl font-semibold text-text-primary">ClauseIQ</Link>
      <div className="hidden md:flex items-center gap-1">{navigation}</div>
      <div className="flex items-center gap-3">
        <span className="hidden lg:block text-xs text-text-secondary">Local workspace</span>
        <ThemeToggle size="sm" />
        <button type="button" className="md:hidden px-3 py-2 rounded-md border border-border-muted text-sm"
          onClick={() => setIsMenuOpen(!isMenuOpen)} aria-expanded={isMenuOpen} aria-controls="mobile-navigation">
          {isMenuOpen ? "Close" : "Menu"}
        </button>
      </div>
    </div>
    {isMenuOpen && <div id="mobile-navigation" className="md:hidden px-6 pb-3 space-y-1">{navigation}</div>}
  </nav>;
}

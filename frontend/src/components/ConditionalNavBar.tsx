"use client";
import { usePathname } from "next/navigation";
import NavBar from "./NavBar";

export default function ConditionalNavBar() {
  const pathname = usePathname();

  // Library/review screens provide their own navigation; reviews guard unsaved work.
  // usePathname excludes the query string; do not hide unrelated route prefixes.
  if (pathname.startsWith("/review") || pathname === "/workspace" || pathname === "/documents" || pathname === "/import") {
    return null;
  }

  return <NavBar />;
}

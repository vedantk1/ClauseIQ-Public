"use client";
import { usePathname } from "next/navigation";
import { AppHeader } from "./shell/AppHeader";

export default function NavBar() {
  const pathname = usePathname();
  return <AppHeader current={pathname === "/settings" ? "settings" : pathname === "/documents" ? "library" : undefined} />;
}

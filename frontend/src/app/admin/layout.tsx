"use client";

import React, { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { adminApi } from "@/lib/adminApi";
import ThemeToggle from "@/components/ThemeToggle";
import clsx from "clsx";
import {
  LayoutDashboard,
  Users,
  FileText,
  Database,
  ClipboardList,
  Settings,
  Lock,
} from "lucide-react";

interface AdminLayoutProps {
  children: React.ReactNode;
}

const navItems = [
  { href: "/admin", label: "Dashboard", icon: LayoutDashboard },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/documents", label: "Documents", icon: FileText },
  { href: "/admin/database", label: "Database", icon: Database },
  { href: "/admin/logs", label: "Logs", icon: ClipboardList },
  { href: "/admin/settings", label: "Settings", icon: Settings },
];

export default function AdminLayout({ children }: AdminLayoutProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [checkingAccess, setCheckingAccess] = useState(true);

  useEffect(() => {
    const checkAdminAccess = async () => {
      if (!isAuthenticated) {
        setCheckingAccess(false);
        return;
      }

      try {
        const response = await adminApi.checkAccess();
        if (response.success && response.data?.is_admin) {
          setIsAdmin(true);
        } else {
          setIsAdmin(false);
        }
      } catch {
        console.error("Admin access check failed");
        setIsAdmin(false);
      } finally {
        setCheckingAccess(false);
      }
    };

    if (!authLoading) {
      checkAdminAccess();
    }
  }, [isAuthenticated, authLoading]);

  // Show loading state
  if (authLoading || checkingAccess) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent-purple mx-auto mb-4"></div>
          <p className="text-text-secondary text-sm font-mono">Checking access...</p>
        </div>
      </div>
    );
  }

  // Redirect if not authenticated
  if (!isAuthenticated) {
    router.push("/login");
    return null;
  }

  // Show access denied
  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center">
        <div className="text-center max-w-md mx-auto px-4">
          <div className="flex justify-center mb-4">
            <Lock className="w-16 h-16 text-text-secondary" />
          </div>
          <h1 className="text-2xl font-bold text-text-primary mb-2">Access Denied</h1>
          <p className="text-text-secondary mb-6">
            You don&apos;t have admin privileges. Contact an administrator if you believe this is an error.
          </p>
          <Link
            href="/"
            className="inline-block px-4 py-2 bg-accent-purple text-white rounded-md hover:bg-purple-600 transition-colors"
          >
            Go to Home
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Admin Header */}
      <header className="bg-bg-surface border-b border-border-muted sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            {/* Logo & Title */}
            <div className="flex items-center gap-3">
              <Link href="/admin" className="flex items-center gap-2">
                <Settings className="w-5 h-5 text-accent-purple" />
                <span className="font-mono font-semibold text-text-primary">Admin Portal</span>
              </Link>
              <span className="text-xs bg-accent-purple/20 text-accent-purple px-2 py-0.5 rounded font-mono">
                v1.0
              </span>
            </div>

            {/* Nav Items */}
            <nav className="hidden md:flex items-center gap-1">
              {navItems.map((item) => {
                const isActive = pathname === item.href ||
                  (item.href !== "/admin" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx(
                      "px-3 py-1.5 rounded-md text-sm font-medium transition-colors flex items-center gap-1.5",
                      isActive
                        ? "bg-accent-purple/20 text-accent-purple"
                        : "text-text-secondary hover:text-text-primary hover:bg-bg-elevated"
                    )}
                  >
                    <item.icon className="w-4 h-4" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>

            {/* Right side */}
            <div className="flex items-center gap-4">
              <ThemeToggle size="sm" />
              <div className="text-xs text-text-secondary font-mono">
                {user?.email}
              </div>
              <Link
                href="/"
                className="text-xs text-text-secondary hover:text-text-primary transition-colors"
              >
                ← Back to App
              </Link>
            </div>
          </div>
        </div>

        {/* Mobile Nav */}
        <div className="md:hidden border-t border-border-muted">
          <div className="flex overflow-x-auto px-4 py-2 gap-2">
            {navItems.map((item) => {
              const isActive = pathname === item.href ||
                (item.href !== "/admin" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-1",
                    isActive
                      ? "bg-accent-purple/20 text-accent-purple"
                      : "text-text-secondary hover:text-text-primary hover:bg-bg-elevated"
                  )}
                >
                  <item.icon className="w-4 h-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>
    </div>
  );
}

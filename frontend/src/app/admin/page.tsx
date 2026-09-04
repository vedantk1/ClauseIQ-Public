"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi, AdminStats } from "@/lib/adminApi";
import clsx from "clsx";
import {
  Users,
  FileText,
  ClipboardList,
  Database,
  LucideIcon,
} from "lucide-react";

interface StatCardProps {
  label: string;
  value: number | string;
  icon: LucideIcon;
  trend?: { value: number; label: string };
  href?: string;
}

function StatCard({ label, value, icon: Icon, trend, href }: StatCardProps) {
  const content = (
    <div className="bg-bg-surface border border-border-muted rounded-lg p-4 hover:border-accent-purple/50 transition-colors">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-text-secondary text-xs font-mono uppercase tracking-wider">{label}</p>
          <p className="text-2xl font-bold text-text-primary mt-1 font-mono">{value}</p>
          {trend && (
            <p className={clsx(
              "text-xs mt-1 font-mono",
              trend.value > 0 ? "text-accent-green" : "text-text-secondary"
            )}>
              {trend.value > 0 ? "+" : ""}{trend.value} {trend.label}
            </p>
          )}
        </div>
        <Icon className="w-6 h-6 text-accent-purple" />
      </div>
    </div>
  );

  if (href) {
    return <Link href={href}>{content}</Link>;
  }
  return content;
}

export default function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await adminApi.getStats();
        if (response.success && response.data) {
          setStats(response.data);
        } else {
          setError(response.error?.message || "Failed to load stats");
        }
      } catch {
        setError("Failed to connect to server");
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse">
          <div className="h-8 bg-bg-surface rounded w-48 mb-6"></div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-bg-surface rounded-lg"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-accent-rose/10 border border-accent-rose/20 rounded-lg p-4">
        <p className="text-accent-rose font-mono text-sm">Error: {error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Dashboard</h1>
          <p className="text-text-secondary text-sm font-mono">System overview and statistics</p>
        </div>
        <div className="text-xs text-text-secondary font-mono">
          Last updated: {new Date().toLocaleTimeString()}
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Users"
          value={stats?.user_count ?? 0}
          icon={Users}
          trend={{ value: stats?.recent_users_7d ?? 0, label: "last 7 days" }}
          href="/admin/users"
        />
        <StatCard
          label="Total Documents"
          value={stats?.document_count ?? 0}
          icon={FileText}
          trend={{ value: stats?.recent_documents_7d ?? 0, label: "last 7 days" }}
          href="/admin/documents"
        />
        <StatCard
          label="Contract Types"
          value={stats?.contract_type_breakdown?.length ?? 0}
          icon={ClipboardList}
        />
        <StatCard
          label="Database"
          value="Online"
          icon={Database}
          href="/admin/database"
        />
      </div>

      {/* Contract Types Breakdown */}
      {stats?.contract_type_breakdown && stats.contract_type_breakdown.length > 0 && (
        <div className="bg-bg-surface border border-border-muted rounded-lg p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">Contract Type Distribution</h2>
          <div className="space-y-2">
            {stats.contract_type_breakdown.map((item, index) => {
              const maxCount = Math.max(...stats.contract_type_breakdown.map(i => i.count));
              const percentage = (item.count / maxCount) * 100;
              return (
                <div key={index} className="flex items-center gap-3">
                  <div className="w-32 text-sm text-text-secondary font-mono truncate">
                    {item.type}
                  </div>
                  <div className="flex-1 h-6 bg-bg-elevated rounded overflow-hidden">
                    <div
                      className="h-full bg-accent-purple/30 rounded"
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                  <div className="w-12 text-right text-sm font-mono text-text-primary">
                    {item.count}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="bg-bg-surface border border-border-muted rounded-lg p-4">
        <h2 className="text-lg font-semibold text-text-primary mb-4">Quick Actions</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Link
            href="/admin/users"
            className="flex items-center gap-2 p-3 bg-bg-elevated rounded-lg hover:bg-bg-primary border border-transparent hover:border-border-muted transition-colors"
          >
            <Users className="w-4 h-4 text-accent-purple" />
            <span className="text-sm text-text-primary">Manage Users</span>
          </Link>
          <Link
            href="/admin/documents"
            className="flex items-center gap-2 p-3 bg-bg-elevated rounded-lg hover:bg-bg-primary border border-transparent hover:border-border-muted transition-colors"
          >
            <FileText className="w-4 h-4 text-accent-purple" />
            <span className="text-sm text-text-primary">Manage Documents</span>
          </Link>
          <Link
            href="/admin/database"
            className="flex items-center gap-2 p-3 bg-bg-elevated rounded-lg hover:bg-bg-primary border border-transparent hover:border-border-muted transition-colors"
          >
            <Database className="w-4 h-4 text-accent-purple" />
            <span className="text-sm text-text-primary">View Database</span>
          </Link>
          <Link
            href="/admin/logs"
            className="flex items-center gap-2 p-3 bg-bg-elevated rounded-lg hover:bg-bg-primary border border-transparent hover:border-border-muted transition-colors"
          >
            <ClipboardList className="w-4 h-4 text-accent-purple" />
            <span className="text-sm text-text-primary">View Logs</span>
          </Link>
        </div>
      </div>

      {/* System Info */}
      <div className="bg-bg-surface border border-border-muted rounded-lg p-4">
        <h2 className="text-lg font-semibold text-text-primary mb-4">System Information</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm font-mono">
          <div>
            <p className="text-text-secondary text-xs">Environment</p>
            <p className="text-text-primary">{process.env.NODE_ENV}</p>
          </div>
          <div>
            <p className="text-text-secondary text-xs">API URL</p>
            <p className="text-text-primary truncate">{process.env.NEXT_PUBLIC_API_URL || "localhost:8000"}</p>
          </div>
          <div>
            <p className="text-text-secondary text-xs">Frontend Version</p>
            <p className="text-text-primary">1.0.0</p>
          </div>
          <div>
            <p className="text-text-secondary text-xs">Status</p>
            <p className="text-accent-green">● Operational</p>
          </div>
        </div>
      </div>
    </div>
  );
}

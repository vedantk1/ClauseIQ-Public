"use client";

import React, { useEffect, useState, useCallback } from "react";
import { adminApi, AuditLogEntry } from "@/lib/adminApi";
import clsx from "clsx";
import {
  KeyRound,
  LogOut,
  Plus,
  Pencil,
  Trash2,
  Upload,
  Search,
  Pin,
  RefreshCw,
  LucideIcon,
} from "lucide-react";

const LOG_LEVELS = ["ALL", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

const levelColors: Record<string, { bg: string; text: string }> = {
  DEBUG: { bg: "bg-gray-500/20", text: "text-gray-400" },
  INFO: { bg: "bg-accent-green/20", text: "text-accent-green" },
  WARNING: { bg: "bg-accent-amber/20", text: "text-accent-amber" },
  ERROR: { bg: "bg-accent-rose/20", text: "text-accent-rose" },
  CRITICAL: { bg: "bg-red-700/30", text: "text-red-400" },
};

const actionIcons: Record<string, LucideIcon> = {
  login: KeyRound,
  logout: LogOut,
  create: Plus,
  update: Pencil,
  delete: Trash2,
  upload: Upload,
  analyze: Search,
};

export default function LogsPage() {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [pagination, setPagination] = useState({ total: 0, limit: 100, offset: 0 });
  const [levelFilter, setLevelFilter] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const response = await adminApi.getLogs({
        limit: pagination.limit,
        offset: pagination.offset,
        level: levelFilter === "ALL" ? undefined : levelFilter,
        search: search || undefined,
      });
      if (response.success && response.data) {
        setLogs(response.data.items);
        setPagination((p) => ({ ...p, total: response.data!.total }));
      }
    } catch {
      console.error("Failed to fetch logs");
    } finally {
      setLoading(false);
    }
  }, [pagination.limit, pagination.offset, levelFilter, search]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchLogs]);

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleString();
    } catch {
      return timestamp;
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Audit Logs</h1>
          <p className="text-text-secondary text-sm font-mono">{pagination.total} log entries</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-border-muted"
            />
            Auto-refresh
          </label>
          <button
            onClick={fetchLogs}
            disabled={loading}
            className="px-3 py-1.5 text-sm bg-bg-surface text-text-primary rounded border border-border-muted hover:bg-bg-elevated disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            <RefreshCw className={clsx("w-3.5 h-3.5", loading && "animate-spin")} />
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1">
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPagination((p) => ({ ...p, offset: 0 }));
            }}
            placeholder="Search in log messages..."
            className="w-full px-3 py-2 bg-bg-surface border border-border-muted rounded-md text-text-primary placeholder:text-text-secondary focus:border-accent-purple focus:outline-none font-mono text-sm"
          />
        </div>
        <div className="flex gap-1">
          {LOG_LEVELS.map((level) => (
            <button
              key={level}
              onClick={() => {
                setLevelFilter(level);
                setPagination((p) => ({ ...p, offset: 0 }));
              }}
              className={clsx(
                "px-3 py-2 text-xs font-mono rounded transition-colors",
                levelFilter === level
                  ? "bg-accent-purple text-white"
                  : "bg-bg-surface text-text-secondary hover:text-text-primary border border-border-muted"
              )}
            >
              {level}
            </button>
          ))}
        </div>
      </div>

      {/* Logs List */}
      <div className="bg-bg-surface border border-border-muted rounded-lg overflow-hidden">
        <div className="divide-y divide-border-muted">
          {loading && logs.length === 0 ? (
            [...Array(10)].map((_, i) => (
              <div key={i} className="px-4 py-3 animate-pulse">
                <div className="h-4 bg-bg-elevated rounded w-3/4"></div>
              </div>
            ))
          ) : logs.length === 0 ? (
            <div className="px-4 py-8 text-center text-text-secondary">
              <p>No log entries found</p>
              <p className="text-xs mt-1">Logs are generated as the application runs</p>
            </div>
          ) : (
            logs.map((log, index) => {
              const colors = levelColors[log.level] || levelColors.INFO;
              return (
                <div
                  key={index}
                  className="px-4 py-3 hover:bg-bg-elevated/50 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    {/* Level Badge */}
                    <span
                      className={clsx(
                        "px-2 py-0.5 rounded text-xs font-mono font-medium shrink-0",
                        colors.bg,
                        colors.text
                      )}
                    >
                      {log.level}
                    </span>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        {/* Action Icon */}
                        {log.action && (() => {
                          const IconComponent = actionIcons[log.action] || Pin;
                          return <span title={log.action}><IconComponent className="w-4 h-4 text-text-secondary shrink-0" /></span>;
                        })()}

                        {/* Message */}
                        <p className="text-text-primary text-sm font-mono break-words">
                          {log.message}
                        </p>
                      </div>

                      {/* Metadata */}
                      <div className="flex flex-wrap items-center gap-3 text-xs text-text-secondary">
                        <span className="font-mono">{formatTimestamp(log.timestamp)}</span>
                        {log.source && (
                          <span className="text-accent-purple font-mono">[{log.source}]</span>
                        )}
                        {log.user_id && (
                          <span className="font-mono">user:{log.user_id.slice(0, 8)}...</span>
                        )}
                        {log.action && (
                          <span className="bg-bg-elevated px-1.5 py-0.5 rounded font-mono">
                            {log.action}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Pagination */}
        {pagination.total > pagination.limit && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border-muted">
            <p className="text-xs text-text-secondary font-mono">
              Showing {pagination.offset + 1}-{Math.min(pagination.offset + pagination.limit, pagination.total)} of {pagination.total}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPagination((p) => ({ ...p, offset: Math.max(0, p.offset - p.limit) }))}
                disabled={pagination.offset === 0}
                className="px-3 py-1 text-sm bg-bg-elevated text-text-primary rounded disabled:opacity-50 hover:bg-bg-primary transition-colors"
              >
                Previous
              </button>
              <button
                onClick={() => setPagination((p) => ({ ...p, offset: p.offset + p.limit }))}
                disabled={pagination.offset + pagination.limit >= pagination.total}
                className="px-3 py-1 text-sm bg-bg-elevated text-text-primary rounded disabled:opacity-50 hover:bg-bg-primary transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="bg-bg-surface border border-border-muted rounded-lg p-4">
        <h3 className="font-semibold text-text-primary mb-3">Log Levels</h3>
        <div className="flex flex-wrap gap-3">
          {Object.entries(levelColors).map(([level, colors]) => (
            <div key={level} className="flex items-center gap-2">
              <span className={clsx("px-2 py-0.5 rounded text-xs font-mono", colors.bg, colors.text)}>
                {level}
              </span>
              <span className="text-xs text-text-secondary">
                {level === "DEBUG" && "Detailed debugging information"}
                {level === "INFO" && "General operational messages"}
                {level === "WARNING" && "Potential issues or concerns"}
                {level === "ERROR" && "Errors that need attention"}
                {level === "CRITICAL" && "Critical system failures"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Action Icons Legend */}
      <div className="bg-bg-surface border border-border-muted rounded-lg p-4">
        <h3 className="font-semibold text-text-primary mb-3">Action Types</h3>
        <div className="flex flex-wrap gap-4">
          {Object.entries(actionIcons).map(([action, IconComponent]) => (
            <div key={action} className="flex items-center gap-1.5 text-sm">
              <IconComponent className="w-4 h-4 text-text-secondary" />
              <span className="text-text-secondary font-mono">{action}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

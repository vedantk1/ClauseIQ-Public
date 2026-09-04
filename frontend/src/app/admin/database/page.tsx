"use client";

import React, { useEffect, useState, useCallback } from "react";
import { adminApi, DatabaseSchema, CollectionInfo } from "@/lib/adminApi";
import clsx from "clsx";
import { FolderArchive, X, ChevronDown, ChevronRight } from "lucide-react";

interface CollectionBrowserProps {
  collection: CollectionInfo;
  onClose: () => void;
}

function CollectionBrowser({ collection, onClose }: CollectionBrowserProps) {
  const [documents, setDocuments] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [pagination, setPagination] = useState({ total: 0, limit: 10, offset: 0 });

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const response = await adminApi.browseCollection(collection.name, {
        limit: pagination.limit,
        offset: pagination.offset,
      });
      if (response.success && response.data) {
        setDocuments(response.data.items);
        setPagination((p) => ({ ...p, total: response.data!.total }));
      }
    } catch {
      console.error("Failed to browse collection");
    } finally {
      setLoading(false);
    }
  }, [collection.name, pagination.limit, pagination.offset]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-bg-surface border border-border-muted rounded-lg w-full max-w-4xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-border-muted">
          <div>
            <h2 className="text-lg font-semibold text-text-primary font-mono">{collection.name}</h2>
            <p className="text-text-secondary text-xs">{collection.document_count} documents</p>
          </div>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="animate-pulse space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-32 bg-bg-elevated rounded"></div>
              ))}
            </div>
          ) : documents.length === 0 ? (
            <p className="text-text-secondary text-center py-8">No documents in this collection</p>
          ) : (
            <div className="space-y-3">
              {documents.map((doc, index) => (
                <div
                  key={index}
                  className="bg-bg-primary border border-border-muted rounded-lg p-3 overflow-x-auto"
                >
                  <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap break-words">
                    {JSON.stringify(doc, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
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
    </div>
  );
}

export default function DatabasePage() {
  const [schema, setSchema] = useState<DatabaseSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCollection, setSelectedCollection] = useState<CollectionInfo | null>(null);
  const [expandedSamples, setExpandedSamples] = useState<Set<string>>(new Set());

  useEffect(() => {
    const fetchSchema = async () => {
      try {
        const response = await adminApi.getDatabaseSchema();
        if (response.success && response.data) {
          setSchema(response.data);
        } else {
          setError(response.error?.message || "Failed to load schema");
        }
      } catch {
        setError("Failed to connect to server");
      } finally {
        setLoading(false);
      }
    };

    fetchSchema();
  }, []);

  const toggleSample = (collName: string) => {
    const newExpanded = new Set(expandedSamples);
    if (newExpanded.has(collName)) {
      newExpanded.delete(collName);
    } else {
      newExpanded.add(collName);
    }
    setExpandedSamples(newExpanded);
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 bg-bg-surface rounded w-48 animate-pulse"></div>
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-32 bg-bg-surface rounded-lg animate-pulse"></div>
          ))}
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
      <div>
        <h1 className="text-2xl font-bold text-text-primary">Database</h1>
        <p className="text-text-secondary text-sm font-mono">
          {schema?.database_name} • {schema?.collections.length} collections
        </p>
      </div>

      {/* Collections Grid */}
      <div className="grid gap-4">
        {schema?.collections.map((collection) => (
          <div
            key={collection.name}
            className="bg-bg-surface border border-border-muted rounded-lg overflow-hidden"
          >
            {/* Collection Header */}
            <div className="flex items-center justify-between p-4 border-b border-border-muted">
              <div className="flex items-center gap-3">
                <FolderArchive className="w-6 h-6 text-accent-purple" />
                <div>
                  <h3 className="font-semibold text-text-primary font-mono">{collection.name}</h3>
                  <p className="text-text-secondary text-xs">
                    {collection.document_count.toLocaleString()} documents • {collection.indexes.length} indexes
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSelectedCollection(collection)}
                className="px-3 py-1.5 text-sm bg-bg-elevated text-text-primary rounded hover:bg-bg-primary border border-border-muted transition-colors"
              >
                Browse →
              </button>
            </div>

            {/* Indexes */}
            {collection.indexes.length > 0 && (
              <div className="p-4 border-b border-border-muted bg-bg-elevated/30">
                <p className="text-xs text-text-secondary uppercase tracking-wider mb-2">Indexes</p>
                <div className="flex flex-wrap gap-2">
                  {collection.indexes.map((idx) => (
                    <span
                      key={idx.name}
                      className={clsx(
                        "px-2 py-1 rounded text-xs font-mono",
                        idx.unique
                          ? "bg-accent-purple/20 text-accent-purple"
                          : "bg-bg-elevated text-text-secondary"
                      )}
                      title={`Keys: ${JSON.stringify(idx.keys)}`}
                    >
                      {idx.name}
                      {idx.unique && " (unique)"}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Sample Document */}
            {collection.sample_document && (
              <div className="p-4">
                <button
                  onClick={() => toggleSample(collection.name)}
                  className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors mb-2"
                >
                  {expandedSamples.has(collection.name) ? (
                    <ChevronDown className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5" />
                  )}
                  <span className="uppercase tracking-wider">Sample Document Schema</span>
                </button>
                {expandedSamples.has(collection.name) && (
                  <div className="bg-bg-primary border border-border-muted rounded p-3 overflow-x-auto">
                    <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap break-words">
                      {JSON.stringify(collection.sample_document, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Collection Browser Modal */}
      {selectedCollection && (
        <CollectionBrowser
          collection={selectedCollection}
          onClose={() => setSelectedCollection(null)}
        />
      )}

      {/* Help Text */}
      <div className="bg-bg-surface border border-border-muted rounded-lg p-4">
        <h3 className="font-semibold text-text-primary mb-2">Tips</h3>
        <ul className="text-sm text-text-secondary space-y-1">
          <li>• Click <strong>Browse</strong> to view documents in any collection</li>
          <li>• Sensitive fields like passwords are automatically redacted</li>
          <li>• Large fields are truncated for display</li>
          <li>• For advanced queries, use MongoDB Compass connected to your database</li>
        </ul>
      </div>
    </div>
  );
}

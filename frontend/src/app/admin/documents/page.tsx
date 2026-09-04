"use client";

import React, { useEffect, useState, useCallback } from "react";
import { adminApi, DocumentListItem, UserListItem } from "@/lib/adminApi";
import toast from "@/lib/toast";
import clsx from "clsx";
import { FileText, Search, MessageSquare } from "lucide-react";
import ConfirmModal from "@/components/ui/ConfirmModal";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [pagination, setPagination] = useState({ total: 0, limit: 20, offset: 0 });
  const [search, setSearch] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [confirmDeleteDoc, setConfirmDeleteDoc] = useState<DocumentListItem | null>(null);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState<{
    count: number;
    docsByUser: Array<{ userId: string; docIds: string[] }>;
  } | null>(null);

  // Fetch users for filter dropdown
  useEffect(() => {
    const fetchUsers = async () => {
      try {
        const response = await adminApi.listUsers({ limit: 100 });
        if (response.success && response.data) {
          setUsers(response.data.items);
        }
      } catch {
        console.error("Failed to fetch users");
      }
    };
    fetchUsers();
  }, []);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const response = await adminApi.listDocuments({
        limit: pagination.limit,
        offset: pagination.offset,
        search: search || undefined,
        user_id: userFilter || undefined,
      });
      if (response.success && response.data) {
        setDocuments(response.data.items);
        setPagination((p) => ({ ...p, total: response.data!.total }));
      }
    } catch {
      console.error("Failed to fetch documents");
    } finally {
      setLoading(false);
    }
  }, [pagination.limit, pagination.offset, search, userFilter]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleSelectAll = () => {
    if (selectedDocs.size === documents.length) {
      setSelectedDocs(new Set());
    } else {
      setSelectedDocs(new Set(documents.map((d) => d.id)));
    }
  };

  const handleSelect = (docId: string) => {
    const newSelected = new Set(selectedDocs);
    if (newSelected.has(docId)) {
      newSelected.delete(docId);
    } else {
      newSelected.add(docId);
    }
    setSelectedDocs(newSelected);
  };

  const handleDelete = (doc: DocumentListItem) => {
    setConfirmDeleteDoc(doc);
  };

  const handleDeleteConfirmed = async () => {
    if (!confirmDeleteDoc) return;
    try {
      setDeletingDocId(confirmDeleteDoc.id);
      const response = await adminApi.deleteDocument(confirmDeleteDoc.id, confirmDeleteDoc.user_id);
      if (response.success) {
        toast.success("Document deleted");
        fetchDocuments();
        setSelectedDocs(new Set());
      } else {
        toast.error(response.error?.message || "Failed to delete document");
      }
    } catch {
      toast.error("An error occurred");
    } finally {
      setDeletingDocId(null);
      setConfirmDeleteDoc(null);
    }
  };

  const handleBulkDelete = () => {
    if (selectedDocs.size === 0) return;
    const docsByUser = new Map<string, string[]>();
    documents
      .filter((d) => selectedDocs.has(d.id))
      .forEach((doc) => {
        const existing = docsByUser.get(doc.user_id) || [];
        existing.push(doc.id);
        docsByUser.set(doc.user_id, existing);
      });

    setConfirmBulkDelete({
      count: selectedDocs.size,
      docsByUser: Array.from(docsByUser.entries()).map(([userId, docIds]) => ({ userId, docIds })),
    });
  };

  const handleBulkDeleteConfirmed = async () => {
    if (!confirmBulkDelete || confirmBulkDelete.count === 0) {
      setConfirmBulkDelete(null);
      return;
    }

    setDeleting(true);
    let totalDeleted = 0;
    let totalFailed = 0;

    try {
      for (const { userId, docIds } of confirmBulkDelete.docsByUser) {
        const response = await adminApi.bulkDeleteDocuments(docIds, userId);
        if (response.success && response.data) {
          totalDeleted += response.data.deleted_count;
          totalFailed += response.data.failed_ids.length;
        }
      }

      if (totalDeleted > 0) {
        toast.success(`Deleted ${totalDeleted} documents`);
      }
      if (totalFailed > 0) {
        toast.error(`Failed to delete ${totalFailed} documents`);
      }

      fetchDocuments();
      setSelectedDocs(new Set());
    } catch {
      toast.error("An error occurred");
    } finally {
      setDeleting(false);
      setConfirmBulkDelete(null);
    }
  };

  const getUserEmail = (userId: string) => {
    const user = users.find((u) => u.id === userId);
    return user?.email || userId.slice(0, 8) + "...";
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-text-primary">Documents</h1>
        <p className="text-text-secondary text-sm font-mono">{pagination.total} total documents</p>
      </div>

      {/* Filters Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1">
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPagination((p) => ({ ...p, offset: 0 }));
            }}
            placeholder="Search by filename or contract type..."
            className="w-full px-3 py-2 bg-bg-surface border border-border-muted rounded-md text-text-primary placeholder:text-text-secondary focus:border-accent-purple focus:outline-none font-mono text-sm"
          />
        </div>
        <select
          value={userFilter}
          onChange={(e) => {
            setUserFilter(e.target.value);
            setPagination((p) => ({ ...p, offset: 0 }));
          }}
          className="px-3 py-2 bg-bg-surface border border-border-muted rounded-md text-text-primary focus:border-accent-purple focus:outline-none font-mono text-sm"
        >
          <option value="">All Users</option>
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.email}
            </option>
          ))}
        </select>
        {selectedDocs.size > 0 && (
          <button
            onClick={handleBulkDelete}
            disabled={deleting}
            className="px-4 py-2 bg-accent-rose text-white rounded-md hover:bg-red-600 disabled:opacity-50 transition-colors text-sm whitespace-nowrap"
          >
            {deleting ? "Deleting..." : `Delete ${selectedDocs.size} Selected`}
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-bg-surface border border-border-muted rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-muted bg-bg-elevated">
                <th className="px-4 py-3 text-left">
                  <input
                    type="checkbox"
                    checked={selectedDocs.size === documents.length && documents.length > 0}
                    onChange={handleSelectAll}
                    className="rounded border-border-muted"
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider">
                  Document
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider hidden md:table-cell">
                  Owner
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider hidden lg:table-cell">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider hidden lg:table-cell">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider hidden xl:table-cell">
                  Created
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-text-secondary uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-muted">
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td className="px-4 py-3"><div className="h-4 w-4 bg-bg-elevated rounded"></div></td>
                    <td className="px-4 py-3"><div className="h-4 bg-bg-elevated rounded w-48"></div></td>
                    <td className="px-4 py-3 hidden md:table-cell"><div className="h-4 bg-bg-elevated rounded w-32"></div></td>
                    <td className="px-4 py-3 hidden lg:table-cell"><div className="h-4 bg-bg-elevated rounded w-20"></div></td>
                    <td className="px-4 py-3 hidden lg:table-cell"><div className="h-4 bg-bg-elevated rounded w-16"></div></td>
                    <td className="px-4 py-3 hidden xl:table-cell"><div className="h-4 bg-bg-elevated rounded w-24"></div></td>
                    <td className="px-4 py-3"><div className="h-4 bg-bg-elevated rounded w-16 ml-auto"></div></td>
                  </tr>
                ))
              ) : documents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-text-secondary">
                    No documents found
                  </td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-bg-elevated/50">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedDocs.has(doc.id)}
                        onChange={() => handleSelect(doc.id)}
                        className="rounded border-border-muted"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div>
                        <p className="text-text-primary font-medium truncate max-w-xs" title={doc.filename}>
                          {doc.filename}
                        </p>
                        <p className="text-text-secondary text-xs font-mono">{doc.id.slice(0, 8)}...</p>
                      </div>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <span className="text-text-secondary font-mono text-xs">
                        {getUserEmail(doc.user_id)}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <span className={clsx(
                        "px-2 py-0.5 rounded text-xs font-mono",
                        doc.contract_type
                          ? "bg-accent-purple/20 text-accent-purple"
                          : "bg-bg-elevated text-text-secondary"
                      )}>
                        {doc.contract_type || "unknown"}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <div className="flex items-center gap-1.5">
                        {doc.has_pdf_file && (
                          <span title="Has PDF"><FileText className="w-3.5 h-3.5 text-text-secondary" /></span>
                        )}
                        {doc.rag_processed && (
                          <span title="RAG Processed"><Search className="w-3.5 h-3.5 text-text-secondary" /></span>
                        )}
                        {doc.ready_for_chat && (
                          <span title="Ready for Chat"><MessageSquare className="w-3.5 h-3.5 text-accent-green" /></span>
                        )}
                        {!doc.has_pdf_file && !doc.rag_processed && (
                          <span className="text-text-secondary text-xs">-</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 hidden xl:table-cell">
                      <span className="text-text-secondary font-mono text-xs">
                        {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : "-"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end">
                        <button
                          onClick={() => handleDelete(doc)}
                          disabled={deleting || deletingDocId === doc.id}
                          className="px-2 py-1 text-xs text-accent-rose hover:bg-accent-rose/10 rounded transition-colors"
                        >
                          {deletingDocId === doc.id ? "Deleting..." : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
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
      <div className="flex items-center gap-4 text-xs text-text-secondary">
        <span className="flex items-center gap-1"><FileText className="w-3.5 h-3.5" /> Has PDF</span>
        <span className="flex items-center gap-1"><Search className="w-3.5 h-3.5" /> RAG Indexed</span>
        <span className="flex items-center gap-1"><MessageSquare className="w-3.5 h-3.5" /> Chat Ready</span>
      </div>

      {/* Confirm dialogs (avoid window.confirm which can be blocked by the browser) */}
      <ConfirmModal
        isOpen={!!confirmDeleteDoc}
        title="Delete Document"
        message={
          <>
            Are you sure you want to delete{" "}
            <span className="font-medium text-text-primary">
              &ldquo;{confirmDeleteDoc?.filename || "this document"}&rdquo;
            </span>
            ? This action cannot be undone.
          </>
        }
        confirmText="Delete"
        confirmVariant="danger"
        loading={!!deletingDocId}
        onClose={() => {
          if (deletingDocId) return;
          setConfirmDeleteDoc(null);
        }}
        onConfirm={() => {
          void handleDeleteConfirmed();
        }}
      />

      <ConfirmModal
        isOpen={!!confirmBulkDelete}
        title="Delete Documents"
        message={
          <>
            Are you sure you want to delete{" "}
            <span className="font-medium text-text-primary">
              {confirmBulkDelete?.count || 0}{" "}
              {(confirmBulkDelete?.count || 0) === 1 ? "document" : "documents"}
            </span>
            ? This action cannot be undone.
          </>
        }
        confirmText={`Delete ${confirmBulkDelete?.count || 0}`}
        confirmVariant="danger"
        loading={deleting}
        onClose={() => {
          if (deleting) return;
          setConfirmBulkDelete(null);
        }}
        onConfirm={() => {
          void handleBulkDeleteConfirmed();
        }}
      />
    </div>
  );
}

"use client";

import React, { useEffect, useState, useCallback } from "react";
import { adminApi, UserListItem, UserDetail } from "@/lib/adminApi";
import { useAuth } from "@/context/AuthContext";
import toast from "@/lib/toast";
import Modal from "@/components/ui/Modal";
import { X } from "lucide-react";

interface UserModalProps {
  user?: UserListItem | null;
  onClose: () => void;
  onSave: () => void;
}

function UserModal({ user, onClose, onSave }: UserModalProps) {
  const [formData, setFormData] = useState({
    email: user?.email || "",
    full_name: user?.full_name || "",
    password: "",
    preferred_model: user?.preferred_model || "",
  });
  const [saving, setSaving] = useState(false);

  const isEdit = !!user;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      if (isEdit) {
        const updateData: Record<string, string> = {};
        if (formData.email !== user.email) updateData.email = formData.email;
        if (formData.full_name !== user.full_name) updateData.full_name = formData.full_name;
        if (formData.password) updateData.password = formData.password;
        if (formData.preferred_model !== user.preferred_model) updateData.preferred_model = formData.preferred_model;

        const response = await adminApi.updateUser(user.id, updateData);
        if (response.success) {
          toast.success("User updated successfully");
          onSave();
        } else {
          toast.error(response.error?.message || "Failed to update user");
        }
      } else {
        if (!formData.password) {
          toast.error("Password is required for new users");
          setSaving(false);
          return;
        }
        const response = await adminApi.createUser({
          email: formData.email,
          full_name: formData.full_name,
          password: formData.password,
        });
        if (response.success) {
          toast.success("User created successfully");
          onSave();
        } else {
          toast.error(response.error?.message || "Failed to create user");
        }
      }
    } catch {
      toast.error("An error occurred");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-bg-surface border border-border-muted rounded-lg w-full max-w-md">
        <div className="flex items-center justify-between p-4 border-b border-border-muted">
          <h2 className="text-lg font-semibold text-text-primary">
            {isEdit ? "Edit User" : "Create User"}
          </h2>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">Email</label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              required
              className="w-full px-3 py-2 bg-bg-primary border border-border-muted rounded-md text-text-primary focus:border-accent-purple focus:outline-none font-mono text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">Full Name</label>
            <input
              type="text"
              value={formData.full_name}
              onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
              required
              minLength={2}
              className="w-full px-3 py-2 bg-bg-primary border border-border-muted rounded-md text-text-primary focus:border-accent-purple focus:outline-none font-mono text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">
              Password {isEdit && "(leave blank to keep current)"}
            </label>
            <input
              type="password"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              required={!isEdit}
              minLength={8}
              className="w-full px-3 py-2 bg-bg-primary border border-border-muted rounded-md text-text-primary focus:border-accent-purple focus:outline-none font-mono text-sm"
              placeholder={isEdit ? "••••••••" : ""}
            />
            <p className="text-xs text-text-secondary mt-1">Min 8 chars with letters and numbers</p>
          </div>

          {isEdit && (
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Preferred Model</label>
              <select
                value={formData.preferred_model}
                onChange={(e) => setFormData({ ...formData, preferred_model: e.target.value })}
                className="w-full px-3 py-2 bg-bg-primary border border-border-muted rounded-md text-text-primary focus:border-accent-purple focus:outline-none font-mono text-sm"
              >
                <option value="">Default</option>
                <option value="gpt-4.1">GPT-4.1</option>
                <option value="gpt-5-mini">GPT-5 Mini</option>
                <option value="gpt-5-nano">GPT-5 Nano</option>
              </select>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm bg-accent-purple text-white rounded-md hover:bg-purple-600 disabled:opacity-50 transition-colors"
            >
              {saving ? "Saving..." : isEdit ? "Update" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface UserDetailModalProps {
  userId: string;
  onClose: () => void;
}

function UserDetailModal({ userId, onClose }: UserDetailModalProps) {
  const [user, setUser] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await adminApi.getUser(userId);
        if (response.success && response.data) {
          setUser(response.data);
        }
      } catch {
        console.error("Failed to fetch user");
      } finally {
        setLoading(false);
      }
    };
    fetchUser();
  }, [userId]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-bg-surface border border-border-muted rounded-lg w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b border-border-muted">
          <h2 className="text-lg font-semibold text-text-primary">User Details</h2>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4">
          {loading ? (
            <div className="animate-pulse space-y-3">
              <div className="h-4 bg-bg-elevated rounded w-1/2"></div>
              <div className="h-4 bg-bg-elevated rounded w-3/4"></div>
              <div className="h-4 bg-bg-elevated rounded w-1/3"></div>
            </div>
          ) : user ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-text-secondary text-xs uppercase">ID</p>
                  <p className="text-text-primary font-mono text-xs truncate">{user.id}</p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs uppercase">Email</p>
                  <p className="text-text-primary font-mono">{user.email}</p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs uppercase">Name</p>
                  <p className="text-text-primary">{user.full_name}</p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs uppercase">Model</p>
                  <p className="text-text-primary font-mono">{user.preferred_model || "default"}</p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs uppercase">Created</p>
                  <p className="text-text-primary font-mono text-xs">
                    {user.created_at ? new Date(user.created_at).toLocaleString() : "-"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs uppercase">Documents</p>
                  <p className="text-text-primary font-mono">{user.document_count}</p>
                </div>
              </div>

              {user.recent_documents && user.recent_documents.length > 0 && (
                <div>
                  <p className="text-text-secondary text-xs uppercase mb-2">Recent Documents</p>
                  <div className="space-y-1">
                    {user.recent_documents.map((doc) => (
                      <div
                        key={doc.id}
                        className="flex items-center justify-between text-sm p-2 bg-bg-elevated rounded"
                      >
                        <span className="text-text-primary truncate">{doc.filename}</span>
                        <span className="text-text-secondary text-xs font-mono">
                          {doc.contract_type || "unknown"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-text-secondary">User not found</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [pagination, setPagination] = useState({ total: 0, limit: 20, offset: 0 });
  const [search, setSearch] = useState("");
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const [showModal, setShowModal] = useState<"create" | "edit" | null>(null);
  const [editingUser, setEditingUser] = useState<UserListItem | null>(null);
  const [viewingUserId, setViewingUserId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<{
    userId: string;
    email: string;
    fullName: string;
  } | null>(null);
  const [confirmBulkDeleteOpen, setConfirmBulkDeleteOpen] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const currentUserId = currentUser?.id;

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const response = await adminApi.listUsers({
        limit: pagination.limit,
        offset: pagination.offset,
        search: search || undefined,
      });
      if (response.success && response.data) {
        setUsers(response.data.items);
        setPagination((p) => ({ ...p, total: response.data!.total }));
      }
    } catch {
      console.error("Failed to fetch users");
    } finally {
      setLoading(false);
    }
  }, [pagination.limit, pagination.offset, search]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSelectAll = () => {
    if (selectedUsers.size === users.length) {
      setSelectedUsers(new Set());
    } else {
      setSelectedUsers(new Set(users.map((u) => u.id)));
    }
  };

  const handleSelect = (userId: string) => {
    const newSelected = new Set(selectedUsers);
    if (newSelected.has(userId)) {
      newSelected.delete(userId);
    } else {
      newSelected.add(userId);
    }
    setSelectedUsers(newSelected);
  };

  const handleDeleteConfirmed = async (userId: string) => {
    try {
      setDeletingUserId(userId);
      const response = await adminApi.deleteUser(userId);
      if (response.success) {
        toast.success(`User deleted (${response.data?.documents_deleted || 0} documents removed)`);
        fetchUsers();
        setSelectedUsers(new Set());
      } else {
        toast.error(response.error?.message || "Failed to delete user");
      }
    } catch {
      toast.error("An error occurred");
    } finally {
      setDeletingUserId(null);
    }
  };

  const handleBulkDeleteConfirmed = async () => {
    if (selectedUsers.size === 0) return;
    setDeleting(true);
    try {
      const response = await adminApi.bulkDeleteUsers(Array.from(selectedUsers));
      if (response.success && response.data) {
        toast.success(`Deleted ${response.data.deleted_count} users`);
        if (response.data.failed_ids.length > 0) {
          toast.error(`Failed to delete ${response.data.failed_ids.length} users`);
        }
        fetchUsers();
        setSelectedUsers(new Set());
      }
    } catch {
      toast.error("An error occurred");
    } finally {
      setDeleting(false);
    }
  };

  const handleEdit = (user: UserListItem) => {
    setEditingUser(user);
    setShowModal("edit");
  };

  const handleModalClose = () => {
    setShowModal(null);
    setEditingUser(null);
  };

  const handleModalSave = () => {
    handleModalClose();
    fetchUsers();
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Users</h1>
          <p className="text-text-secondary text-sm font-mono">{pagination.total} total users</p>
        </div>
        <button
          onClick={() => setShowModal("create")}
          className="px-4 py-2 bg-accent-purple text-white rounded-md hover:bg-purple-600 transition-colors text-sm"
        >
          + Create User
        </button>
      </div>

      {/* Search & Actions Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1">
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPagination((p) => ({ ...p, offset: 0 }));
            }}
            placeholder="Search by email or name..."
            className="w-full px-3 py-2 bg-bg-surface border border-border-muted rounded-md text-text-primary placeholder:text-text-secondary focus:border-accent-purple focus:outline-none font-mono text-sm"
          />
        </div>
        {selectedUsers.size > 0 && (
          <button
            onClick={() => setConfirmBulkDeleteOpen(true)}
            disabled={deleting}
            className="px-4 py-2 bg-accent-rose text-white rounded-md hover:bg-red-600 disabled:opacity-50 transition-colors text-sm"
          >
            {deleting ? "Deleting..." : `Delete ${selectedUsers.size} Selected`}
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
                    checked={selectedUsers.size === users.length && users.length > 0}
                    onChange={handleSelectAll}
                    className="rounded border-border-muted"
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider">
                  User
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider hidden md:table-cell">
                  Model
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider hidden lg:table-cell">
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
                    <td className="px-4 py-3 hidden md:table-cell"><div className="h-4 bg-bg-elevated rounded w-20"></div></td>
                    <td className="px-4 py-3 hidden lg:table-cell"><div className="h-4 bg-bg-elevated rounded w-24"></div></td>
                    <td className="px-4 py-3"><div className="h-4 bg-bg-elevated rounded w-20 ml-auto"></div></td>
                  </tr>
                ))
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-text-secondary">
                    No users found
                  </td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id} className="hover:bg-bg-elevated/50">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedUsers.has(user.id)}
                        onChange={() => handleSelect(user.id)}
                        className="rounded border-border-muted"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setViewingUserId(user.id)}
                        className="text-left hover:underline"
                      >
                        <p className="text-text-primary font-medium">{user.full_name}</p>
                        <p className="text-text-secondary text-xs font-mono">{user.email}</p>
                      </button>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <span className="text-text-secondary font-mono text-xs">
                        {user.preferred_model || "default"}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <span className="text-text-secondary font-mono text-xs">
                        {user.created_at ? new Date(user.created_at).toLocaleDateString() : "-"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => handleEdit(user)}
                          className="px-2 py-1 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => {
                            if (currentUserId && user.id === currentUserId) {
                              toast.error(
                                "You can't delete the account you're currently logged in as",
                              );
                              return;
                            }
                            setConfirmDelete({
                              userId: user.id,
                              email: user.email,
                              fullName: user.full_name,
                            });
                          }}
                          disabled={!!currentUserId && user.id === currentUserId}
                          title={
                            !!currentUserId && user.id === currentUserId
                              ? "You can't delete the account you're currently logged in as"
                              : undefined
                          }
                          className="px-2 py-1 text-xs text-accent-rose hover:bg-accent-rose/10 rounded transition-colors disabled:opacity-50 disabled:pointer-events-none"
                        >
                          {deletingUserId === user.id ? "Deleting..." : "Delete"}
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

      {/* Modals */}
      {showModal && (
        <UserModal
          user={showModal === "edit" ? editingUser : null}
          onClose={handleModalClose}
          onSave={handleModalSave}
        />
      )}

      {viewingUserId && (
        <UserDetailModal userId={viewingUserId} onClose={() => setViewingUserId(null)} />
      )}

      {/* Confirm single-user delete (avoid window.confirm which can be blocked by the browser) */}
      <Modal
        isOpen={!!confirmDelete}
        onClose={() => {
          if (deletingUserId) return;
          setConfirmDelete(null);
        }}
        title="Delete User"
        size="md"
        footer={
          <>
            <button
              onClick={() => setConfirmDelete(null)}
              disabled={!!deletingUserId}
              className="px-4 py-2 text-sm bg-bg-elevated text-text-primary rounded-md disabled:opacity-50 hover:bg-bg-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (!confirmDelete) return;
                void handleDeleteConfirmed(confirmDelete.userId).finally(() => {
                  setConfirmDelete(null);
                });
              }}
              disabled={!!deletingUserId}
              className="px-4 py-2 text-sm bg-accent-rose text-white rounded-md disabled:opacity-50 hover:bg-red-600 transition-colors"
            >
              {deletingUserId ? "Deleting..." : "Delete"}
            </button>
          </>
        }
      >
        <p className="text-text-secondary text-sm">
          This will permanently delete{" "}
          <span className="text-text-primary font-medium">
            {confirmDelete?.fullName || "this user"}
          </span>{" "}
          ({confirmDelete?.email}) and all their data. This action cannot be undone.
        </p>
      </Modal>

      {/* Confirm bulk delete */}
      <Modal
        isOpen={confirmBulkDeleteOpen}
        onClose={() => {
          if (deleting) return;
          setConfirmBulkDeleteOpen(false);
        }}
        title="Delete Users"
        size="md"
        footer={
          <>
            <button
              onClick={() => setConfirmBulkDeleteOpen(false)}
              disabled={deleting}
              className="px-4 py-2 text-sm bg-bg-elevated text-text-primary rounded-md disabled:opacity-50 hover:bg-bg-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                void handleBulkDeleteConfirmed().finally(() => {
                  setConfirmBulkDeleteOpen(false);
                });
              }}
              disabled={deleting}
              className="px-4 py-2 text-sm bg-accent-rose text-white rounded-md disabled:opacity-50 hover:bg-red-600 transition-colors"
            >
              {deleting ? "Deleting..." : `Delete ${selectedUsers.size}`}
            </button>
          </>
        }
      >
        <p className="text-text-secondary text-sm">
          This will permanently delete{" "}
          <span className="text-text-primary font-medium">
            {selectedUsers.size} {selectedUsers.size === 1 ? "user" : "users"}
          </span>{" "}
          and all their data. This action cannot be undone.
        </p>
      </Modal>
    </div>
  );
}

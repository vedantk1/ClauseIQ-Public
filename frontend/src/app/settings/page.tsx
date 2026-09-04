"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { useAuthRedirect } from "@/hooks/useAuthRedirect";
import Card from "@/components/Card";
import Button from "@/components/Button";
import ThemeToggle from "@/components/ThemeToggle";
import toast from "@/lib/toast";
import { adminApi } from "@/lib/adminApi";
import apiClient from "@/lib/api";
import { Eye, EyeOff, Lock } from "lucide-react";
import ConfirmModal from "@/components/ui/ConfirmModal";

interface ApiKeyStatus {
  has_api_key: boolean;
  updated_at: string | null;
}

export default function Settings() {
  const { isAuthenticated, isLoading } = useAuthRedirect();
  const { user, currentModel, updateProfile } = useAuth();
  const [fullName, setFullName] = useState("");
  const [isUpdatingProfile, setIsUpdatingProfile] = useState(false);
  const [lastUpdateSuccess, setLastUpdateSuccess] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);

  // API Key state
  const [apiKey, setApiKey] = useState("");
  const [apiKeyStatus, setApiKeyStatus] = useState<ApiKeyStatus | null>(null);
  const [isLoadingApiKey, setIsLoadingApiKey] = useState(true);
  const [isSavingApiKey, setIsSavingApiKey] = useState(false);
  const [isDeletingApiKey, setIsDeletingApiKey] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [confirmDeleteApiKeyOpen, setConfirmDeleteApiKeyOpen] = useState(false);

  // Change Password state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);

  // Email verification state
  const [emailVerified, setEmailVerified] = useState<boolean | null>(null);
  const [isResendingVerification, setIsResendingVerification] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [passwordChangeSuccess, setPasswordChangeSuccess] = useState(false);

  // Check admin access
  useEffect(() => {
    const checkAdmin = async () => {
      if (!isAuthenticated) return;
      try {
        const response = await adminApi.checkAccess();
        setIsAdmin(response.success && response.data?.is_admin === true);
      } catch {
        setIsAdmin(false);
      }
    };
    checkAdmin();
  }, [isAuthenticated]);

  // Fetch API key status
  useEffect(() => {
    const fetchApiKeyStatus = async () => {
      if (!isAuthenticated) return;
      try {
        const response = await apiClient.get<ApiKeyStatus>(
          "/auth/api-key/status",
        );
        if (response.success && response.data) {
          setApiKeyStatus(response.data);
        }
      } catch {
        console.error("Failed to fetch API key status:");
      } finally {
        setIsLoadingApiKey(false);
      }
    };
    fetchApiKeyStatus();
  }, [isAuthenticated]);

  // Fetch email verification status
  useEffect(() => {
    const fetchVerificationStatus = async () => {
      if (!isAuthenticated) return;
      try {
        const response = await apiClient.get<{ email_verified: boolean }>(
          "/auth/verification-status",
        );
        if (response.success && response.data) {
          setEmailVerified(response.data.email_verified);
        }
      } catch {
        console.error("Failed to fetch verification status:");
      }
    };
    fetchVerificationStatus();
  }, [isAuthenticated]);

  // Initialize fullName when user data loads
  React.useEffect(() => {
    if (user?.full_name !== undefined) {
      setFullName(user.full_name);
      setLastUpdateSuccess(false);
    }
  }, [user?.full_name]);

  const handleSaveApiKey = async () => {
    if (!apiKey.trim()) {
      toast.error("Please enter an API key");
      return;
    }

    if (!apiKey.startsWith("sk-")) {
      toast.error("API key must start with 'sk-'");
      return;
    }

    setIsSavingApiKey(true);
    try {
      const response = await apiClient.put("/auth/api-key", {
        api_key: apiKey,
      });
      if (response.success) {
        toast.success("API key saved successfully");
        setApiKey("");
        setShowApiKey(false);
        // Refresh status
        const statusResponse = await apiClient.get<ApiKeyStatus>(
          "/auth/api-key/status",
        );
        if (statusResponse.success && statusResponse.data) {
          setApiKeyStatus(statusResponse.data);
        }
      } else {
        toast.error(response.error?.message || "Failed to save API key");
      }
    } catch {
      console.error("Failed to save API key:");
      toast.error("Failed to save API key");
    } finally {
      setIsSavingApiKey(false);
    }
  };

  const handleDeleteApiKey = () => {
    setConfirmDeleteApiKeyOpen(true);
  };

  const handleDeleteApiKeyConfirmed = async () => {
    setIsDeletingApiKey(true);
    try {
      const response = await apiClient.delete("/auth/api-key");
      if (response.success) {
        toast.success("API key removed successfully");
        setApiKeyStatus({ has_api_key: false, updated_at: null });
      } else {
        toast.error(response.error?.message || "Failed to remove API key");
      }
    } catch {
      console.error("Failed to delete API key:");
      toast.error("Failed to remove API key");
    } finally {
      setIsDeletingApiKey(false);
      setConfirmDeleteApiKeyOpen(false);
    }
  };

  const handleSaveProfile = async () => {

    if (!fullName.trim()) {
      toast.error("Please enter your full name");
      return;
    }

    if (fullName.trim() === user?.full_name) {
      toast.error("No changes to save");
      return;
    }

    setIsUpdatingProfile(true);
    setLastUpdateSuccess(false);
    try {
      await updateProfile(fullName.trim());
      setLastUpdateSuccess(true);
      // Reset success indicator after 3 seconds
      setTimeout(() => setLastUpdateSuccess(false), 3000);
    } catch {
      console.error("Failed to update profile:");
      toast.error("Failed to update profile");
    } finally {
      setIsUpdatingProfile(false);
    }
  };

  const handleChangePassword = async () => {
    // Validate inputs
    if (!currentPassword) {
      toast.error("Please enter your current password");
      return;
    }

    if (!newPassword) {
      toast.error("Please enter a new password");
      return;
    }

    if (newPassword.length < 8) {
      toast.error("New password must be at least 8 characters");
      return;
    }

    // Check for letters and numbers
    if (!/[A-Za-z]/.test(newPassword) || !/\d/.test(newPassword)) {
      toast.error("Password must contain both letters and numbers");
      return;
    }

    if (newPassword !== confirmPassword) {
      toast.error("New passwords do not match");
      return;
    }

    setIsChangingPassword(true);
    setPasswordChangeSuccess(false);

    try {
      const response = await apiClient.put("/auth/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });

      if (response.success) {
        toast.success("Password changed successfully");
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setPasswordChangeSuccess(true);
        // Hide success indicator after 3 seconds
        setTimeout(() => setPasswordChangeSuccess(false), 3000);
      } else {
        toast.error(response.error?.message || "Failed to change password");
      }
    } catch {
      console.error("Failed to change password:");
      toast.error("Failed to change password");
    } finally {
      setIsChangingPassword(false);
    }
  };

  // Auth loading check
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent-purple"></div>
      </div>
    );
  }

  // Don't render if not authenticated
  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-bg-primary to-bg-surface">
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-2xl mx-auto">
          <h1 className="text-3xl font-bold text-text-primary mb-8">
            Settings
          </h1>

          {/* Profile Settings Section */}
          <Card className="p-6 mb-6">
            <h2 className="text-xl font-semibold text-text-primary mb-6">
              Profile Information
            </h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Full Name
                </label>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Enter your full name"
                  className="w-full px-4 py-3 bg-bg-primary border border-border-muted rounded-lg focus:ring-2 focus:ring-accent-purple focus:border-accent-purple outline-none transition-colors text-text-primary placeholder:text-text-secondary"
                />
                <p className="text-xs text-text-secondary mt-1">
                  This name will be displayed throughout the application
                </p>
              </div>

              <div className="pt-4 border-t border-border-muted">
                <div className="flex justify-between items-center gap-4">
                  <div>
                    <p className="text-sm text-text-secondary">
                      Current name:{" "}
                      <span className="font-medium text-text-primary">
                        {user?.full_name || "Not set"}
                      </span>
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {lastUpdateSuccess && (
                      <div className="flex items-center gap-2 text-green-600 text-sm font-medium">
                        <svg
                          className="w-5 h-5"
                          fill="currentColor"
                          viewBox="0 0 20 20"
                        >
                          <path
                            fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd"
                          />
                        </svg>
                        Saved
                      </div>
                    )}
                    <Button
                      onClick={handleSaveProfile}
                      loading={isUpdatingProfile}
                      disabled={
                        !fullName.trim() || fullName.trim() === user?.full_name
                      }
                    >
                      {isUpdatingProfile ? "Updating..." : "Update Name"}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </Card>

          {/* Change Password Section */}
          <Card className="p-6 mb-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-full bg-accent-purple/10 flex items-center justify-center">
                <Lock className="w-5 h-5 text-accent-purple" />
              </div>
              <h2 className="text-xl font-semibold text-text-primary">
                Change Password
              </h2>
            </div>

            <div className="space-y-4">
              {/* Current Password */}
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Current Password
                </label>
                <div className="relative">
                  <input
                    type={showCurrentPassword ? "text" : "password"}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    placeholder="Enter your current password"
                    className="w-full px-4 py-3 pr-12 bg-bg-primary border border-border-muted rounded-lg focus:ring-2 focus:ring-accent-purple focus:border-accent-purple outline-none transition-colors text-text-primary placeholder:text-text-secondary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
                    aria-label={
                      showCurrentPassword ? "Hide password" : "Show password"
                    }
                  >
                    {showCurrentPassword ? (
                      <EyeOff className="w-5 h-5" />
                    ) : (
                      <Eye className="w-5 h-5" />
                    )}
                  </button>
                </div>
              </div>

              {/* New Password */}
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  New Password
                </label>
                <div className="relative">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Enter new password"
                    className="w-full px-4 py-3 pr-12 bg-bg-primary border border-border-muted rounded-lg focus:ring-2 focus:ring-accent-purple focus:border-accent-purple outline-none transition-colors text-text-primary placeholder:text-text-secondary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
                    aria-label={
                      showNewPassword ? "Hide password" : "Show password"
                    }
                  >
                    {showNewPassword ? (
                      <EyeOff className="w-5 h-5" />
                    ) : (
                      <Eye className="w-5 h-5" />
                    )}
                  </button>
                </div>
                <p className="text-xs text-text-secondary mt-1">
                  Must be at least 8 characters with letters and numbers
                </p>
              </div>

              {/* Confirm New Password */}
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Confirm New Password
                </label>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    className="w-full px-4 py-3 pr-12 bg-bg-primary border border-border-muted rounded-lg focus:ring-2 focus:ring-accent-purple focus:border-accent-purple outline-none transition-colors text-text-primary placeholder:text-text-secondary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
                    aria-label={
                      showConfirmPassword ? "Hide password" : "Show password"
                    }
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="w-5 h-5" />
                    ) : (
                      <Eye className="w-5 h-5" />
                    )}
                  </button>
                </div>
              </div>

              {/* Submit Button */}
              <div className="pt-4 border-t border-border-muted">
                <div className="flex justify-end items-center gap-3">
                  {passwordChangeSuccess && (
                    <div className="flex items-center gap-2 text-green-600 text-sm font-medium">
                      <svg
                        className="w-5 h-5"
                        fill="currentColor"
                        viewBox="0 0 20 20"
                      >
                        <path
                          fillRule="evenodd"
                          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                          clipRule="evenodd"
                        />
                      </svg>
                      Password Changed
                    </div>
                  )}
                  <Button
                    onClick={handleChangePassword}
                    loading={isChangingPassword}
                    disabled={
                      !currentPassword || !newPassword || !confirmPassword
                    }
                  >
                    {isChangingPassword ? "Changing..." : "Change Password"}
                  </Button>
                </div>
              </div>
            </div>
          </Card>

          {/* Theme Preferences Section */}
          <Card className="p-6 mb-6">
            <h2 className="text-xl font-semibold text-text-primary mb-6">
              Appearance
            </h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-text-primary mb-3">
                  Theme Preference
                </label>
                <div className="flex items-center justify-between p-4 bg-bg-surface rounded-lg border border-border-muted">
                  <div>
                    <p className="text-sm font-medium text-text-primary">
                      Choose your preferred theme
                    </p>
                    <p className="text-xs text-text-secondary mt-1">
                      Toggle between light and dark modes for optimal viewing
                      experience
                    </p>
                  </div>
                  <ThemeToggle size="md" showLabel />
                </div>
              </div>
            </div>
          </Card>

          <Card className="p-6">
            <h2 className="text-xl font-semibold text-text-primary mb-6">
              AI Model
            </h2>

            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-bg-surface rounded-lg border border-border-muted">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-accent-purple/10 flex items-center justify-center">
                    <span className="text-accent-purple text-lg">🤖</span>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-text-primary">
                      {currentModel?.name || "Loading..."}
                    </p>
                    <p className="text-xs text-text-secondary mt-0.5">
                      {currentModel?.description ||
                        "Fetching model configuration..."}
                    </p>
                  </div>
                </div>
                <div className="px-3 py-1 bg-accent-purple/10 text-accent-purple text-xs font-medium rounded-full">
                  Active
                </div>
              </div>

              <div className="p-4 bg-bg-primary rounded-lg border border-border-muted">
                <div className="flex items-start gap-2">
                  <span className="text-text-secondary">ℹ️</span>
                  <div className="text-sm text-text-secondary">
                    <p>
                      ClauseIQ uses{" "}
                      {currentModel?.name || "the configured AI model"} for all
                      contract analysis. This model is configured by your
                      administrator for optimal balance of speed, accuracy, and
                      comprehensive legal insights.
                    </p>
                    <p className="mt-2 text-xs">
                      To use your own OpenAI API key, you can configure it in
                      the API Settings section below.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </Card>

          {/* API Key Settings Section */}
          <Card className="p-6 mt-6">
            <h2 className="text-xl font-semibold text-text-primary mb-6">
              API Settings
            </h2>

            {emailVerified === false && (
              <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                <div className="flex items-start gap-3">
                  <span className="text-amber-500 text-lg mt-0.5">⚠️</span>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                      Email verification required
                    </p>
                    <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                      Please verify your email address before adding an API key.
                      Check your inbox for a verification email.
                    </p>
                    <button
                      onClick={async () => {
                        setIsResendingVerification(true);
                        try {
                          const response = await apiClient.post(
                            "/auth/resend-verification",
                          );
                          if (response.success) {
                            toast.success(
                              "Verification email sent! Check your inbox.",
                            );
                          } else {
                            toast.error(
                              response.error?.message ||
                                "Failed to send verification email",
                            );
                          }
                        } catch {
                          toast.error("Failed to send verification email");
                        } finally {
                          setIsResendingVerification(false);
                        }
                      }}
                      disabled={isResendingVerification}
                      className="mt-2 text-sm font-medium text-accent-purple hover:text-accent-purple/80 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isResendingVerification
                        ? "Sending..."
                        : "Resend verification email"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div
              className={`space-y-4 ${emailVerified === false ? "opacity-50 pointer-events-none" : ""}`}
            >
              {isLoadingApiKey ? (
                <div className="flex items-center gap-2 text-text-secondary">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-accent-purple"></div>
                  <span className="text-sm">Loading API key status...</span>
                </div>
              ) : apiKeyStatus?.has_api_key ? (
                // API key is set - show status and delete option
                <div className="space-y-4">
                  <div className="flex items-center justify-between p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-green-100 dark:bg-green-900/50 flex items-center justify-center">
                        <span className="text-green-600 dark:text-green-400 text-lg">
                          🔑
                        </span>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-text-primary">
                          Your OpenAI API Key
                        </p>
                        <p className="text-xs text-text-secondary mt-0.5">
                          {apiKeyStatus.updated_at
                            ? `Last updated: ${new Date(apiKeyStatus.updated_at).toLocaleDateString()}`
                            : "API key is configured"}
                        </p>
                      </div>
                    </div>
                    <div className="px-3 py-1 bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-400 text-xs font-medium rounded-full">
                      Active
                    </div>
                  </div>

                  <div className="flex flex-col sm:flex-row gap-3">
                    <div className="flex-1 relative">
                      <input
                        type={showApiKey ? "text" : "password"}
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder="Enter new API key to replace..."
                        className="w-full px-4 py-3 pr-12 bg-bg-primary border border-border-muted rounded-lg focus:ring-2 focus:ring-accent-purple focus:border-accent-purple outline-none transition-colors text-text-primary placeholder:text-text-secondary"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary"
                      >
                        {showApiKey ? "🙈" : "👁️"}
                      </button>
                    </div>
                    <Button
                      onClick={handleSaveApiKey}
                      loading={isSavingApiKey}
                      disabled={!apiKey.trim()}
                    >
                      Update Key
                    </Button>
                  </div>

                  <div className="pt-4 border-t border-border-muted">
                    <button
                      onClick={handleDeleteApiKey}
                      disabled={isDeletingApiKey}
                      className="text-sm text-red-500 hover:text-red-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isDeletingApiKey ? "Removing..." : "Remove API key"}
                    </button>
                  </div>
                </div>
              ) : (
                // No API key set - show input to add one
                <div className="space-y-4">
                  <div className="flex items-center justify-between p-4 bg-bg-surface rounded-lg border border-border-muted">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
                        <span className="text-text-secondary text-lg">🔑</span>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-text-primary">
                          OpenAI API Key
                        </p>
                        <p className="text-xs text-text-secondary mt-0.5">
                          Required for document analysis
                        </p>
                      </div>
                    </div>
                    <div className="px-3 py-1 bg-gray-100 dark:bg-gray-800 text-text-secondary text-xs font-medium rounded-full">
                      Not Set
                    </div>
                  </div>

                  <div className="flex flex-col sm:flex-row gap-3">
                    <div className="flex-1 relative">
                      <input
                        type={showApiKey ? "text" : "password"}
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder="sk-..."
                        className="w-full px-4 py-3 pr-12 bg-bg-primary border border-border-muted rounded-lg focus:ring-2 focus:ring-accent-purple focus:border-accent-purple outline-none transition-colors text-text-primary placeholder:text-text-secondary"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary"
                      >
                        {showApiKey ? "🙈" : "👁️"}
                      </button>
                    </div>
                    <Button
                      onClick={handleSaveApiKey}
                      loading={isSavingApiKey}
                      disabled={!apiKey.trim()}
                    >
                      Save Key
                    </Button>
                  </div>

                  <div className="p-4 bg-bg-primary rounded-lg border border-border-muted">
                    <div className="flex items-start gap-2">
                      <span className="text-text-secondary">ℹ️</span>
                      <div className="text-sm text-text-secondary">
                        <p>
                          By adding your own OpenAI API key, your document
                          analyses will be billed directly to your OpenAI
                          account. Your key is encrypted and stored securely.
                        </p>
                        <p className="mt-2 text-xs">
                          Get your API key from{" "}
                          <a
                            href="https://platform.openai.com/api-keys"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-accent-purple hover:underline"
                          >
                            platform.openai.com/api-keys
                          </a>
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* Admin Section - Only visible to admins */}
          {isAdmin && (
            <Card className="p-6 mt-6">
              <h2 className="text-xl font-semibold text-text-primary mb-4">
                Administration
              </h2>
              <div className="space-y-3">
                <p className="text-sm text-text-secondary">
                  You have administrator access. Use the admin portal to manage
                  users, documents, and system settings.
                </p>
                <Link
                  href="/admin"
                  className="inline-flex items-center gap-2 px-4 py-2 bg-accent-purple text-white rounded-md hover:bg-purple-600 transition-colors text-sm"
                >
                  <span>⚙️</span>
                  Open Admin Portal
                </Link>
              </div>
            </Card>
          )}

          <ConfirmModal
            isOpen={confirmDeleteApiKeyOpen}
            title="Remove API Key"
            message={
              isDeletingApiKey ? (
                <>Removing your API key... Please wait.</>
              ) : (
                <>
                  Are you sure you want to remove your API key? You will not be
                  able to analyze documents or use chat features until you add a
                  new key.
                </>
              )
            }
            confirmText={isDeletingApiKey ? "Removing..." : "Remove"}
            confirmVariant="danger"
            loading={isDeletingApiKey}
            onClose={() => {
              if (isDeletingApiKey) return;
              setConfirmDeleteApiKeyOpen(false);
            }}
            onConfirm={() => {
              void handleDeleteApiKeyConfirmed();
            }}
          />
        </div>
      </div>
    </div>
  );
}

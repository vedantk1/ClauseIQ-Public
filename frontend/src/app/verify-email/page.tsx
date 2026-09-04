"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api";

function VerifyEmailContent() {
  const [isLoading, setIsLoading] = useState(true);
  const [isSuccess, setIsSuccess] = useState(false);
  const [error, setError] = useState("");
  const searchParams = useSearchParams();

  useEffect(() => {
    const token = searchParams.get("token");

    if (!token) {
      setError("Invalid verification link. No token provided.");
      setIsLoading(false);
      return;
    }

    const verifyEmail = async () => {
      try {
        const response = await fetch(
          `${getApiBaseUrl()}/api/v1/auth/verify-email`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ token }),
          },
        );

        const data = await response.json();

        if (response.ok && data.success) {
          setIsSuccess(true);
        } else {
          setError(
            data.error?.message ||
              "Email verification failed. The link may have expired.",
          );
        }
      } catch {
        setError("Network error. Please check your connection and try again.");
      } finally {
        setIsLoading(false);
      }
    };

    verifyEmail();
  }, [searchParams]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md mx-auto">
          <div className="bg-bg-surface rounded-lg border border-border-muted p-8 shadow-lg text-center">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-accent-purple/10 flex items-center justify-center">
              <Loader2 className="w-8 h-8 text-accent-purple animate-spin" />
            </div>
            <h2 className="text-2xl font-heading font-bold text-text-primary mb-4">
              Verifying Your Email
            </h2>
            <p className="text-text-secondary">
              Please wait while we verify your email address...
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (isSuccess) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md mx-auto">
          <div className="bg-bg-surface rounded-lg border border-border-muted p-8 shadow-lg text-center">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-accent-green/10 flex items-center justify-center">
              <CheckCircle className="w-8 h-8 text-accent-green" />
            </div>

            <h2 className="text-2xl font-heading font-bold text-text-primary mb-4">
              Email Verified!
            </h2>

            <p className="text-text-secondary mb-6">
              Your email has been verified successfully. You can now add your
              API key and access all features.
            </p>

            <Link
              href="/settings"
              className="inline-flex items-center justify-center px-6 py-3 bg-accent-purple text-white rounded-lg hover:bg-purple-600 transition-colors font-medium"
            >
              Go to Settings
            </Link>

            <div className="mt-4">
              <Link
                href="/"
                className="text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                or go to Dashboard
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md mx-auto">
        <div className="bg-bg-surface rounded-lg border border-border-muted p-8 shadow-lg text-center">
          <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-red-50 dark:bg-red-900/20 flex items-center justify-center">
            <AlertCircle className="w-8 h-8 text-red-500" />
          </div>

          <h2 className="text-2xl font-heading font-bold text-text-primary mb-4">
            Verification Failed
          </h2>

          <p className="text-text-secondary mb-6">{error}</p>

          <div className="space-y-3">
            <Link
              href="/login"
              className="inline-flex items-center justify-center w-full px-6 py-3 bg-accent-purple text-white rounded-lg hover:bg-purple-600 transition-colors font-medium"
            >
              Go to Login
            </Link>
            <p className="text-xs text-text-secondary">
              You can resend the verification email from your Settings page
              after logging in.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent-purple"></div>
        </div>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  );
}

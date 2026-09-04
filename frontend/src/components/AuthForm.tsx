"use client";
import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button, Input } from "@/components/ui";
import Card from "@/components/Card";
import { Mail, Lock, User, Eye, EyeOff } from "lucide-react";

interface AuthFormProps {
  mode: "login" | "register";
  onToggleMode: () => void;
  onSuccess?: () => void;
}

export default function AuthForm({
  mode,
  onToggleMode,
  onSuccess,
}: AuthFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const { login, register } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();


    setIsLoading(true);

    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, fullName);
      }
      onSuccess?.();
    } catch {
      console.error("Authentication attempt failed");
      // Error handling is done in the context with toast
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-md mx-auto">
      <Card className="p-8">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-heading font-bold text-text-primary mb-2">
            {mode === "login" ? "Welcome Back" : "Create Account"}
          </h2>
          <p className="text-text-secondary">
            {mode === "login"
              ? "Sign in to your ClauseIQ account"
              : "Sign up to get started with ClauseIQ"}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {mode === "register" && (
            <Input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(value) => setFullName(value)}
              required
              label="Full Name"
              placeholder="Enter your full name"
              leftIcon={<User className="h-4 w-4" />}
              size="lg"
            />
          )}

          <Input
            id="email"
            type="email"
            value={email}
            onChange={(value) => setEmail(value)}
            required
            label="Email Address"
            placeholder="Enter your email"
            leftIcon={<Mail className="h-4 w-4" />}
            size="lg"
          />

          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(value) => setPassword(value)}
            required
            minLength={8}
            label="Password"
            placeholder="Enter your password"
            leftIcon={<Lock className="h-4 w-4" />}
            rightIcon={
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="text-text-secondary hover:text-text-primary transition-colors"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            }
            size="lg"
            helpText={
              mode === "register"
                ? "Password must be at least 8 characters long"
                : undefined
            }
          />

          {mode === "login" && (
            <div className="text-right">
              <a
                href="/forgot-password"
                className="text-sm text-accent-purple hover:text-accent-purple/80 font-medium transition-colors focus:outline-none focus:underline"
              >
                Forgot Password?
              </a>
            </div>
          )}

          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={isLoading}
            isLoading={isLoading}
            className="w-full"
          >
            {mode === "login" ? "Sign In" : "Create Account"}
          </Button>
        </form>

        <div className="mt-6 text-center">
          <p className="text-text-secondary">
            {mode === "login"
              ? "Don't have an account?"
              : "Already have an account?"}{" "}
            <button
              type="button"
              onClick={onToggleMode}
              className="text-accent-purple hover:text-accent-purple/80 font-medium transition-colors focus:outline-none focus:underline"
            >
              {mode === "login" ? "Sign up" : "Sign in"}
            </button>
          </p>
        </div>
      </Card>
    </div>
  );
}

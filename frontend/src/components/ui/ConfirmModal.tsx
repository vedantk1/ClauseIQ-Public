"use client";

import React from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/Button";

type ConfirmVariant = "primary" | "danger";

export interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  confirmVariant?: ConfirmVariant;
  showCancel?: boolean;
  loading?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  confirmVariant = "primary",
  showCancel = true,
  loading = false,
  onClose,
  onConfirm,
}: ConfirmModalProps) {
  const confirmButtonVariant = confirmVariant === "danger" ? "danger" : "primary";

  return (
    <Modal isOpen={isOpen} onClose={loading ? () => {} : onClose} title={title} size="md">
      <div className="space-y-6">
        <div className="text-text-secondary">{message}</div>
        <div className="flex gap-3">
          {showCancel && (
            <Button
              onClick={onClose}
              variant="secondary"
              className="flex-1"
              disabled={loading}
            >
              {loading ? "Please wait..." : cancelText}
            </Button>
          )}
          <Button
            onClick={onConfirm}
            variant={confirmButtonVariant}
            className="flex-1"
            loading={loading}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * Modal component with overlay and focus management
 */
"use client";

import React, { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import { isTopModal, mountModal } from "./modalFocus";

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  children: React.ReactNode;
  title?: string;
  size?: "sm" | "md" | "lg" | "xl" | "full";
  closeOnOverlayClick?: boolean;
  closeOnEscapeKey?: boolean;
  showCloseButton?: boolean;
  className?: string;
  footer?: React.ReactNode;
  placement?: "center" | "right";
}

const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  children,
  title,
  size = "md",
  closeOnOverlayClick = true,
  closeOnEscapeKey = true,
  showCloseButton = true,
  className,
  footer,
  placement = "center",
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const dismissal = useRef({ onClose, closeOnEscapeKey });
  dismissal.current = { onClose, closeOnEscapeKey };

  // Register only open dialogs. Inline callback changes must not reset focus or scroll locks.
  useEffect(() => {
    if (!isOpen || !modalRef.current) return;
    return mountModal(modalRef.current, () => {
      if (dismissal.current.closeOnEscapeKey) dismissal.current.onClose();
    });
  }, [isOpen]);

  // Handle overlay click
  const handleOverlayClick = (event: React.MouseEvent) => {
    if (closeOnOverlayClick && event.target === overlayRef.current && isTopModal(modalRef.current)) {
      onClose();
    }
  };

  if (!isOpen) {
    return null;
  }

  const sizeClasses = {
    sm: "max-w-md",
    md: "max-w-lg",
    lg: "max-w-2xl",
    xl: "max-w-4xl",
    full: "max-w-full mx-4",
  };

  const modalContent = (
    <div
      ref={overlayRef}
      className={cn("fixed inset-0 z-50 flex bg-black/50 backdrop-blur-sm", placement === "right" ? "items-stretch justify-end" : "items-center justify-center p-4")}
      onClick={handleOverlayClick}
      data-testid="modal-backdrop"
    >
      <div
        ref={modalRef}
        className={cn(
          "relative w-full bg-bg-surface rounded-lg border border-border-muted shadow-lg focus:outline-none",
          sizeClasses[size],
          className,
          placement === "right" && "h-full overflow-y-auto rounded-none"
        )}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
      >
        {(title || showCloseButton) && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-muted">
            {title && (
              <h2
                id={titleId}
                className="text-lg font-semibold text-text-primary"
              >
                {title}
              </h2>
            )}
            {showCloseButton && (
              <button
                onClick={onClose}
                className="p-1 text-text-secondary hover:text-text-primary transition-colors rounded-md hover:bg-surface-secondary"
                aria-label="Close modal"
              >
                <X className="h-5 w-5" />
              </button>
            )}
          </div>
        )}
        <div
          className={cn(
            "px-6 pb-6",
            title || showCloseButton ? "pt-6" : "pt-6"
          )}
        >
          {children}
        </div>
        {footer && (
          <div className="flex items-center justify-end gap-3 p-6 border-t border-border-muted">
            {footer}
          </div>
        )}
      </div>
    </div>
  );

  // Render modal in portal
  return createPortal(modalContent, document.body);
};

export { Modal };
export default Modal;

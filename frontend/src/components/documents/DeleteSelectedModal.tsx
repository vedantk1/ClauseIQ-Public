/**
 * Delete selected documents confirmation modal (bulk delete)
 */

import Modal from "@/components/ui/Modal";
import Button from "@/components/Button";

interface DeleteSelectedModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  selectedCount: number;
  deleting?: boolean;
}

export const DeleteSelectedModal = ({
  isOpen,
  onClose,
  onConfirm,
  selectedCount,
  deleting = false,
}: DeleteSelectedModalProps) => {
  return (
    <Modal
      isOpen={isOpen}
      onClose={deleting ? () => {} : onClose}
      title="Delete Selected"
      size="md"
    >
      <div className="space-y-6">
        <p className="text-text-secondary">
          {deleting ? (
            <>
              Deleting{" "}
              <span className="font-medium text-text-primary">
                {selectedCount} {selectedCount === 1 ? "document" : "documents"}
              </span>
              ... Please wait.
            </>
          ) : (
            <>
              Are you sure you want to delete{" "}
              <span className="font-medium text-text-primary">
                {selectedCount} {selectedCount === 1 ? "document" : "documents"}
              </span>
              ? This action cannot be undone.
            </>
          )}
        </p>
        <div className="flex gap-3">
          <Button
            onClick={onClose}
            variant="secondary"
            className="flex-1"
            disabled={deleting}
          >
            {deleting ? "Please wait..." : "Cancel"}
          </Button>
          <Button
            onClick={onConfirm}
            variant="danger"
            className="flex-1"
            disabled={deleting}
          >
            {deleting ? (
              <div className="flex items-center justify-center">
                <svg
                  className="animate-spin -ml-1 mr-3 h-4 w-4 text-white"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  ></circle>
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  ></path>
                </svg>
                Deleting...
              </div>
            ) : (
              `Delete ${selectedCount}`
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

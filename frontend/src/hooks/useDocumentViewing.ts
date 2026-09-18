import { useCallback } from 'react';
import config from '@/config/config';
import { LOCAL_API_HEADERS } from '@/lib/api';

/**
 * Hook for tracking document views and managing last viewed timestamps
 */
export function useDocumentViewing() {
  /**
   * Track that a document has been viewed by sending a request to the backend
   */
  const trackDocumentView = useCallback(async (documentId: string): Promise<boolean> => {
    try {
      const response = await fetch(
        `${config.apiUrl}/api/v1/documents/${documentId}/view`,
        {
          method: 'POST',
          headers: {
            ...LOCAL_API_HEADERS,
            'Content-Type': 'application/json',
          },
        }
      );

      if (!response.ok) {
        console.error("Failed to track document view");
        return false;
      }

      const result = await response.json();

      if (result.success) {
        return true;
      } else {
        console.error("View tracking failed:");
        return false;
      }
    } catch {
      console.error("Error tracking document view:");
      return false;
    }
  }, []);

  /**
   * Format a last viewed timestamp into a human-readable relative time
   */
  const formatLastViewed = useCallback((lastViewedTimestamp: string | null | undefined): string => {
    if (!lastViewedTimestamp) {
      return 'Never';
    }

    try {
      const lastViewed = new Date(lastViewedTimestamp);
      const now = new Date();

      // Validate the date
      if (isNaN(lastViewed.getTime())) {
        return 'Unknown';
      }

      const diffMs = now.getTime() - lastViewed.getTime();
      const diffMins = Math.floor(diffMs / (1000 * 60));
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      // If in the future (shouldn't happen), show "Just now"
      if (diffMs < 0) {
        return 'Just now';
      }

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
      if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;

      return lastViewed.toLocaleDateString();
    } catch {
      console.error("Error formatting last viewed timestamp:");
      return 'Unknown';
    }
  }, []);

  return {
    trackDocumentView,
    formatLastViewed,
  };
}

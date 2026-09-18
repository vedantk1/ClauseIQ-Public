/**
 * Toast utility that respects workspace settings.
 * Wraps react-hot-toast to conditionally show/hide notifications.
 */

import { toast as hotToast } from "react-hot-toast";
import { getApiBaseUrl, LOCAL_API_HEADERS } from "@/lib/api";

// Cache for the toast setting to avoid repeated API calls
let toastEnabledCache: boolean | null = null;
let cacheTimestamp: number = 0;
const CACHE_TTL = 60000; // 1 minute cache

/**
 * Fetch the toast notification setting from the server.
 * Caches the result to avoid repeated API calls.
 */
async function isToastEnabled(): Promise<boolean> {
  const now = Date.now();

  // Return cached value if still valid
  if (toastEnabledCache !== null && now - cacheTimestamp < CACHE_TTL) {
    return toastEnabledCache;
  }

  try {
    const apiUrl = getApiBaseUrl();
    const response = await fetch(`${apiUrl}/api/v1/app-config`, { headers: LOCAL_API_HEADERS });
    const data = await response.json();

    if (data.success && data.data) {
      toastEnabledCache = data.data.toast_notifications_enabled ?? true;
      cacheTimestamp = now;
      return toastEnabledCache === true;
    }
  } catch {
    console.error("Failed to fetch toast settings");
  }

  // Default to enabled if fetch fails
  return true;
}

/**
 * Clear the toast cache (call when settings change)
 */
export function clearToastCache(): void {
  toastEnabledCache = null;
  cacheTimestamp = 0;
}

/**
 * Toast wrapper that respects workspace settings.
 * Falls back to showing toasts if setting can't be fetched.
 */
export const toast = {
  success: async (message: string, options?: Parameters<typeof hotToast.success>[1]) => {
    if (await isToastEnabled()) {
      return hotToast.success(message, options);
    }
    return null;
  },

  error: async (message: string, options?: Parameters<typeof hotToast.error>[1]) => {
    if (await isToastEnabled()) {
      return hotToast.error(message, options);
    }
    return null;
  },

  loading: async (message: string, options?: Parameters<typeof hotToast.loading>[1]) => {
    if (await isToastEnabled()) {
      return hotToast.loading(message, options);
    }
    return null;
  },

  custom: async (message: Parameters<typeof hotToast.custom>[0], options?: Parameters<typeof hotToast.custom>[1]) => {
    if (await isToastEnabled()) {
      return hotToast.custom(message, options);
    }
    return null;
  },

  dismiss: hotToast.dismiss,
  remove: hotToast.remove,
};

export default toast;

/**
 * sessionStorage.ts provides failure-tolerant access to optional, tab-scoped
 * navigation state without ever persisting user messages or interpretations.
 */

/**
 * Read one optional value from the current tab's session storage.
 *
 * Args:
 *   key: The storage key to read.
 *
 * Returns:
 *   The stored value, or null when storage is unavailable or access is denied.
 */
export function readSessionStorage(key: string): string | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    return window.sessionStorage.getItem(key)
  } catch {
    // Privacy settings can disable storage; optional persistence must not break the app.
    return null
  }
}

/**
 * Store one optional value for the lifetime of the current browser tab.
 *
 * Args:
 *   key: The storage key to write.
 *   value: The non-sensitive value to store.
 *
 * Returns:
 *   Nothing. Storage failures are deliberately ignored.
 */
export function writeSessionStorage(key: string, value: string): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    // The interface remains usable without optional navigation persistence.
  }
}

/**
 * Remove one optional value from the current tab's session storage.
 *
 * Args:
 *   key: The storage key to remove.
 *
 * Returns:
 *   Nothing. No further action is needed when storage is unavailable.
 */
export function removeSessionStorage(key: string): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    window.sessionStorage.removeItem(key)
  } catch {
    // There is no required fallback for optional client-side state.
  }
}

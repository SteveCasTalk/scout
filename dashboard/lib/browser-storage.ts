/** Migrate saved workspace/live-session selections from the previous brand. */
export function readStoredItem(storage: Storage, key: string): string | null {
  const current = storage.getItem(key);
  if (current !== null) return current;
  const legacyKey = key.replace(/^scout-/, 'jev-');
  if (legacyKey === key) return null;
  const previous = storage.getItem(legacyKey);
  if (previous !== null) {
    storage.setItem(key, previous);
    storage.removeItem(legacyKey);
  }
  return previous;
}

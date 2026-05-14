/**
 * Optimistic-mutation pattern. Apply the local change immediately so the UI
 * stays responsive; if the backend call rejects, undo it and re-throw so the
 * caller can surface the error.
 */
export async function withRollback<T>(
  applyLocal: () => void,
  rollback: () => void,
  apiCall: () => Promise<T>,
): Promise<T> {
  applyLocal();
  try {
    return await apiCall();
  } catch (e) {
    rollback();
    throw e;
  }
}

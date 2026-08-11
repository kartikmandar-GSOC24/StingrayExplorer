import { useQuery } from '@tanstack/react-query';
import { dataApi, EventListSummary } from '@/api/dataApi';

export const EVENT_LISTS_QUERY_KEY = ['eventLists'] as const;

/**
 * Loaded event lists from the backend. The ApiClient re-resolves the backend
 * port on every request, so this works without gating on backend readiness;
 * failures surface as query errors with a retry affordance in the UI.
 */
export function useEventLists() {
  return useQuery({
    queryKey: EVENT_LISTS_QUERY_KEY,
    queryFn: async (): Promise<EventListSummary[]> => {
      const res = await dataApi.listEventLists();
      if (!res.success) {
        throw new Error(res.error || res.message || 'Failed to list event lists');
      }
      return res.data ?? [];
    },
    staleTime: 5_000,
  });
}

import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/timeline';

async function req<T>(path: string): Promise<T> {
  const resp = await authedFetch(`${BASE}${path}`);
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((j as any).detail || `Request failed (${resp.status})`);
  return j as T;
}

export type EventCategory = 'idea' | 'feature' | 'run' | 'research';

export interface TimelineEvent {
  id: string;
  type: string;
  category: EventCategory;
  title: string;
  timestamp: string;
  route: string;
}

export interface TimelinePage {
  events: TimelineEvent[];
  next_cursor: string | null;
}

export const timelineApi = {
  list: (projectId: string, category?: EventCategory, cursor?: string, limit = 30) => {
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    if (cursor) params.set('cursor', cursor);
    params.set('limit', String(limit));
    return req<TimelinePage>(`/project/${projectId}?${params.toString()}`);
  },
};

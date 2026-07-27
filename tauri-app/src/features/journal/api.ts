import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await authedFetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((j as any).detail || `Request failed (${resp.status})`);
  return j as T;
}

export interface JournalEntry {
  id: string;
  entry_date: string;
  kind: string;
  title: string;
  body: string;
  highlights: string[];
  auto_drafted: boolean;
}

export interface Draft {
  entry_date: string;
  title: string;
  body: string;
  highlights: string[];
  event_count: number;
  saved: boolean;
}

export interface AppEntry {
  slug: string; name: string; route: string; blurb: string;
  reads: string[]; writes: string[];
}

export interface Registry {
  apps: AppEntry[];
  your_skills: { slug: string; name: string; route: string; state: string; blurb: string }[];
  shared: { memory: string; permissions: string; work_graph: string };
  local_first: boolean;
}

export const journalApi = {
  list: (projectId: string) =>
    req<{ entries: JournalEntry[] }>('GET', `/journal/project/${projectId}`),
  streak: (projectId: string) =>
    req<{ entries: number; in_window: number; current_streak: number }>(
      'GET', `/journal/project/${projectId}/streak`),
  write: (projectId: string, body: string, entryDate?: string, title = '') =>
    req<JournalEntry>('POST', '/journal', {
      project_id: projectId, body, entry_date: entryDate ?? null, title,
    }),
  autoDraft: (projectId: string, save = false, entryDate?: string) =>
    req<Draft>('POST', `/journal/auto/${projectId}`, {
      save, entry_date: entryDate ?? null,
    }),
  remove: (id: string) => req<{ success: boolean }>('DELETE', `/journal/${id}`),
  registry: (projectId: string) => req<Registry>('GET', `/apps/${projectId}`),
};

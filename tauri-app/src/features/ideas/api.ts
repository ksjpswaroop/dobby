import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/ideas';

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

export type IdeaStatus = 'inbox' | 'backlog' | 'research' | 'archived';

export interface Idea {
  id: string;
  project_id: string;
  text: string;
  status: IdeaStatus;
  promoted_feature_id: string | null;
  promoted_brief_id: string | null;
  created_at: string;
  updated_at: string;
}

export const ideasApi = {
  capture: (projectId: string, text: string) =>
    req<Idea>('POST', '', { project_id: projectId, text }),

  list: (projectId: string, status?: IdeaStatus) =>
    req<{ ideas: Idea[] }>('GET', `/project/${projectId}${status ? `?status=${status}` : ''}`),

  triageToBacklog: (ideaId: string, impact = 5, effort = 5, risk = 5) =>
    req<Idea>('POST', `/${ideaId}/triage/backlog`, {
      impact_score: impact, effort_score: effort, risk_score: risk,
    }),

  triageToResearch: (ideaId: string) =>
    req<Idea>('POST', `/${ideaId}/triage/research`),

  archive: (ideaId: string) => req<Idea>('POST', `/${ideaId}/archive`),

  remove: (ideaId: string) => req<{ success: boolean }>('DELETE', `/${ideaId}`),
};

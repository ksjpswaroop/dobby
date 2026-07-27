import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/projects';

export interface HomeItem {
  id: string;
  title: string;
  route: string;
  risk?: string;
  state?: string;
  kind?: string;
  pareto_score?: number;
}

export interface HomeData {
  greeting: string;
  needs_decision: HomeItem[];
  needs_triage: HomeItem[];
  in_progress: HomeItem[];
  needs_attention: HomeItem[];
  top_backlog: HomeItem[];
  clear: boolean;
}

export const homeApi = {
  get: async (projectId: string): Promise<HomeData> => {
    const resp = await authedFetch(`${BASE}/${projectId}/home`);
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error((j as any).detail || `Request failed (${resp.status})`);
    return j as HomeData;
  },
};

import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/skills';

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

export interface Skill {
  id: string; slug: string; name: string; description: string;
  state: 'draft' | 'published';
  goal: string; expected_output: string; prompt: string;
  sources: string[]; rules: string[];
  approval_mode: string; output_action: string;
  max_output_words: number; local_only: boolean; builtin: boolean;
  run_count: number;
  permissions: { can: string[]; cannot: string[] };
}

export interface SkillRun {
  run_id: string;
  ok: boolean; simulated: boolean;
  output: string; error: string | null;
  trace: { step: string; ok: boolean; detail: string }[];
  duration_ms: number;
  produced: { type: string; id: string } | null;
}

export const skillsApi = {
  list: (projectId: string) => req<{ skills: Skill[] }>('GET', `/project/${projectId}`),
  get: (id: string) => req<Skill>('GET', `/${id}`),
  fork: (id: string, projectId: string) =>
    req<Skill>('POST', `/${id}/fork?project_id=${projectId}`),
  publish: (id: string) => req<Skill>('POST', `/${id}/publish`),
  update: (id: string, changes: Partial<Skill>) => req<Skill>('PUT', `/${id}`, changes),
  run: (id: string, input: string, simulate: boolean) =>
    req<SkillRun>('POST', `/${id}/run`, { input, simulate }),
  runs: (id: string) => req<{ runs: any[] }>('GET', `/${id}/runs`),
  remove: (id: string) => req<{ success: boolean }>('DELETE', `/${id}`),
};

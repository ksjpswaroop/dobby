import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/decisions';

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

export type DecisionStatus = 'open' | 'decided' | 'superseded';

export interface DecisionOption {
  id: string;
  label: string;
  note: string;
  chosen: boolean;
}

export interface Decision {
  id: string;
  project_id: string;
  title: string;
  question: string;
  status: DecisionStatus;
  due_on: string | null;
  days_until_due: number | null;
  overdue: boolean;
  due_soon: boolean;
  chosen_option_id: string | null;
  rationale: string;
  decided_at: string | null;
  superseded_by: string | null;
  options: DecisionOption[];
  links: { id: string; entity_type: string; entity_id: string; blocking: boolean }[];
  blocking_count: number;
}

export interface DecisionSummary {
  open: number;
  overdue: number;
  due_soon: number;
  blocking_work: number;
  most_urgent: Decision | null;
}

export const decisionsApi = {
  list: (projectId: string, status?: DecisionStatus) =>
    req<{ decisions: Decision[] }>('GET',
      `/project/${projectId}${status ? `?status=${status}` : ''}`),

  summary: (projectId: string) =>
    req<DecisionSummary>('GET', `/project/${projectId}/summary`),

  get: (id: string) => req<Decision>('GET', `/${id}`),

  create: (projectId: string, title: string, question = '',
           dueOn?: string, options: { label: string; note?: string }[] = []) =>
    req<Decision>('POST', '', {
      project_id: projectId, title, question, due_on: dueOn ?? null, options,
    }),

  addOption: (id: string, label: string, note = '') =>
    req<Decision>('POST', `/${id}/options`, { label, note }),

  decide: (id: string, optionId: string, rationale = '') =>
    req<Decision>('POST', `/${id}/decide`, { option_id: optionId, rationale }),

  supersede: (id: string, title: string, question = '', dueOn?: string,
              options: { label: string; note?: string }[] = []) =>
    req<Decision>('POST', `/${id}/supersede`, {
      title, question, due_on: dueOn ?? null, options,
    }),

  link: (id: string, entityType: string, entityId: string, blocking = true) =>
    req<Decision>('POST', `/${id}/link`, {
      entity_type: entityType, entity_id: entityId, blocking,
    }),

  unlink: (linkId: string) => req<{ success: boolean }>('DELETE', `/links/${linkId}`),

  blockersFor: (projectId: string, entityType: string, entityId: string) =>
    req<{ decisions: Decision[] }>('GET', `/blocking/${projectId}/${entityType}/${entityId}`),

  remove: (id: string) => req<{ success: boolean }>('DELETE', `/${id}`),
};

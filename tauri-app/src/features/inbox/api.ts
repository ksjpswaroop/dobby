import { authedFetch } from '../../lib/auth';
/** Inbox & Approvals API client. */
const BASE = 'http://localhost:8000/api/v1/inbox';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await authedFetch(`${BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error('Cannot reach the Dobby backend at localhost:8000. Is it running?');
  }
  if (!resp.ok) {
    let detail = `Request failed (${resp.status})`;
    try {
      const j = await resp.json();
      detail = typeof j.detail === 'string' ? j.detail : detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export interface Ask {
  id: string;
  kind: string;
  capability: string | null;
  target: string;
  title: string;
  detail: string;
  risk: 'low' | 'medium' | 'high' | string;
  options: string[];
  state: string;
  answer: string;
  source: string;
  run_id: string | null;
  awaited: boolean;
  expires_at: string | null;
  created_at: string | null;
}

export interface Grant {
  id: string;
  capability: string;
  target: string;
  note: string;
  use_count: number;
  expires_at: string | null;
  last_used_at: string | null;
}

export const inboxApi = {
  meta: () =>
    req<{ capabilities: { id: string; label: string }[]; kinds: string[]; risks: string[] }>(
      'GET',
      '/meta'
    ),

  load: (projectId: string) =>
    req<{ asks: Ask[]; pending: number; grants: Grant[] }>('GET', `/project/${projectId}`),

  answer: (askId: string, approved: boolean, answer = '', rememberHours?: number) =>
    req<Ask>('POST', `/asks/${askId}/answer`, {
      approved,
      answer,
      remember_hours: rememberHours ?? null,
    }),

  cancel: (askId: string) => req<{ success: boolean }>('POST', `/asks/${askId}/cancel`),

  reconcile: (projectId: string) =>
    req<{ reconnected: number; expired: number }>('POST', `/reconcile/${projectId}`),

  revokeGrant: (grantId: string) => req<{ success: boolean }>('DELETE', `/grants/${grantId}`),
};

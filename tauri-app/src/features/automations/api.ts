/** Automations API client — scheduled work. */
const BASE = 'http://localhost:8000/api/v1/automations';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, {
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

export interface Automation {
  id: string;
  name: string;
  description: string;
  action: string;
  action_config: Record<string, unknown>;
  trigger: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  max_runs: number;
  run_count: number;
  is_running: boolean;
  next_run: string | null;
  last_run: string | null;
  last_status: string | null;
  last_error: string | null;
  unread_count: number;
  schedule_text: string;
}

export interface AutomationRun {
  id: string;
  run_id: string | null;
  status: string;
  trigger_source: string;
  summary: string;
  error: string | null;
  read: boolean;
  duration_ms: number | null;
  started_at: string | null;
}

export interface ActionKind {
  id: string;
  label: string;
  blurb: string;
}

export interface Preset {
  label: string;
  cron: string;
}

export const automationApi = {
  meta: () =>
    req<{ actions: ActionKind[]; triggers: string[]; presets: Preset[] }>('GET', '/meta'),

  preview: (cronExpr: string, timezone: string) =>
    req<{ description: string; next_run: string | null; never: boolean }>('POST', '/preview', {
      cron: cronExpr,
      timezone,
    }),

  list: (projectId: string) =>
    req<{ automations: Automation[]; unread: number }>('GET', `/project/${projectId}`),

  create: (body: Record<string, unknown>) => req<Automation>('POST', '', body),

  runs: (id: string) => req<{ runs: AutomationRun[] }>('GET', `/${id}/runs`).then((r) => r.runs),

  setEnabled: (id: string, enabled: boolean) =>
    req<Automation>('PUT', `/${id}/enabled`, { enabled }),

  runNow: (id: string) => req<{ success: boolean }>('POST', `/${id}/run`),

  markRead: (id: string) => req<{ success: boolean }>('POST', `/${id}/read`),

  remove: (id: string) => req<{ success: boolean }>('DELETE', `/${id}`),
};

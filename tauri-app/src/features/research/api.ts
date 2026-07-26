/**
 * Research API client.
 *
 * Mirrors the mind-map client's plain-`fetch` approach: there are no Rust
 * commands behind these endpoints, and the FastAPI sidecar is reachable from
 * both the Tauri webview and a browser.
 */
const BASE = 'http://localhost:8000/api/v1/research';

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

export type BriefStatus =
  | 'pending' | 'planning' | 'researching' | 'synthesizing' | 'complete' | 'failed';

export interface Learning {
  id: string;
  content: string;
  promoted_feature_id: string | null;
}

export interface Track {
  kind: string;
  label: string;
  status: string;
  content: string;
  confidence: number | null;
  error: string | null;
  learnings: Learning[];
}

export interface SourceRef {
  kind: 'model' | 'web' | 'project';
  title: string;
  url: string;
  track_kind: string;
}

export interface Conflict {
  left_index: number;
  right_index: number;
  left: string;
  right: string;
  subject: string;
  explanation: string;
  engine: string;
  left_track?: string;
  right_track?: string;
}

/** Result of the deductive pass over every finding in a brief. */
export interface Audit {
  checked: number;
  consistent: boolean;
  engine: string;
  notes: string[];
  conflicts: Conflict[];
}

export interface Brief {
  id: string;
  project_id: string;
  topic: string;
  context: string;
  status: BriefStatus;
  plan: string;
  summary: string;
  search_provider: string;
  error: string | null;
  run_id: string | null;
  created_at: string | null;
  tracks: Track[];
  sources: SourceRef[];
  audit: Audit | null;
}

export interface BriefSummary {
  id: string;
  topic: string;
  status: BriefStatus;
  search_provider: string;
  created_at: string | null;
}

export interface ProposedFeature {
  title: string;
  description: string;
  impact: number;
  effort: number;
  risk: number;
}

export const researchApi = {
  listTracks: () =>
    req<{ tracks: { kind: string; label: string }[] }>('GET', '/tracks')
      .then((r) => r.tracks),

  providers: () =>
    req<{ providers: { id: string; remote: boolean }[]; active: string }>(
      'GET', '/providers'
    ),

  list: (projectId: string) =>
    req<{ briefs: BriefSummary[] }>('GET', `/project/${projectId}`).then((r) => r.briefs),

  create: (projectId: string, topic: string, context = '') =>
    req<Brief>('POST', '', { project_id: projectId, topic, context }),

  get: (briefId: string) => req<Brief>('GET', `/${briefId}`),

  remove: (briefId: string) => req<{ success: boolean }>('DELETE', `/${briefId}`),

  run: (briefId: string) =>
    req<{ success: boolean; status: string }>('POST', `/${briefId}/run`),

  proposeFeatures: (briefId: string) =>
    req<{ features: ProposedFeature[] }>('POST', `/${briefId}/features`)
      .then((r) => r.features),

  acceptFeatures: (briefId: string, features: ProposedFeature[]) =>
    req<{ created: number }>('POST', `/${briefId}/features/accept`, { features }),
};

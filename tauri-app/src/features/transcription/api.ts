import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/transcription';
const ATTACH_BASE = 'http://localhost:8000/api/v1/attachments';

async function req<T>(method: string, path: string, base = BASE, body?: unknown): Promise<T> {
  const resp = await authedFetch(`${base}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((j as any).detail || `Request failed (${resp.status})`);
  return j as T;
}

export interface ModelInfo {
  id: string;
  size_mb: number;
  blurb: string;
}

export interface InstalledModel {
  id: string;
  path: string;
}

export interface Capabilities {
  whisper_cli: string | null;
  faster_whisper: boolean;
  ffmpeg: string | null;
  models: InstalledModel[];
  available_models: ModelInfo[];
  ready: boolean;
  reason: string;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
}

export interface TranscriptResult {
  text: string;
  segments: Segment[];
  engine: string;
  model: string;
  duration_ms: number;
  audio_seconds: number;
}

export const transcriptionApi = {
  capabilities: () => req<Capabilities>('GET', '/capabilities'),

  downloadModel: (modelId: string, projectId = 'default-project') =>
    req<{ success: boolean }>('POST', '/models/download', BASE,
                              { project_id: projectId, model_id: modelId }),

  deleteModel: (modelId: string) => req<{ success: boolean }>('DELETE', `/models/${modelId}`),

  uploadAudio: async (projectId: string, file: File): Promise<{ id: string }> => {
    const form = new FormData();
    form.append('file', file);
    const resp = await authedFetch(`${ATTACH_BASE}/project/${projectId}`, {
      method: 'POST',
      body: form,
    });
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(j.detail || `Upload failed (${resp.status})`);
    return j;
  },

  transcribe: (projectId: string, attachmentId: string, modelId = '', language = '') =>
    req<TranscriptResult>('POST', '/transcribe', BASE, {
      project_id: projectId, attachment_id: attachmentId, model_id: modelId, language,
    }),
};

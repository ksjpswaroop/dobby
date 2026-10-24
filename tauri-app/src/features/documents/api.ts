import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/documents';

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

export type DocStatus = 'draft' | 'in_review' | 'approved';
export type RefineAction = 'shorten' | 'expand' | 'tone';

export interface DocSection {
  index: number;
  level: number;
  heading: string;
  word_count: number;
}

export interface DocTag {
  id: string;
  name: string;
  color: string;
}

export interface DocumentDetail {
  id: string;
  project_id: string;
  node_type: string;
  title: string;
  content: string;
  word_count: number;
  status: DocStatus;
  dirty: boolean;
  status_history: { from: string; to: string; at: string }[];
  version_count: number;
  open_comments: number;
  tags: DocTag[];
  sections: DocSection[];
  links: string[];
  updated_at: string | null;
}

export interface DocVersion {
  id: string;
  version: number;
  title: string;
  reason: string;
  note: string;
  word_count: number;
  created_at: string;
}

export interface DocComment {
  id: string;
  node_id: string;
  parent_id: string | null;
  body: string;
  start_offset: number | null;
  end_offset: number | null;
  anchor_text: string;
  resolved: boolean;
  created_at: string;
}

export interface LinkMap {
  outgoing: { title: string; node_id: string | null; resolved: boolean }[];
  backlinks: { node_id: string; title: string }[];
}

export interface RefinePreview {
  original: string;
  refined: string;
  action: string;
  original_words: number;
  refined_words: number;
}

export const documentsApi = {
  get: (nodeId: string) => req<DocumentDetail>('GET', `/${nodeId}`),

  save: (nodeId: string, content: string, title?: string) =>
    req<DocumentDetail>('PUT', `/${nodeId}`, { content, title }),

  setStatus: (nodeId: string, status: DocStatus) =>
    req<DocumentDetail>('POST', `/${nodeId}/status`, { status }),

  versions: (nodeId: string) =>
    req<{ versions: DocVersion[] }>('GET', `/${nodeId}/versions`),

  version: (versionId: string) =>
    req<DocVersion & { content: string }>('GET', `/versions/${versionId}`),

  diff: (nodeId: string, versionId: string) =>
    req<{ version: number; diff: string[]; added_lines: number; removed_lines: number }>(
      'GET', `/${nodeId}/versions/${versionId}/diff`),

  restore: (nodeId: string, versionId: string) =>
    req<DocumentDetail>('POST', `/${nodeId}/versions/${versionId}/restore`),

  links: (nodeId: string, projectId: string) =>
    req<LinkMap>('GET', `/${nodeId}/links?project_id=${projectId}`),

  comments: (nodeId: string) =>
    req<{ comments: DocComment[] }>('GET', `/${nodeId}/comments`),

  addComment: (nodeId: string, body: string, start?: number, end?: number, parentId?: string) =>
    req<DocComment>('POST', `/${nodeId}/comments`, {
      body, start_offset: start ?? null, end_offset: end ?? null, parent_id: parentId ?? null,
    }),

  resolveComment: (id: string) => req<DocComment>('POST', `/comments/${id}/resolve`),
  reopenComment: (id: string) => req<DocComment>('POST', `/comments/${id}/reopen`),
  deleteComment: (id: string) => req<{ success: boolean }>('DELETE', `/comments/${id}`),

  addTag: (nodeId: string, projectId: string, name: string, color = 'neutral') =>
    req<DocumentDetail>('POST', `/${nodeId}/tags`, { project_id: projectId, name, color }),

  removeTag: (nodeId: string, tagId: string) =>
    req<DocumentDetail>('DELETE', `/${nodeId}/tags/${tagId}`),

  projectTags: (projectId: string) =>
    req<{ tags: (DocTag & { count: number })[] }>('GET', `/tags/${projectId}`),

  regenerateSection: (nodeId: string, sectionIndex: number, instruction = '') =>
    req<{ document: DocumentDetail; section_index: number; new_text: string }>(
      'POST', `/${nodeId}/regenerate-section`,
      { section_index: sectionIndex, instruction }),

  refinePreview: (content: string, selection: string, action: RefineAction, tone = 'plain') =>
    req<RefinePreview>('POST', '/refine/preview', { content, selection, action, tone }),

  refineApply: (nodeId: string, start: number, end: number, replacement: string) =>
    req<DocumentDetail>('POST', `/${nodeId}/refine/apply`, {
      start_offset: start, end_offset: end, replacement,
    }),

  summarize: (nodeId: string) =>
    req<{ summary: string; title: string }>('POST', `/${nodeId}/summarize`),
};

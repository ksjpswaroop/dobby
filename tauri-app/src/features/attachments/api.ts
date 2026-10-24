import { authedFetch } from '../../lib/auth';

/** Attachments — local files used as source material. */
const BASE = 'http://localhost:8000/api/v1/attachments';

export interface Attachment {
  id: string;
  filename: string;
  size: number;
  mime: string;
  extract_mode: string;
  pages: number;
  chars: number;
  note: string;
  truncated: boolean;
}

/** Extraction modes that produced no usable text — the UI must not offer these
 *  as source material, because an empty document reads as a successful one. */
export const UNREADABLE = ['needs_ocr', 'failed', 'unsupported', 'unavailable'];

export const attachmentApi = {
  list: async (projectId: string): Promise<Attachment[]> => {
    const r = await authedFetch(`${BASE}/project/${projectId}`);
    if (!r.ok) throw new Error('Could not load attachments');
    return (await r.json()).attachments;
  },

  upload: async (projectId: string, file: File): Promise<Attachment> => {
    const form = new FormData();
    form.append('file', file);
    // No Content-Type header — the browser must set the multipart boundary.
    const r = await authedFetch(`${BASE}/project/${projectId}`, {
      method: 'POST',
      body: form,
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error((j as any).detail || 'Upload failed');
    return j as Attachment;
  },

  remove: async (projectId: string, id: string): Promise<void> => {
    const r = await authedFetch(`${BASE}/project/${projectId}/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error('Could not delete');
  },
};

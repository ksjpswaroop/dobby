import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/pins';

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

export type PinEntityType = 'idea' | 'feature' | 'document';

export interface Pin {
  id: string;
  entity_type: PinEntityType;
  entity_id: string;
  order_index: number;
  title: string;
  route: string;
  created_at: string;
}

export const pinsApi = {
  list: (projectId: string) => req<{ pins: Pin[] }>('GET', `/project/${projectId}`),

  pin: (projectId: string, entityType: PinEntityType, entityId: string) =>
    req<Pin>('POST', '', { project_id: projectId, entity_type: entityType, entity_id: entityId }),

  unpin: (projectId: string, entityType: PinEntityType, entityId: string) =>
    req<{ success: boolean }>('DELETE', `/${entityType}/${entityId}?project_id=${projectId}`),

  reorder: (projectId: string, pinIds: string[]) =>
    req<{ pins: Pin[] }>('PATCH', '/reorder', { project_id: projectId, pin_ids: pinIds }),
};

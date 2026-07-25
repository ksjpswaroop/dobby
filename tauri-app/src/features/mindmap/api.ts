/**
 * Mind-map API client.
 *
 * Uses plain `fetch` against the local backend. Unlike the main client there is
 * no Tauri `invoke` branch — there are no Rust commands for these endpoints, and
 * the FastAPI sidecar is reachable from both the Tauri webview and a browser.
 */
import type { MapTree, MindMap, MindMapEdge, MindMapNode } from './types';

const BASE = 'http://localhost:8000/api/v1/mindmaps';

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
      detail = (await resp.json()).detail || detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export const mindmapApi = {
  listMaps: (projectId: string) =>
    req<{ maps: MindMap[] }>('GET', `/project/${projectId}`).then((r) => r.maps),

  createMap: (projectId: string, title: string, sessionId?: string) =>
    req<MindMap>('POST', '', { project_id: projectId, title, session_id: sessionId ?? null }),

  getTree: (mapId: string) => req<MapTree>('GET', `/map/${mapId}/tree`),

  updateMap: (mapId: string, data: Partial<Pick<MindMap, 'title' | 'viewport_state'>>) =>
    req<MindMap>('PATCH', `/map/${mapId}`, data),

  duplicateMap: (mapId: string) => req<MindMap>('POST', `/map/${mapId}/duplicate`),

  deleteMap: (mapId: string) => req<{ success: boolean }>('DELETE', `/map/${mapId}`),

  validate: (mapId: string) =>
    req<{ problems: { node_id: string; issue: string; message: string }[] }>(
      'POST',
      `/map/${mapId}/validate`
    ),

  createNode: (
    mapId: string,
    data: {
      title: string;
      parent_id?: string | null;
      node_type?: string;
      description?: string;
      metadata?: Record<string, any>;
    }
  ) => req<MindMapNode>('POST', `/map/${mapId}/nodes`, data),

  updateNode: (nodeId: string, data: Partial<MindMapNode>) =>
    req<MindMapNode>('PATCH', `/nodes/${nodeId}`, data),

  moveNode: (nodeId: string, newParentId: string | null, sortOrder?: number) =>
    req<MindMapNode>('PUT', `/nodes/${nodeId}/move`, {
      new_parent_id: newParentId,
      sort_order: sortOrder,
    }),

  deleteNode: (nodeId: string) => req<{ deleted: number }>('DELETE', `/nodes/${nodeId}`),

  duplicateNode: (nodeId: string) => req<MindMapNode>('POST', `/nodes/${nodeId}/duplicate`),

  createEdge: (mapId: string, source: string, target: string) =>
    req<MindMapEdge>('POST', `/map/${mapId}/edges`, {
      source_node_id: source,
      target_node_id: target,
    }),

  deleteEdge: (edgeId: string) => req<{ success: boolean }>('DELETE', `/edges/${edgeId}`),
};

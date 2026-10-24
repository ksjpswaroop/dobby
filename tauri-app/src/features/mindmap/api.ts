/**
 * Mind-map API client.
 *
 * Uses plain `fetch` against the local backend. Unlike the main client there is
 * no Tauri `invoke` branch — there are no Rust commands for these endpoints, and
 * the FastAPI sidecar is reachable from both the Tauri webview and a browser.
 */
import type { MapTree, MindMap, MindMapEdge, MindMapNode } from './types';
import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/mindmaps';

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

  // --- AI (Phase 2) ---
  aiGenerate: (projectId: string, topic?: string) =>
    req<{ map_id: string; title: string; nodes_created: number }>('POST', '/ai/generate', {
      project_id: projectId,
      topic: topic || null,
    }),

  aiExpand: (nodeId: string) =>
    req<{ nodes_created: number }>('POST', `/ai/expand/${nodeId}`),

  aiRegroup: (mapId: string) =>
    req<{ proposed: ProposedTree; summary: { current_nodes: number; proposed_nodes: number } }>(
      'POST',
      `/ai/regroup/${mapId}`
    ),

  aiApplyRegroup: (mapId: string, proposed: ProposedTree) =>
    req<{ nodes_created: number }>('POST', `/ai/regroup/${mapId}/apply`, { proposed }),

  // --- Export / import (Phase 3) ---
  exportJson: (mapId: string) => req<Record<string, unknown>>('GET', `/map/${mapId}/export/json`),

  exportText: async (mapId: string, format: 'markdown' | 'mermaid' | 'outline') => {
    const resp = await authedFetch(`${BASE}/map/${mapId}/export/${format}`);
    if (!resp.ok) throw new Error(`Export failed (${resp.status})`);
    return resp.text();
  },

  importMap: (projectId: string, data: unknown) =>
    req<{ map_id: string; nodes_imported: number }>('POST', `/import/${projectId}`, { data }),

  // --- Outline interchange ---
  // Heading markdown is the format other mind-map tools speak, so it doubles as
  // the import path for anything pasted from outside Dobby.
  importOutline: (projectId: string, outline: string, title?: string) =>
    req<{ map_id: string; title: string; nodes_imported: number }>(
      'POST',
      `/import/${projectId}/outline`,
      { outline, title: title ?? null }
    ),

  replaceOutline: (mapId: string, outline: string) =>
    req<{ nodes_created: number }>('PUT', `/map/${mapId}/outline`, { outline }),

  aiChat: (mapId: string, instruction: string) =>
    req<{ nodes_before: number; nodes_after: number }>('POST', `/ai/chat/${mapId}`, {
      instruction,
    }),

  // --- Snapshots ---
  // The client undo stack replays edits onto surviving nodes, so it cannot bring
  // back a node that was deleted. Operations that rebuild the whole tree (chat
  // editing, outline replace) rely on these server-side restore points instead.
  listSnapshots: (mapId: string) =>
    req<{ snapshots: Snapshot[] }>('GET', `/map/${mapId}/snapshots`).then((r) => r.snapshots),

  restoreSnapshot: (mapId: string, snapshotId: string) =>
    req<{ success: boolean }>('POST', `/map/${mapId}/restore/${snapshotId}`),
};

export interface Snapshot {
  id: string;
  label: string;
  created_at: string | null;
}

export interface ProposedNode {
  title: string;
  node_type: string;
  description: string;
  children: ProposedNode[];
}

export interface ProposedTree {
  title: string;
  children: ProposedNode[];
}

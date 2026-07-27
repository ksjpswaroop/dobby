import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/workgraph';

async function req<T>(path: string): Promise<T> {
  const resp = await authedFetch(`${BASE}${path}`);
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((j as any).detail || `Request failed (${resp.status})`);
  return j as T;
}

export type WgNodeType = 'goal' | 'project' | 'decision' | 'skill' | 'document';
export type WgEdgeType = 'pursues' | 'blocked_by' | 'unlocks' | 'documents';

export interface WgNode {
  id: string;
  entity_id: string;
  type: WgNodeType;
  title: string;
  subtitle: string;
  meta: Record<string, any>;
}

export interface WgEdge {
  source: string;
  target: string;
  type: WgEdgeType;
}

export interface WorkGraph {
  project: { id: string; name: string };
  nodes: WgNode[];
  edges: WgEdge[];
  counts: Record<string, number>;
  hidden_projects: number;
}

export interface NodeDetail {
  node: WgNode;
  connected_to: { node: WgNode; type: WgEdgeType }[];
  connected_from: { node: WgNode; type: WgEdgeType }[];
  insight: string | null;
  next_action: { label: string; route: string; reason: string } | null;
  computed: boolean;
}

export const workgraphApi = {
  graph: (projectId: string) => req<WorkGraph>(`/${projectId}`),
  node: (projectId: string, nodeId: string) =>
    req<NodeDetail>(`/${projectId}/node/${encodeURIComponent(nodeId)}`),
};

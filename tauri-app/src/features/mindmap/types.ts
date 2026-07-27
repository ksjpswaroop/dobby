export const NODE_TYPES = [
  'Idea', 'Problem', 'Opportunity', 'Feature', 'Risk',
  'Assumption', 'Research Question', 'Action Item', 'Decision',
] as const;

export type NodeType = (typeof NODE_TYPES)[number];

export interface MindMap {
  id: string;
  project_id: string;
  session_id: string | null;
  title: string;
  root_node_id: string | null;
  viewport_state: Record<string, number>;
  created_at: string | null;
  updated_at: string | null;
}

export interface MindMapNode {
  id: string;
  mind_map_id: string;
  parent_id: string | null;
  title: string;
  description: string;
  node_type: NodeType | string;
  color: string | null;
  sort_order: number;
  metadata: Record<string, any>;
  created_at: string | null;
  updated_at: string | null;
}

export interface TreeNode extends MindMapNode {
  children: TreeNode[];
}

export interface MindMapEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relation_type: string;
}

export interface MapTree {
  map: MindMap;
  nodes: TreeNode[];
  flat: MindMapNode[];
  edges: MindMapEdge[];
}

/** Per-type accent, mapped onto the app's semantic tokens. */
export const TYPE_COLOR: Record<string, string> = {
  Idea: 'rgb(var(--brand))',
  Problem: 'rgb(var(--danger))',
  Opportunity: 'rgb(var(--success))',
  Feature: 'rgb(var(--accent))',
  Risk: 'rgb(var(--warning))',
  Assumption: 'rgb(var(--ink-muted))',
  'Research Question': 'rgb(var(--ink-muted))',
  'Action Item': 'rgb(var(--brand))',
  Decision: 'rgb(var(--accent))',
};

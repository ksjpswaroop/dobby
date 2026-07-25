/**
 * API Client for Dobby v2.0 Tauri App
 *
 * Calls Tauri commands which proxy to FastAPI backend.
 */

import { invoke } from '@tauri-apps/api/core';

// ============================================================================
// Type Definitions
// ============================================================================

export interface DashboardData {
  project_count: number;
  feature_count: number;
  document_count: number;
  today_feature: FeatureInfo | null;
  recent_features: FeatureInfo[];
}

export interface FeatureInfo {
  id: string;
  title: string;
  pareto_score: number;
  status: string;
}

export interface FeatureBacklogItem {
  id: string;
  title: string;
  description: string;
  pareto_score: number;
  impact_score: number;
  effort_score: number;
  risk_score: number;
  category: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  mermaid_syntax: string;
}

export interface GraphNode {
  id: string;
  type: string;
  title: string;
  status: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface WizardStartResult {
  success: boolean;
  session_id: string;
  feature_node_id: string;
}

export interface WizardStepResult {
  success: boolean;
  step: number;
  content: string;
  verification_score: number;
  passed: boolean;
}

export interface YoloGenerationResult {
  success: boolean;
  feature_node_id: string;
  verification_score: number;
  passed: boolean;
  all_content?: Record<string, string>;
  error?: string;
}

export interface AppSettings {
  ollama_host: string;
  model: string;
  theme: 'system' | 'light' | 'dark';
  verification_threshold: number;
  app_version: string;
}

export interface SettingsUpdate {
  ollama_host?: string;
  model?: string;
  theme?: 'system' | 'light' | 'dark';
  verification_threshold?: number;
}

export interface ModelInfo {
  name: string;
  size?: number;
  parameter_size?: string;
  family?: string;
  modified_at?: string;
  active: boolean;
}

export interface BulkDocResult {
  name: string;
  present: boolean;
  words: number;
  score: number;
  passed: boolean;
}

export interface BulkIdeaResult {
  title: string;
  feature_node_id: string;
  success: boolean;
  overall_score: number;
  overall_passed: boolean;
  documents: BulkDocResult[];
  error?: string;
}

export interface BulkResponse {
  total_ideas: number;
  ideas_ok: number;
  documents_expected: number;
  documents_generated: number;
  documents_passed: number;
  gaps: { idea: string; missing: string[] }[];
  results: BulkIdeaResult[];
}

export interface SystemInfo {
  app_version: string;
  python_version: string;
  platform: string;
  ollama_host: string;
  ollama_reachable: boolean;
  ollama_version?: string;
  active_model: string;
}

export interface ProjectInfo {
  id: string;
  name: string;
  idea: string;
  description?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentItem {
  id: string;
  node_type: string;
  title: string;
  status: string;
  content: string;
  word_count: number;
}

export interface DocumentGroup {
  feature: { id: string; title: string; status: string };
  documents: DocumentItem[];
  document_count: number;
}

export interface DocumentsResponse {
  project_id: string;
  feature_count: number;
  features: DocumentGroup[];
}

export interface RunInfo {
  id: string;
  project_id: string | null;
  kind: string;
  label: string;
  status: 'running' | 'ok' | 'failed' | 'cancelled';
  model: string | null;
  node_id: string | null;
  error: string | null;
  total_steps: number;
  completed_steps: number;
  score: number | null;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunEventItem {
  seq: number;
  level: 'info' | 'warn' | 'error';
  event: string;
  message: string;
  step: string | null;
  duration_ms: number | null;
  tokens: number | null;
  score: number | null;
  ts: string | null;
}

export interface SearchResult {
  type: 'project' | 'document' | 'feature' | 'run';
  id: string;
  title: string;
  subtitle: string;
  snippet: string;
  route: string;
  project_id?: string;
}

export interface NodeContent {
  id: string;
  project_id: string;
  node_type: string;
  title: string;
  content: string;
  status: string;
  parent_id: string | null;
}

// ============================================================================
// API Client
// ============================================================================

const DEFAULT_PROJECT_ID = 'default-project';

// ============================================================================
// Dual transport: use Tauri IPC inside the desktop app, plain HTTP in a browser.
// This lets the same UI run as a PWA against the FastAPI backend directly.
// ============================================================================
const API_BASE = 'http://localhost:8000/api/v1';

function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

async function http<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown
): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
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
      const data = await resp.json();
      detail = data.detail || data.message || detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

export const api = {
  // Dashboard
  async getDashboard(projectId: string = DEFAULT_PROJECT_ID): Promise<DashboardData> {
    return isTauri()
      ? invoke<DashboardData>('get_dashboard_data', { projectId })
      : http('GET', `/projects/${projectId}/dashboard`);
  },

  // Feature Backlog
  async getFeatureBacklog(
    projectId: string = DEFAULT_PROJECT_ID,
    status?: string,
    limit?: number
  ): Promise<FeatureBacklogItem[]> {
    return isTauri()
      ? invoke<FeatureBacklogItem[]>('get_feature_backlog', { projectId, status, limit })
      : http('GET', `/projects/${projectId}/backlog${qs({ status, limit })}`);
  },

  // Graph
  async getGraphData(
    projectId: string = DEFAULT_PROJECT_ID,
    maxNodes?: number
  ): Promise<GraphData> {
    return isTauri()
      ? invoke<GraphData>('get_graph_data', { projectId, maxNodes })
      : http('GET', `/projects/${projectId}/graph${qs({ max_nodes: maxNodes })}`);
  },

  // Wizard
  async startWizard(
    projectId: string = DEFAULT_PROJECT_ID,
    featureTitle: string,
    featureDescription: string
  ): Promise<WizardStartResult> {
    return isTauri()
      ? invoke<WizardStartResult>('start_wizard', { projectId, featureTitle, featureDescription })
      : http('POST', `/projects/${projectId}/wizard/start`, {
          title: featureTitle,
          description: featureDescription,
        });
  },

  async executeWizardStep(
    sessionId: string,
    userEdit?: string,
    force = false
  ): Promise<WizardStepResult> {
    return isTauri()
      ? invoke<WizardStepResult>('execute_wizard_step', { sessionId, userEdit, force })
      : http('POST', `/wizard/${sessionId}/execute`, { user_edit: userEdit ?? null, force });
  },

  // YOLO
  async generateYolo(
    projectId: string = DEFAULT_PROJECT_ID,
    featureTitle: string,
    featureDescription: string
  ): Promise<YoloGenerationResult> {
    return isTauri()
      ? invoke<YoloGenerationResult>('generate_yolo', {
          projectId,
          featureTitle,
          featureDescription,
        })
      : http('POST', `/projects/${projectId}/yolo/generate`, {
          title: featureTitle,
          description: featureDescription,
        });
  },

  async acceptYoloGeneration(
    projectId: string = DEFAULT_PROJECT_ID,
    featureNodeId: string
  ): Promise<boolean> {
    return isTauri()
      ? invoke<boolean>('accept_yolo_generation', { projectId, featureNodeId })
      : http('POST', `/projects/${projectId}/yolo/accept`, {
          feature_node_id: featureNodeId,
        }).then(() => true);
  },

  // Feature creation
  async createFeature(
    feature: {
      title: string;
      description: string;
      category: string;
      impactScore: number;
      effortScore: number;
      riskScore: number;
    },
    projectId: string = DEFAULT_PROJECT_ID
  ): Promise<{ id: string; title: string; pareto_score: number }> {
    return isTauri()
      ? invoke('create_feature', {
          projectId,
          title: feature.title,
          description: feature.description,
          category: feature.category,
          impactScore: feature.impactScore,
          effortScore: feature.effortScore,
          riskScore: feature.riskScore,
        })
      : http('POST', `/projects/${projectId}/backlog`, {
          title: feature.title,
          description: feature.description,
          category: feature.category,
          impact_score: feature.impactScore,
          effort_score: feature.effortScore,
          risk_score: feature.riskScore,
        });
  },

  // Settings & models
  async getSettings(): Promise<AppSettings> {
    return isTauri() ? invoke<AppSettings>('get_settings') : http('GET', '/settings');
  },

  async updateSettings(update: SettingsUpdate): Promise<AppSettings> {
    return isTauri()
      ? invoke<AppSettings>('update_settings', { update })
      : http('PUT', '/settings', update);
  },

  async listModels(): Promise<ModelInfo[]> {
    return isTauri() ? invoke<ModelInfo[]>('list_models') : http('GET', '/models');
  },

  async pullModel(name: string): Promise<{ success: boolean; model: string; status: string }> {
    return isTauri() ? invoke('pull_model', { name }) : http('POST', '/models/pull', { name });
  },

  async deleteModel(name: string): Promise<{ success: boolean; model: string }> {
    return isTauri()
      ? invoke('delete_model', { name })
      : http('DELETE', `/models/${encodeURIComponent(name)}`);
  },

  async getSystemInfo(): Promise<SystemInfo> {
    return isTauri() ? invoke<SystemInfo>('get_system_info') : http('GET', '/system/info');
  },

  // Bulk generation
  async generateBulk(
    ideas: { title: string; description: string }[],
    concurrency = 3,
    projectId: string = DEFAULT_PROJECT_ID
  ): Promise<BulkResponse> {
    return isTauri()
      ? invoke<BulkResponse>('bulk_generate', { projectId, ideas, concurrency })
      : http('POST', `/projects/${projectId}/bulk/generate`, { ideas, concurrency });
  },

  // Projects (no Tauri command layer — always over HTTP to the local backend)
  async listProjects(): Promise<ProjectInfo[]> {
    return http('GET', '/projects');
  },

  async createProject(name: string, idea: string, description = ''): Promise<ProjectInfo> {
    return http('POST', '/projects', { name, idea, description });
  },

  async getProject(projectId: string): Promise<ProjectInfo> {
    return http('GET', `/projects/${projectId}`);
  },

  // Documents (generated docs grouped by feature)
  async listDocuments(projectId: string = DEFAULT_PROJECT_ID): Promise<DocumentsResponse> {
    return http('GET', `/projects/${projectId}/documents`);
  },

  async getNode(nodeId: string): Promise<NodeContent> {
    return http('GET', `/nodes/${nodeId}`);
  },

  // Runs — Logs & Traces
  async listRuns(projectId?: string, limit = 50): Promise<{ count: number; runs: RunInfo[] }> {
    return http('GET', `/runs${qs({ project_id: projectId, limit })}`);
  },

  async getRun(runId: string): Promise<{ run: RunInfo; events: RunEventItem[] }> {
    return http('GET', `/runs/${runId}`);
  },

  async clearRuns(projectId?: string): Promise<{ deleted: number }> {
    return http('DELETE', `/runs${qs({ project_id: projectId })}`);
  },

  // Global search
  async search(
    q: string,
    projectId?: string,
    limit = 30
  ): Promise<{ query: string; count: number; results: SearchResult[] }> {
    return http('GET', `/search${qs({ q, project_id: projectId, limit })}`);
  },
};

/** Base URL of the live run-event stream (SSE). */
export const RUN_STREAM_URL = `${API_BASE}/runs/stream`;

export default api;

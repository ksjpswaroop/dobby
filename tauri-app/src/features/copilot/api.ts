import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/copilot';

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

export interface Citation {
  index: number;
  node_id: string;
  title: string;
  project_id: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  model: string;
  latency_ms: number;
  created_at: string;
}

export interface ChatThread {
  id: string;
  project_id: string | null;
  title: string;
  scope: 'project' | 'global';
  updated_at: string;
}

export interface Suggestion {
  kind: string;
  title: string;
  reason: string;
  route: string;
  count: number;
  weight: number;
}

export interface NextAction {
  suggestion: Suggestion | null;
  alternatives: Suggestion[];
  message: string;
  phrased_by_model: boolean;
}

export interface ScoreSuggestion {
  id: string;
  feature_id: string;
  feature_title: string;
  current: { impact: number; effort: number; risk: number; pareto: number };
  suggested: { impact: number; effort: number; risk: number; pareto: number };
  rationale: string;
  confidence: number;
  status: string;
}

export interface Prompt {
  id: string;
  slug: string;
  name: string;
  description: string;
  body: string;
  variables: string[];
  task_type: string;
  builtin: boolean;
  forked_from: string | null;
  version: number;
}

export interface Usage {
  days: number;
  total_calls: number;
  total_tokens: number;
  total_ms: number;
  failures: number;
  avg_ms: number;
  estimated_cost: number;
  cost_basis: { watts: number; rate_per_kwh: number; note: string };
  tokens_are_estimated: boolean;
  by_model: { model: string; calls: number; tokens: number; avg_ms: number; failures: number }[];
  by_task: { task_type: string; calls: number; tokens: number; avg_ms: number }[];
  by_day: { date: string; calls: number; tokens: number; total_ms: number }[];
}

export const copilotApi = {
  createThread: (projectId: string | null, title = 'New chat') =>
    req<ChatThread>('POST', '/threads', { project_id: projectId, title }),

  threads: (projectId: string | null, scope: 'project' | 'global' = 'project') =>
    req<{ threads: ChatThread[] }>('GET',
      `/threads?scope=${scope}${projectId ? `&project_id=${projectId}` : ''}`),

  messages: (threadId: string) =>
    req<{ messages: ChatMessage[] }>('GET', `/threads/${threadId}/messages`),

  ask: (threadId: string, question: string) =>
    req<ChatMessage>('POST', `/threads/${threadId}/ask`, { question }),

  deleteThread: (threadId: string) =>
    req<{ success: boolean }>('DELETE', `/threads/${threadId}`),

  nextAction: (projectId: string, phrase = true) =>
    req<NextAction>('GET', `/next-action/${projectId}?phrase=${phrase}`),

  signals: (projectId: string) =>
    req<{ suggestions: Suggestion[] }>('GET', `/signals/${projectId}`),

  suggestScores: (projectId: string, featureId: string) =>
    req<ScoreSuggestion>('POST', `/prioritize/${projectId}/${featureId}`),

  listScoreSuggestions: (projectId: string) =>
    req<{ suggestions: ScoreSuggestion[] }>('GET', `/prioritize/${projectId}`),

  acceptScores: (suggestionId: string, edits?: { impact?: number; effort?: number; risk?: number }) =>
    req<{ feature_id: string; pareto: number }>('POST', `/prioritize/accept/${suggestionId}`, edits || {}),

  rejectScores: (suggestionId: string) =>
    req<{ success: boolean }>('POST', `/prioritize/reject/${suggestionId}`),

  prompts: (projectId: string) =>
    req<{ prompts: Prompt[] }>('GET', `/prompts?project_id=${projectId}`),

  forkPrompt: (promptId: string, projectId: string) =>
    req<Prompt>('POST', `/prompts/${promptId}/fork?project_id=${projectId}`),

  updatePrompt: (promptId: string, body: string) =>
    req<Prompt>('PUT', `/prompts/${promptId}`, { body }),

  routing: () =>
    req<{ task_types: string[]; routes: Record<string, string>; unrouted: string[] }>('GET', '/routing'),

  setRoute: (taskType: string, model: string) =>
    req<{ routes: Record<string, string> }>('POST', '/routing', { task_type: taskType, model }),

  usage: (projectId?: string, days = 30) =>
    req<Usage>('GET', `/usage?days=${days}${projectId ? `&project_id=${projectId}` : ''}`),
};

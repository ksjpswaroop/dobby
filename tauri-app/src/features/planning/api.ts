import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/planning';

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

export type BoardColumnId = 'backlog' | 'todo' | 'in_progress' | 'blocked' | 'done';

export interface Card {
  feature_id: string;
  title: string;
  category: string | null;
  pareto_score: number;
  impact: number; effort: number; risk: number;
  column: BoardColumnId;
  stored_column: BoardColumnId;
  blocked: boolean;
  estimate: number | null;
  estimate_unit: string;
  sprint_id: string | null;
  milestone_id: string | null;
  node_id: string | null;
}

export interface BoardColumn { id: BoardColumnId; title: string; cards: Card[]; count: number }
export interface Board { columns: BoardColumn[]; total: number }

export interface Sprint {
  id: string; name: string; goal: string; state: string;
  starts_on: string; ends_on: string; capacity: number;
}

export interface SprintSummary {
  sprint: Sprint; item_count: number; completed_count: number;
  committed_estimate: number; completed_estimate: number;
  capacity: number; over_capacity: boolean; remaining_capacity: number;
  items: { feature_id: string; title: string; estimate: number; column: string }[];
}

export interface DailyProposal {
  proposed: { feature_id: string; title: string; estimate: number; pareto_score: number; done: boolean }[];
  capacity: number; planned_estimate: number; ready_count: number;
}

export interface Analytics {
  throughput: { week: string; items: number; estimate: number }[];
  velocity: { sprint_id: string; name: string; committed: number; completed: number; hit_rate: number }[];
  cycle_time: { count: number; average_hours: number; median_hours: number; slowest: { title: string; days: number }[] };
  cumulative_flow: Record<string, any>[];
  avg_items_per_week: number;
}

export interface WeeklyReview {
  week_of: string;
  completed_last_week: { feature_id: string; title: string; estimate: number }[];
  completed_count: number;
  carryover: { feature_id: string; title: string; days_in_progress: number }[];
  long_blocked: { feature_id: string; title: string; blocked_by: string; days: number }[];
  suggested_capacity: number;
  capacity_basis: string;
  ready_next: Card[];
}

export const planningApi = {
  board: (projectId: string, sprintId?: string) =>
    req<Board>('GET', `/board/${projectId}${sprintId ? `?sprint_id=${sprintId}` : ''}`),

  move: (featureId: string, toColumn: BoardColumnId) =>
    req<Card>('POST', `/board/${featureId}/move`, { to_column: toColumn }),

  ready: (projectId: string) => req<{ features: Card[] }>('GET', `/ready/${projectId}`),

  blockers: (projectId: string) =>
    req<{ blockers: any[]; blocked_feature_ids: string[] }>('GET', `/blockers/${projectId}`),

  addBlocker: (projectId: string, featureId: string, blockedById: string) =>
    req<any>('POST', '/blockers', { project_id: projectId, feature_id: featureId, blocked_by_id: blockedById }),

  removeBlocker: (id: string) => req<{ success: boolean }>('DELETE', `/blockers/${id}`),

  setEstimate: (featureId: string, estimate: number, unit = 'points') =>
    req<Card>('POST', `/estimate/${featureId}`, { estimate, unit }),

  sprints: (projectId: string) => req<{ sprints: Sprint[] }>('GET', `/sprints/${projectId}`),

  createSprint: (projectId: string, name: string, startsOn: string, endsOn: string, capacity = 0) =>
    req<Sprint>('POST', '/sprints', { project_id: projectId, name, starts_on: startsOn, ends_on: endsOn, capacity }),

  setSprintState: (sprintId: string, state: string) =>
    req<Sprint>('POST', `/sprints/${sprintId}/state`, { state }),

  sprintSummary: (sprintId: string) => req<SprintSummary>('GET', `/sprints/summary/${sprintId}`),

  assignSprint: (featureId: string, sprintId: string | null) =>
    req<Card>('POST', `/assign-sprint/${featureId}`, { sprint_id: sprintId }),

  milestones: (projectId: string) => req<{ milestones: any[] }>('GET', `/milestones/${projectId}`),

  timeline: (projectId: string) => req<any>('GET', `/timeline/${projectId}`),

  proposeDaily: (projectId: string, capacity = 3) =>
    req<DailyProposal>('GET', `/daily/${projectId}/propose?capacity=${capacity}`),

  commitDaily: (projectId: string, planDate: string, items: any[]) =>
    req<any>('POST', `/daily/${projectId}`, { plan_date: planDate, items }),

  objectives: (projectId: string) => req<{ objectives: any[] }>('GET', `/objectives/${projectId}`),

  analytics: (projectId: string) => req<Analytics>('GET', `/analytics/${projectId}`),

  weeklyReview: (projectId: string) => req<WeeklyReview>('GET', `/weekly-review/${projectId}`),

  wbsPropose: (projectId: string, featureId: string) =>
    req<{ parent_title: string; subtasks: any[] }>('POST', `/wbs/${projectId}/${featureId}/propose`),

  wbsAccept: (projectId: string, parentId: string, subtasks: any[]) =>
    req<{ count: number; dependencies: number }>('POST', `/wbs/${parentId}/accept`, { project_id: projectId, subtasks }),
};

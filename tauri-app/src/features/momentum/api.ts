import { authedFetch } from '../../lib/auth';

const BASE = 'http://localhost:8000/api/v1/momentum';

export interface SparkDay {
  date: string;
  count: number;
}

export interface Momentum {
  streak: number;
  active_today: boolean;
  longest_recent: number;
  total_active_days: number;
  sparkline: SparkDay[];
  tz_offset_minutes: number;
}

export const momentumApi = {
  /**
   * The browser is the only component that reliably knows the user's
   * timezone, so it tells the backend. `getTimezoneOffset()` is inverted
   * (it returns minutes to *add* to local to get UTC), hence the negation.
   */
  get: async (projectId: string): Promise<Momentum> => {
    const offset = -new Date().getTimezoneOffset();
    const resp = await authedFetch(
      `${BASE}/project/${projectId}?tz_offset_minutes=${offset}`
    );
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error((j as any).detail || `Request failed (${resp.status})`);
    return j as Momentum;
  },
};

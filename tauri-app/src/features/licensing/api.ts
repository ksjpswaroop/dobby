import { authedFetch } from '../../lib/auth';

/** Licensing API client — activation and status only; issuance is CLI/admin-only. */
const BASE = 'http://localhost:8000/api/v1/license';

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
      const j = await resp.json();
      detail = typeof j.detail === 'string' ? j.detail : detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export interface LicenseStatus {
  token: string;
  tier: string;
  seats: number;
  updates_until: string | null;
  high_water_mark: string | null;
  last_verified_ok: boolean;
  last_error: string;
}

export interface CheckResult {
  valid: boolean;
  tier: string;
  reason: string;
  offline: boolean;
}

export const licenseApi = {
  status: () => req<LicenseStatus>('GET', '/status'),
  activate: (token: string) => req<CheckResult>('POST', '/activate', { token }),
  deactivate: () => req<{ success: boolean }>('POST', '/deactivate'),
  check: () => req<CheckResult>('POST', '/check'),
};

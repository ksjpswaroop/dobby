/**
 * Launch-token handshake.
 *
 * The backend mints a fresh token each launch and requires it on every API
 * route. The frontend fetches it once from `/api/v1/auth/handshake`, which is
 * safe because CORS restricts which origins may read that response.
 *
 * Everything funnels through `authedFetch` so a single place owns the header,
 * the one-time handshake, and the re-handshake when the backend restarts with a
 * new token (a 401 mid-session means exactly that).
 */
const BACKEND = 'http://localhost:8000';

let token: string | null = null;
let inflight: Promise<string | null> | null = null;

async function handshake(): Promise<string | null> {
  try {
    const r = await fetch(`${BACKEND}/api/v1/auth/handshake`);
    if (!r.ok) return null;
    const body = await r.json();
    return typeof body.token === 'string' ? body.token : null;
  } catch {
    // Backend not up yet. Callers surface their own "is it running?" message.
    return null;
  }
}

/** Fetch the token, reusing a single in-flight request across concurrent callers. */
export async function getToken(force = false): Promise<string | null> {
  if (token && !force) return token;
  if (!inflight) {
    inflight = handshake().finally(() => {
      inflight = null;
    });
  }
  token = await inflight;
  return token;
}

/** Clear the cached token — used when a 401 says the backend restarted. */
export function clearToken(): void {
  token = null;
}

/**
 * `fetch` with the launch token attached.
 *
 * On a 401 the token is refreshed once and the request retried, so restarting
 * the backend during development does not force a page reload.
 */
export async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const send = async (t: string | null) => {
    const headers = new Headers(init.headers || {});
    if (t) headers.set('Authorization', `Bearer ${t}`);
    return fetch(input, { ...init, headers });
  };

  let resp = await send(await getToken());
  if (resp.status === 401) {
    clearToken();
    resp = await send(await getToken(true));
  }
  return resp;
}

/**
 * Append the token as a query parameter.
 *
 * `EventSource` cannot set request headers, so the SSE stream is the one place
 * the token has to travel in the URL. The backend accepts it either way.
 */
export async function withToken(url: string): Promise<string> {
  const t = await getToken();
  if (!t) return url;
  const u = new URL(url, window.location.origin);
  u.searchParams.set('token', t);
  return u.toString();
}

import { useEffect, useRef, useState } from 'react';
import { RUN_STREAM_URL } from '../api/client';

export interface LiveEvent {
  type: 'run.start' | 'run.event' | 'run.finish';
  run_id: string;
  kind?: string;
  label?: string;
  seq?: number;
  level?: 'info' | 'warn' | 'error';
  event?: string;
  message?: string;
  step?: string | null;
  duration_ms?: number | null;
  score?: number | null;
  status?: string;
  error?: string | null;
  completed_steps?: number;
  total_steps?: number;
  /** Set on step.done when that step persisted a graph node. */
  node_id?: string | null;
  ts?: string;
}

/**
 * Subscribe to the backend's live run-event stream (SSE).
 *
 * `events` accumulates (most recent last, capped); `connected` reflects the
 * transport. The browser reconnects automatically on drop.
 */
export function useRunStream(enabled = true, cap = 200) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(RUN_STREAM_URL);
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (m) => {
      if (!m.data) return;
      try {
        const payload = JSON.parse(m.data) as LiveEvent;
        if (!payload.type) return; // the priming {} ping
        setEvents((prev) => [...prev, payload].slice(-cap));
      } catch {
        /* ignore malformed frames */
      }
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [enabled, cap]);

  return { events, connected, clear: () => setEvents([]) };
}

/** Narrow the stream to a single run's live progress. */
export function useRunProgress(runLabel?: string) {
  const { events, connected } = useRunStream(Boolean(runLabel));
  const mine = runLabel ? events.filter((e) => e.label === runLabel || e.run_id) : [];
  const last = [...mine].reverse().find((e) => e.type === 'run.event');
  return {
    connected,
    events: mine,
    completed: last?.completed_steps ?? 0,
    total: last?.total_steps ?? 0,
    message: last?.message ?? '',
  };
}

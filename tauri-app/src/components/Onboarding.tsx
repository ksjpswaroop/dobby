import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authedFetch } from '../lib/auth';
import { Card, Spinner } from './ui';
import { IconCheck, IconChevronRight, IconSparkles } from '../lib/icons';
import { useProject } from '../lib/project';

const BASE = 'http://localhost:8000/api/v1';

interface Step {
  id: string;
  label: string;
  detail: string;
  route: string;
  done: boolean;
}

interface Checklist {
  steps: Step[];
  done_count: number;
  total: number;
  complete: boolean;
  dismissed: boolean;
}

/**
 * Shown until the builder has been all the way round the loop once —
 * capture, triage, generate. Each step's done-state comes from real data,
 * so doing the thing anywhere in the app ticks the box here.
 */
export function Onboarding() {
  const { projectId } = useProject();
  const navigate = useNavigate();
  const [data, setData] = useState<Checklist | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    authedFetch(`${BASE}/projects/${projectId}/onboarding`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j) => setData(Array.isArray(j?.steps) ? j : null))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [projectId]);

  const dismiss = async () => {
    setData(null);
    await authedFetch(`${BASE}/onboarding/dismiss?dismissed=true`, { method: 'POST' })
      .catch(() => {});
  };

  if (loading) return <div className="flex justify-center py-6"><Spinner size={18} /></div>;
  if (!data || data.dismissed || data.complete) return null;

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line px-5 py-3.5 text-sm font-semibold">
        <IconSparkles size={16} className="text-accent" />
        Get started
        <span className="ml-auto text-[11px] font-normal text-ink-muted">
          {data.done_count} of {data.total}
        </span>
        <button
          onClick={dismiss}
          className="rounded px-1.5 text-[11px] font-normal text-ink-muted hover:text-ink"
        >
          Dismiss
        </button>
      </div>
      <ul>
        {data.steps.map((s) => (
          <li key={s.id}>
            <button
              onClick={() => navigate(s.route)}
              disabled={s.done}
              className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-surface2 disabled:hover:bg-transparent"
            >
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                  s.done ? 'border-success bg-success/10 text-success' : 'border-line text-transparent'
                }`}
              >
                <IconCheck size={11} />
              </span>
              <span className="min-w-0 flex-1">
                <span className={`block text-[13px] ${s.done ? 'text-ink-muted line-through' : 'text-ink'}`}>
                  {s.label}
                </span>
                {!s.done && <span className="block text-[11px] text-ink-muted">{s.detail}</span>}
              </span>
              {!s.done && <IconChevronRight size={14} className="shrink-0 text-ink-muted" />}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

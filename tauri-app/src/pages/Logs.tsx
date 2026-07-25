import { useEffect, useMemo, useState } from 'react';
import api, { RunInfo, RunEventItem } from '../api/client';
import { Card, Button, PageHeader, Badge, LoadingState, ErrorState, EmptyState } from '../components/ui';
import { IconLogs, IconRefresh, IconTrash, IconBolt } from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';
import { useRunStream } from '../lib/runStream';
import { useToast } from '../lib/toast';

function fmtDuration(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function fmtTime(ts: string | null): string {
  if (!ts) return '';
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z');
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

const STATUS_TONE: Record<string, 'brand' | 'success' | 'danger' | 'neutral'> = {
  running: 'brand',
  ok: 'success',
  failed: 'danger',
  cancelled: 'neutral',
};

export default function Logs() {
  const { projectId } = useProject();
  const { toast } = useToast();
  const { events: live, connected } = useRunStream(true);

  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ run: RunInfo; events: RunEventItem[] } | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.listRuns(projectId, 50);
      setRuns(res.runs);
      setSelectedId((prev) => prev ?? res.runs[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load runs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSelectedId(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Refresh the run list whenever a run starts or finishes.
  useEffect(() => {
    const last = live[live.length - 1];
    if (last && (last.type === 'run.start' || last.type === 'run.finish')) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.length]);

  useEffect(() => {
    if (!selectedId) return setDetail(null);
    api.getRun(selectedId).then(setDetail).catch(() => setDetail(null));
  }, [selectedId, live.length]);

  const liveByRun = useMemo(() => {
    const m = new Map<string, { completed: number; total: number; message: string }>();
    live.forEach((e) => {
      if (e.type === 'run.event') {
        m.set(e.run_id, {
          completed: e.completed_steps ?? 0,
          total: e.total_steps ?? 0,
          message: e.message ?? '',
        });
      }
    });
    return m;
  }, [live]);

  const clear = async () => {
    try {
      const { deleted } = await api.clearRuns(projectId);
      toast(`Cleared ${deleted} run${deleted === 1 ? '' : 's'}`, 'success');
      setSelectedId(null);
      load();
    } catch {
      toast('Failed to clear runs', 'error');
    }
  };

  if (loading) return <LoadingState label="Loading runs…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Logs & Traces"
        subtitle="Every generation run, step by step — live and historical."
        actions={
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-ink-muted" title="Live event stream">
              <span
                className={cn(
                  'h-2 w-2 rounded-full',
                  connected ? 'bg-success' : 'bg-ink-muted/40'
                )}
              />
              {connected ? 'Live' : 'Offline'}
            </span>
            <Button variant="ghost" icon={<IconRefresh size={16} />} onClick={load} aria-label="Refresh" />
            {runs.length > 0 && (
              <Button variant="ghost" icon={<IconTrash size={16} />} onClick={clear}>
                Clear
              </Button>
            )}
          </div>
        }
      />

      {runs.length === 0 ? (
        <EmptyState
          icon={<IconLogs size={22} />}
          title="No runs yet"
          description="Generate something and every step will be traced here — timings, scores, and errors."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
          {/* Run list */}
          <div className="space-y-2">
            {runs.map((r) => {
              const lv = liveByRun.get(r.id);
              const completed = lv?.completed ?? r.completed_steps;
              const total = lv?.total ?? r.total_steps;
              const pct = total ? Math.round((completed / total) * 100) : 0;
              return (
                <button
                  key={r.id}
                  onClick={() => setSelectedId(r.id)}
                  className={cn(
                    'w-full rounded-xl border bg-surface p-3 text-left transition-colors',
                    selectedId === r.id
                      ? 'border-brand ring-2 ring-brand/20'
                      : 'border-line hover:border-brand/40'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{r.label}</span>
                    <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{r.status}</Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-muted">
                    <span className="uppercase tracking-wide">{r.kind}</span>
                    <span>·</span>
                    <span>{fmtTime(r.started_at)}</span>
                    {r.duration_ms != null && (
                      <>
                        <span>·</span>
                        <span>{fmtDuration(r.duration_ms)}</span>
                      </>
                    )}
                    {r.score != null && (
                      <>
                        <span>·</span>
                        <span>{Math.round(r.score)}/100</span>
                      </>
                    )}
                  </div>
                  {r.status === 'running' && total > 0 && (
                    <div className="mt-2">
                      <div className="h-1 overflow-hidden rounded-full bg-surface2">
                        <div
                          className="h-full rounded-full bg-brand transition-all duration-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <p className="mt-1 truncate text-[11px] text-ink-muted">
                        {lv?.message || `${completed}/${total} steps`}
                      </p>
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {/* Timeline */}
          <Card className="flex min-h-[60vh] flex-col overflow-hidden">
            {detail ? (
              <>
                <div className="border-b border-line px-5 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{detail.run.label}</span>
                    <Badge tone={STATUS_TONE[detail.run.status] ?? 'neutral'}>
                      {detail.run.status}
                    </Badge>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                    <span>{detail.run.kind}</span>
                    {detail.run.model && <span>· {detail.run.model}</span>}
                    <span>· {fmtDuration(detail.run.duration_ms)}</span>
                    <span>· {detail.run.completed_steps}/{detail.run.total_steps} steps</span>
                  </div>
                  {detail.run.error && (
                    <p className="mt-2 rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
                      {detail.run.error}
                    </p>
                  )}
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  <ol className="relative space-y-0 border-l border-line pl-5">
                    {detail.events.map((e) => (
                      <li key={e.seq} className="relative pb-4">
                        <span
                          className={cn(
                            'absolute -left-[27px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-surface',
                            e.level === 'error'
                              ? 'bg-danger'
                              : e.level === 'warn'
                              ? 'bg-warning'
                              : e.event === 'step.done'
                              ? 'bg-success'
                              : 'bg-brand'
                          )}
                        />
                        <div className="flex items-baseline justify-between gap-3">
                          <span
                            className={cn(
                              'text-sm',
                              e.level === 'error' ? 'text-danger' : 'text-ink'
                            )}
                          >
                            {e.message || e.event}
                          </span>
                          <span className="shrink-0 font-mono text-[11px] text-ink-muted">
                            {fmtTime(e.ts)}
                          </span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-muted">
                          <span className="font-mono">{e.event}</span>
                          {e.duration_ms != null && <span>· {fmtDuration(e.duration_ms)}</span>}
                          {e.score != null && <span>· score {Math.round(e.score)}</span>}
                        </div>
                      </li>
                    ))}
                  </ol>
                  {detail.run.status === 'running' && (
                    <div className="flex items-center gap-2 pl-1 text-sm text-brand">
                      <IconBolt size={14} />
                      <span className="animate-pulse">Running…</span>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-ink-muted">
                Select a run to see its trace.
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

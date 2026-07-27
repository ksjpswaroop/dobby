import { useEffect, useState } from 'react';
import { copilotApi, type Usage } from '../features/copilot/api';
import { Badge, Card, CardBody, EmptyState, PageHeader, Spinner } from '../components/ui';
import { IconCpu } from '../lib/icons';
import { useProject } from '../lib/project';

function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}

/**
 * Where your local compute actually goes. Cost is an estimate derived from
 * time x power x rate (local inference has no invoice), and every number that
 * is estimated says so — a confidently wrong figure is worse than none.
 */
export default function ModelUsage() {
  const { projectId } = useProject();
  const [data, setData] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    setLoading(true);
    copilotApi.usage(projectId, days)
      .then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [projectId, days]);

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  if (!data || data.total_calls === 0) {
    return (
      <div>
        <PageHeader title="Model usage" subtitle="Tokens, latency, and estimated local compute cost." />
        <EmptyState
          icon={<IconCpu size={22} />}
          title="No model calls recorded yet"
          description="Generate a document, ask the copilot something, or summarize — usage shows up here."
        />
      </div>
    );
  }

  const peak = Math.max(1, ...data.by_day.map((d) => d.calls));

  const stats = [
    { label: 'Calls', value: data.total_calls.toLocaleString() },
    { label: 'Tokens (est.)', value: data.total_tokens.toLocaleString() },
    { label: 'Avg latency', value: ms(data.avg_ms) },
    { label: 'Compute (est.)', value: `$${data.estimated_cost.toFixed(4)}` },
  ];

  return (
    <div>
      <PageHeader
        title="Model usage"
        subtitle="Tokens, latency, and estimated local compute cost."
        actions={
          <div className="flex gap-1 rounded-xl bg-surface2 p-1">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`rounded-lg px-3 py-1 text-[12px] font-medium transition-colors ${
                  days === d ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardBody className="p-4">
              <p className="text-[12px] text-ink-muted">{s.label}</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">{s.value}</p>
            </CardBody>
          </Card>
        ))}
      </div>

      <p className="mb-4 text-[11px] text-ink-muted">
        {data.cost_basis.note} Basis: {data.cost_basis.watts}W at ${data.cost_basis.rate_per_kwh}/kWh
        — both configurable in Settings. Token counts are estimated (~4 chars/token) because local
        runtimes do not report usage.
      </p>

      {/* Daily activity */}
      <Card className="mb-4">
        <div className="border-b border-line px-5 py-3 text-sm font-semibold">Calls per day</div>
        <CardBody>
          <div className="flex items-end gap-1">
            {data.by_day.map((d) => (
              <div
                key={d.date}
                title={`${d.date} — ${d.calls} calls, ${d.tokens} tokens`}
                style={{ height: `${Math.max(4, (d.calls / peak) * 60)}px` }}
                className="flex-1 rounded-sm bg-brand"
              />
            ))}
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <div className="border-b border-line px-5 py-3 text-sm font-semibold">By model</div>
          <ul className="divide-y divide-line">
            {data.by_model.map((m) => (
              <li key={m.model} className="flex items-center gap-3 px-5 py-2.5">
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{m.model}</span>
                {m.failures > 0 && <Badge tone="danger">{m.failures} failed</Badge>}
                <span className="text-[12px] text-ink-muted">{m.calls} calls</span>
                <span className="w-14 text-right text-[12px] text-ink-muted">{ms(m.avg_ms)}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <div className="border-b border-line px-5 py-3 text-sm font-semibold">By task</div>
          <ul className="divide-y divide-line">
            {data.by_task.map((t) => (
              <li key={t.task_type} className="flex items-center gap-3 px-5 py-2.5">
                <span className="min-w-0 flex-1 truncate text-[13px] capitalize text-ink">
                  {t.task_type.replace('_', ' ')}
                </span>
                <span className="text-[12px] text-ink-muted">{t.calls} calls</span>
                <span className="w-14 text-right text-[12px] text-ink-muted">{ms(t.avg_ms)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

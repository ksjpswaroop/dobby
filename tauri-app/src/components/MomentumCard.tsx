import { useEffect, useState } from 'react';
import { momentumApi, type Momentum } from '../features/momentum/api';
import { Card } from './ui';
import { IconSparkles } from '../lib/icons';
import { useProject } from '../lib/project';

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
  });
}

/**
 * Streak + 14-day momentum. The copy is deliberately non-punitive: a broken
 * streak reads as an invitation to start one, never as a loss — a habit
 * surface that scolds you is one you stop opening.
 */
export function MomentumCard() {
  const { projectId } = useProject();
  const [data, setData] = useState<Momentum | null>(null);

  useEffect(() => {
    momentumApi.get(projectId).then(setData).catch(() => setData(null));
  }, [projectId]);

  if (!data) return null;

  const peak = Math.max(1, ...data.sparkline.map((d) => d.count));
  const { streak, active_today: activeToday } = data;

  const headline =
    streak === 0 ? 'Start your streak today'
      : activeToday ? `${streak}-day streak`
        : `${streak}-day streak — keep it alive`;

  const sub =
    streak === 0
      ? 'Capture an idea, triage one, or generate a document — any of those counts.'
      : activeToday
        ? "You've built today. Nice."
        : 'Anything you build today keeps it going.';

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 px-5 py-4">
        <div
          className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-xl font-semibold ${
            activeToday ? 'bg-brand/10 text-brand' : 'bg-surface2 text-ink-muted'
          }`}
          aria-hidden="true"
        >
          {streak > 0 ? streak : <IconSparkles size={20} />}
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">{headline}</p>
          <p className="mt-0.5 text-[12px] text-ink-muted">{sub}</p>
        </div>

        {/* Sparkline. Bars are decorative; the table-free summary below it is
            what a screen reader actually announces. */}
        <div className="flex items-end gap-[3px]" aria-hidden="true">
          {data.sparkline.map((d) => (
            <div
              key={d.date}
              title={`${dayLabel(d.date)} — ${d.count} action${d.count === 1 ? '' : 's'}`}
              style={{ height: `${Math.max(4, (d.count / peak) * 34)}px` }}
              className={`w-[7px] rounded-sm ${d.count > 0 ? 'bg-brand' : 'bg-surface2'}`}
            />
          ))}
        </div>
      </div>

      <p className="sr-only">
        Current streak {streak} days. {activeToday ? 'Active today.' : 'Not yet active today.'}{' '}
        Longest recent streak {data.longest_recent} days across{' '}
        {data.total_active_days} active days.
      </p>
    </Card>
  );
}

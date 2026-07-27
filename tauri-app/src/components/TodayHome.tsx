import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { homeApi, type HomeData, type HomeItem } from '../features/home/api';
import { Badge, Card, Spinner } from './ui';
import {
  IconControl, IconBulb, IconLogs, IconAlert, IconBacklog, IconCheck, IconChevronRight,
} from '../lib/icons';
import { useProject } from '../lib/project';

type SectionDef = {
  key: keyof Pick<HomeData, 'needs_decision' | 'needs_triage' | 'in_progress' | 'needs_attention' | 'top_backlog'>;
  label: string;
  icon: (p: { size?: number; className?: string }) => JSX.Element;
  tone: 'brand' | 'warning' | 'danger' | 'neutral';
};

// Ordered by what's most blocked on the builder; top backlog is last because
// it's the only forward-looking section, useful when nothing else is waiting.
const SECTIONS: SectionDef[] = [
  { key: 'needs_decision', label: 'Waiting on your decision', icon: IconControl, tone: 'warning' },
  { key: 'needs_attention', label: 'Needs attention', icon: IconAlert, tone: 'danger' },
  { key: 'in_progress', label: 'Pick up where you left off', icon: IconLogs, tone: 'brand' },
  { key: 'needs_triage', label: 'Ideas to triage', icon: IconBulb, tone: 'brand' },
  { key: 'top_backlog', label: 'Highest leverage next', icon: IconBacklog, tone: 'neutral' },
];

/** Today's actionable slice, assembled by a single endpoint. */
export function TodayHome() {
  const { projectId } = useProject();
  const navigate = useNavigate();
  const [data, setData] = useState<HomeData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    homeApi.get(projectId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [projectId]);

  if (loading) return <div className="flex justify-center py-10"><Spinner size={20} /></div>;
  if (!data) return null;

  // Top backlog only when nothing is blocked — otherwise it duplicates the
  // "Today's priority" card below, which has the actual Wizard/YOLO actions.
  const active = SECTIONS.filter(
    (s) => data[s.key].length > 0 && (s.key !== 'top_backlog' || data.clear)
  );

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-ink">{data.greeting}</h2>
        <p className="mt-0.5 text-sm text-ink-muted">
          {data.clear
            ? 'Nothing is waiting on you — a clean slate.'
            : "Here's today's actionable slice."}
        </p>
      </div>

      {data.clear && data.top_backlog.length === 0 ? (
        <Card>
          <div className="flex items-center gap-3 p-5 text-sm text-ink-muted">
            <IconCheck size={16} className="text-success" />
            Capture an idea to get started — ⌘I from anywhere.
          </div>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {active.map((s) => (
            <Card key={s.key} className="overflow-hidden">
              <div className="flex items-center gap-2 border-b border-line px-4 py-3 text-[13px] font-semibold">
                <s.icon size={15} className="text-ink-muted" />
                {s.label}
                <Badge tone={s.tone} className="ml-auto">{data[s.key].length}</Badge>
              </div>
              <ul>
                {data[s.key].map((item: HomeItem) => (
                  <li key={item.id}>
                    <button
                      onClick={() => navigate(item.route)}
                      className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] text-ink transition-colors hover:bg-surface2"
                    >
                      <span className="min-w-0 flex-1 truncate">{item.title}</span>
                      {item.pareto_score !== undefined && (
                        <span className="shrink-0 text-[11px] font-medium text-brand">
                          {item.pareto_score.toFixed(2)}
                        </span>
                      )}
                      <IconChevronRight size={13} className="shrink-0 text-ink-muted" />
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

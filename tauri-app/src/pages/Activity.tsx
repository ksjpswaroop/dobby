import { useEffect, useState } from 'react';
import { timelineApi, type TimelineEvent, type EventCategory } from '../features/timeline/api';
import { Badge, Button, Card, EmptyState, PageHeader, Spinner } from '../components/ui';
import { IconActivity, IconBulb, IconBacklog, IconLogs, IconResearch } from '../lib/icons';
import { useProject } from '../lib/project';
import { useNavigate } from 'react-router-dom';

const FILTERS: { label: string; value: EventCategory | 'all' }[] = [
  { label: 'All', value: 'all' },
  { label: 'Ideas', value: 'idea' },
  { label: 'Backlog', value: 'feature' },
  { label: 'Runs', value: 'run' },
  { label: 'Research', value: 'research' },
];

const CATEGORY_ICON: Record<EventCategory, (p: { size?: number; className?: string }) => JSX.Element> = {
  idea: IconBulb, feature: IconBacklog, run: IconLogs, research: IconResearch,
};

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (sameDay(d, today)) return 'Today';
  if (sameDay(d, yesterday)) return 'Yesterday';
  return d.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/**
 * A reverse-chronological feed derived from ideas, backlog, runs, and
 * research — everything the builder has done in Dobby, sourced from state
 * those services already track (no new event-emission wiring needed).
 */
export default function Activity() {
  const { projectId } = useProject();
  const navigate = useNavigate();

  const [filter, setFilter] = useState<EventCategory | 'all'>('all');
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = () => {
    setLoading(true);
    timelineApi.list(projectId, filter === 'all' ? undefined : filter)
      .then((page) => {
        setEvents(page.events);
        setCursor(page.next_cursor);
      })
      .catch(() => { setEvents([]); setCursor(null); })
      .finally(() => setLoading(false));
  };

  useEffect(load, [projectId, filter]);

  const loadMore = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await timelineApi.list(projectId, filter === 'all' ? undefined : filter, cursor);
      setEvents((prev) => [...prev, ...page.events]);
      setCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  };

  let lastDay = '';

  return (
    <div>
      <PageHeader
        title="Activity"
        subtitle="Everything captured, triaged, generated, and verified — newest first."
      />

      <div className="mb-4 flex gap-1 rounded-xl bg-surface2 p-1">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`flex-1 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${
              filter === f.value ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner size={20} /></div>
      ) : events.length === 0 ? (
        <EmptyState
          icon={<IconActivity size={22} />}
          title="Nothing here yet"
          description="Capture an idea, generate a document, or run a verifier — it'll show up here."
        />
      ) : (
        <div className="space-y-4">
          {events.map((e) => {
            const Icon = CATEGORY_ICON[e.category];
            const header = dayLabel(e.timestamp) !== lastDay ? dayLabel(e.timestamp) : null;
            lastDay = dayLabel(e.timestamp);
            return (
              <div key={e.id}>
                {header && (
                  <div className="mb-1.5 mt-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                    {header}
                  </div>
                )}
                <Card>
                  <button
                    onClick={() => navigate(e.route)}
                    className="flex w-full items-center gap-3 rounded-2xl p-3.5 text-left transition-colors hover:bg-surface2"
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface2 text-ink-muted">
                      <Icon size={15} />
                    </div>
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{e.title}</span>
                    <Badge tone="neutral" className="shrink-0">{timeLabel(e.timestamp)}</Badge>
                  </button>
                </Card>
              </div>
            );
          })}

          {cursor && (
            <div className="flex justify-center pt-2">
              <Button variant="secondary" loading={loadingMore} onClick={loadMore}>
                Load more
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

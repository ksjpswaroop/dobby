import { useState, useEffect } from 'react';
import api, { FeatureBacklogItem } from '../api/client';
import { LoadingState, ErrorState, EmptyState, Badge } from './ui';
import { IconBacklog } from '../lib/icons';

interface FeatureListProps {
  projectId?: string;
  reloadKey?: number;
  onFeatureSelect?: (feature: FeatureBacklogItem) => void;
}

const STATUS_TONE: Record<string, 'neutral' | 'brand' | 'success' | 'danger'> = {
  backlog: 'neutral',
  in_progress: 'brand',
  completed: 'success',
  cancelled: 'danger',
};

const CATEGORY_TONE: Record<string, 'brand' | 'accent' | 'warning' | 'neutral'> = {
  core: 'brand',
  nice_to_have: 'accent',
  stretch: 'warning',
};

export default function FeatureList({ projectId, reloadKey, onFeatureSelect }: FeatureListProps) {
  const [features, setFeatures] = useState<FeatureBacklogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'pareto' | 'created' | 'title'>('pareto');

  useEffect(() => {
    loadFeatures();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, sortBy, reloadKey, projectId]);

  const loadFeatures = async () => {
    try {
      setLoading(true);
      const status = statusFilter === 'all' ? undefined : statusFilter;
      const data = await api.getFeatureBacklog(projectId, status, 100);
      const sorted = [...data].sort((a, b) => {
        switch (sortBy) {
          case 'pareto':
            return b.pareto_score - a.pareto_score;
          case 'created':
            return new Date(b.created_at || '').getTime() - new Date(a.created_at || '').getTime();
          case 'title':
            return a.title.localeCompare(b.title);
          default:
            return 0;
        }
      });
      setFeatures(sorted);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load features');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <LoadingState label="Loading features…" />;
  if (error) return <ErrorState message={error} onRetry={loadFeatures} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="input w-auto py-2"
          >
            <option value="all">All status</option>
            <option value="backlog">Backlog</option>
            <option value="in_progress">In progress</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="input w-auto py-2"
          >
            <option value="pareto">Sort: Pareto score</option>
            <option value="created">Sort: Created date</option>
            <option value="title">Sort: Title</option>
          </select>
        </div>
        <span className="text-sm text-ink-muted">
          {features.length} feature{features.length !== 1 ? 's' : ''}
        </span>
      </div>

      {features.length === 0 ? (
        <EmptyState
          icon={<IconBacklog size={22} />}
          title="No features found"
          description="Add a feature to start prioritizing and generating documentation."
        />
      ) : (
        <div className="space-y-2.5">
          {features.map((f) => (
            <button
              key={f.id}
              onClick={() => onFeatureSelect?.(f)}
              className="group flex w-full items-start justify-between gap-4 rounded-2xl border border-line bg-surface p-4 text-left transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-card"
            >
              <div className="min-w-0 flex-1">
                <h3 className="truncate font-semibold">{f.title}</h3>
                <p className="mt-1 line-clamp-2 text-sm text-ink-muted">{f.description}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge tone={STATUS_TONE[f.status] ?? 'neutral'}>
                    {f.status.replace('_', ' ')}
                  </Badge>
                  <Badge tone={CATEGORY_TONE[f.category] ?? 'neutral'}>
                    {f.category.replace('_', ' ')}
                  </Badge>
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end">
                <span className="text-2xl font-semibold text-brand">{f.pareto_score.toFixed(2)}</span>
                <span className="text-[10px] uppercase tracking-wide text-ink-muted">Pareto</span>
                <div className="mt-2 flex gap-1.5 text-[11px] text-ink-muted">
                  <span title="Impact">I{f.impact_score}</span>
                  <span title="Effort">E{f.effort_score}</span>
                  <span title="Risk">R{f.risk_score}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

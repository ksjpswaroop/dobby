import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api, { DashboardData } from '../api/client';
import { Card, LoadingState, ErrorState, Badge, Button, PageHeader } from '../components/ui';
import { PinnedStrip } from '../components/PinnedStrip';
import { TodayHome } from '../components/TodayHome';
import { Onboarding } from '../components/Onboarding';
import { MomentumCard } from '../components/MomentumCard';
import { useProject } from '../lib/project';
import {
  IconWizard,
  IconBolt,
  IconBacklog,
  IconGraph,
  IconDoc,
  IconSparkles,
  IconChevronRight,
  IconLayers,
  IconFolder,
} from '../lib/icons';

function statusTone(status: string): 'neutral' | 'brand' | 'success' {
  if (status === 'in_progress') return 'brand';
  if (status === 'completed') return 'success';
  return 'neutral';
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { projectId } = useProject();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const loadDashboard = async () => {
    try {
      setLoading(true);
      setError(null);
      setData(await api.getDashboard(projectId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <LoadingState label="Loading dashboard…" />;
  if (error) return <ErrorState message={error} onRetry={loadDashboard} />;

  const stats = [
    { label: 'Projects', value: data?.project_count ?? 0, icon: IconFolder, to: '/projects' },
    { label: 'Features', value: data?.feature_count ?? 0, icon: IconBacklog, to: '/backlog' },
    { label: 'Documents', value: data?.document_count ?? 0, icon: IconDoc, to: '/documents' },
  ];

  const modes = [
    {
      to: '/wizard',
      icon: IconWizard,
      title: 'Wizard',
      desc: 'Guided, step-by-step generation with a review gate at every stage.',
      meta: '7 steps · ~30 min',
      tone: 'brand' as const,
    },
    {
      to: '/yolo',
      icon: IconBolt,
      title: 'YOLO',
      desc: 'Generate all seven artifacts in a single pass, then accept or reject.',
      meta: 'One shot · ~5 min',
      tone: 'accent' as const,
    },
    {
      to: '/bulk',
      icon: IconLayers,
      title: 'Bulk generate',
      desc: 'Paste many ideas and generate every document for all of them at once.',
      meta: 'Parallel · full coverage',
      tone: 'brand' as const,
    },
    {
      to: '/backlog',
      icon: IconBacklog,
      title: 'Backlog',
      desc: 'Prioritize features by Pareto score before you build.',
      meta: 'Impact / effort / risk',
      tone: 'accent' as const,
    },
    {
      to: '/graph',
      icon: IconGraph,
      title: 'Graph',
      desc: 'Visualize how features, specs, and docs depend on each other.',
      meta: 'Dependency map',
      tone: 'accent' as const,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Today" subtitle="Your local document workspace at a glance." />

      <Onboarding />
      <MomentumCard />
      <PinnedStrip />
      <TodayHome />

      {/* Stats (click through to the matching view) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {stats.map((s) => (
          <Link
            key={s.label}
            to={s.to}
            className="group card p-5 transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-card"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-ink-muted">{s.label}</span>
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand/10 text-brand">
                <s.icon size={18} />
              </span>
            </div>
            <p className="mt-3 text-3xl font-semibold tracking-tight">{s.value}</p>
            <span className="mt-1 inline-flex items-center gap-1 text-xs text-ink-muted opacity-0 transition-opacity group-hover:opacity-100">
              Open <IconChevronRight size={12} />
            </span>
          </Link>
        ))}
      </div>

      {/* Priority feature */}
      <Card className="overflow-hidden">
        <div className="border-b border-line px-5 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <IconSparkles size={16} className="text-accent" />
            Today's priority
          </div>
        </div>
        <div className="p-5">
          {data?.today_feature ? (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold">{data.today_feature.title}</h3>
                <div className="mt-2 flex items-center gap-3">
                  <span className="text-2xl font-semibold text-brand">
                    {data.today_feature.pareto_score.toFixed(2)}
                  </span>
                  <span className="text-xs text-ink-muted">Pareto score</span>
                  <Badge tone={statusTone(data.today_feature.status)}>
                    {data.today_feature.status.replace('_', ' ')}
                  </Badge>
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  icon={<IconWizard size={16} />}
                  onClick={() =>
                    navigate(`/wizard?feature=${encodeURIComponent(data.today_feature!.title)}`)
                  }
                >
                  Wizard
                </Button>
                <Button
                  variant="secondary"
                  icon={<IconBolt size={16} />}
                  onClick={() =>
                    navigate(`/yolo?feature=${encodeURIComponent(data.today_feature!.title)}`)
                  }
                >
                  YOLO
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center py-6 text-center">
              <p className="text-sm text-ink-muted">No features in the backlog yet.</p>
              <Link to="/backlog" className="btn-primary mt-4">
                Add your first feature
              </Link>
            </div>
          )}
        </div>
      </Card>

      {/* Recent */}
      {data?.recent_features && data.recent_features.length > 0 && (
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold">Recently completed</h2>
          <div className="divide-y divide-line">
            {data.recent_features.map((f) => (
              <div key={f.id} className="flex items-center justify-between py-2.5">
                <span className="text-sm">{f.title}</span>
                <span className="text-xs text-ink-muted">{f.pareto_score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Modes */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-ink-muted">Start something</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {modes.map((m) => (
            <Link
              key={m.to}
              to={m.to}
              className="group card p-5 transition-all hover:-translate-y-0.5 hover:shadow-card"
            >
              <div className="flex items-start gap-4">
                <span
                  className={
                    m.tone === 'brand'
                      ? 'flex h-11 w-11 items-center justify-center rounded-xl bg-brand/10 text-brand'
                      : 'flex h-11 w-11 items-center justify-center rounded-xl bg-accent/10 text-accent'
                  }
                >
                  <m.icon size={20} />
                </span>
                <div className="flex-1">
                  <div className="flex items-center gap-1.5">
                    <h3 className="font-semibold">{m.title}</h3>
                    <IconChevronRight
                      size={16}
                      className="text-ink-muted transition-transform group-hover:translate-x-0.5"
                    />
                  </div>
                  <p className="mt-1 text-sm text-ink-muted">{m.desc}</p>
                  <p className="mt-2 text-xs font-medium text-ink-muted">{m.meta}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

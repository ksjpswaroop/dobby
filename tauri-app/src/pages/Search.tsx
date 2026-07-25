import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { SearchResult } from '../api/client';
import { Card, PageHeader, Badge, EmptyState, Spinner } from '../components/ui';
import { IconSearch, IconDoc, IconFolder, IconBacklog, IconLogs } from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';

const ICON = {
  project: IconFolder,
  document: IconDoc,
  feature: IconBacklog,
  run: IconLogs,
} as const;

const TONE = {
  project: 'brand',
  document: 'accent',
  feature: 'success',
  run: 'neutral',
} as const;

const FILTERS = ['all', 'document', 'feature', 'project', 'run'] as const;

export default function Search() {
  const navigate = useNavigate();
  const { projectId } = useProject();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [searched, setSearched] = useState(false);
  // Search spans every project by default — that's what makes it global.
  const [scopeToProject, setScopeToProject] = useState(false);
  const [projectNames, setProjectNames] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .listProjects()
      .then((ps) => setProjectNames(Object.fromEntries(ps.map((p) => [p.id, p.name]))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setSearched(false);
      return;
    }
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const r = await api.search(term, scopeToProject ? projectId : undefined, 50);
        setResults(r.results);
        setSearched(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [q, projectId, scopeToProject]);

  const shown = filter === 'all' ? results : results.filter((r) => r.type === filter);
  const countFor = (t: string) =>
    t === 'all' ? results.length : results.filter((r) => r.type === t).length;

  return (
    <div>
      <PageHeader
        title="Search"
        subtitle="One query across your projects, documents, backlog, and runs — all local."
      />

      <Card className="mb-4 flex items-center gap-2 px-4">
        <IconSearch size={17} className="text-ink-muted" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search everything…"
          className="w-full bg-transparent py-3.5 text-sm text-ink outline-none placeholder:text-ink-muted"
        />
        {loading && <Spinner size={16} className="text-brand" />}
      </Card>

      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {results.length > 0 &&
          FILTERS.filter((f) => countFor(f) > 0).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'rounded-lg px-2.5 py-1 text-xs font-medium capitalize transition-colors',
                filter === f ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface2'
              )}
            >
              {f === 'all' ? 'All' : `${f}s`} ({countFor(f)})
            </button>
          ))}
        <button
          onClick={() => setScopeToProject((v) => !v)}
          className={cn(
            'ml-auto rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
            scopeToProject ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface2'
          )}
          title="Limit results to the active project"
        >
          {scopeToProject ? 'This project only' : 'All projects'}
        </button>
      </div>

      {q.trim().length < 2 ? (
        <EmptyState
          icon={<IconSearch size={22} />}
          title="Search your workspace"
          description="Type at least two characters. Results cover generated documents, backlog features, projects, and runs."
        />
      ) : searched && shown.length === 0 ? (
        <EmptyState
          icon={<IconSearch size={22} />}
          title={`No matches for “${q.trim()}”`}
          description="Try a different term, or generate more documents to search over."
        />
      ) : (
        <div className="space-y-2">
          {shown.map((r) => {
            const Icon = ICON[r.type] ?? IconDoc;
            return (
              <button
                key={`${r.type}-${r.id}`}
                onClick={() => navigate(r.route)}
                className="flex w-full items-start gap-3 rounded-xl border border-line bg-surface p-4 text-left transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-card"
              >
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface2 text-ink-muted">
                  <Icon size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate font-medium text-ink">{r.title}</span>
                    <Badge tone={TONE[r.type] ?? 'neutral'}>{r.type}</Badge>
                  </span>
                  {r.snippet && (
                    <span className="mt-1 block line-clamp-2 text-sm text-ink-muted">{r.snippet}</span>
                  )}
                  <span className="mt-1 block text-[11px] text-ink-muted">
                    {r.subtitle}
                    {r.project_id && projectNames[r.project_id] && (
                      <> · {projectNames[r.project_id]}</>
                    )}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

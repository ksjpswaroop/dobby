import { useState, useEffect, useRef } from 'react';
import api from '../api/client';
import GraphViewer from '../components/GraphViewer';
import { useProject } from '../lib/project';
import { useRunStream } from '../lib/runStream';
import { cn } from '../lib/cn';
import { Button, PageHeader, ErrorState, LoadingState } from '../components/ui';
import { IconRefresh } from '../lib/icons';

const LEGEND = [
  { color: '#6366f1', label: 'Feature' },
  { color: '#22c55e', label: 'User story' },
  { color: '#f59e0b', label: 'Analysis' },
  { color: '#a855f7', label: 'Flowchart' },
  { color: '#ec4899', label: 'Pseudocode' },
  { color: '#ef4444', label: 'TDD tests' },
  { color: '#71717a', label: 'Documentation' },
];

export default function GraphPage() {
  const [mermaidSyntax, setMermaidSyntax] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { projectId } = useProject();
  const [maxNodes, setMaxNodes] = useState(50);
  const [nodeCount, setNodeCount] = useState(0);
  const [justAdded, setJustAdded] = useState<string[]>([]);

  // Live: every generation step publishes an event, so the graph extends as
  // each document is written rather than only on a manual refresh.
  const { events, connected } = useRunStream(true, 60);
  const seenRef = useRef(0);

  useEffect(() => {
    loadGraph();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxNodes, projectId]);

  useEffect(() => {
    if (events.length === seenRef.current) return;
    const fresh = events.slice(seenRef.current);
    seenRef.current = events.length;

    // A node was persisted, or a run started/finished — either way, redraw.
    const touchesGraph = fresh.some(
      (e) =>
        e.type === 'run.start' ||
        e.type === 'run.finish' ||
        (e.type === 'run.event' && (e.event === 'step.done' || e.node_id))
    );
    if (!touchesGraph) return;

    const newIds = fresh.map((e) => e.node_id).filter(Boolean) as string[];
    if (newIds.length) {
      setJustAdded((prev) => [...prev, ...newIds]);
      // Let the highlight fade so the canvas settles back to normal.
      window.setTimeout(
        () => setJustAdded((prev) => prev.filter((id) => !newIds.includes(id))),
        6000
      );
    }
    loadGraph({ quiet: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  /** `quiet` skips the spinner so live redraws don't flash the canvas. */
  const loadGraph = async (opts: { quiet?: boolean } = {}) => {
    try {
      if (!opts.quiet) setLoading(true);
      setError(null);
      const data = await api.getGraphData(projectId, maxNodes);
      setMermaidSyntax(data.mermaid_syntax);
      setNodeCount(data.nodes?.length ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      if (!opts.quiet) setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Graph"
        subtitle="Dependencies across features, specs, flows, tests and docs."
        actions={
          <div className="flex items-center gap-2">
            <span
              className="flex items-center gap-1.5 text-xs text-ink-muted"
              title={connected ? 'Graph updates as documents are generated' : 'Live updates unavailable'}
            >
              <span className={cn('h-2 w-2 rounded-full', connected ? 'bg-success' : 'bg-ink-muted/40')} />
              {connected ? 'Live' : 'Offline'}
            </span>
            <span className="text-xs text-ink-muted">{nodeCount} nodes</span>
            <select
              value={maxNodes}
              onChange={(e) => setMaxNodes(Number(e.target.value))}
              className="input w-auto py-2"
            >
              {[20, 50, 100, 200].map((n) => (
                <option key={n} value={n}>
                  {n} nodes
                </option>
              ))}
            </select>
            <Button variant="secondary" icon={<IconRefresh size={16} />} onClick={() => loadGraph()} loading={loading}>
              Refresh
            </Button>
          </div>
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={() => loadGraph()} />
      ) : loading ? (
        <LoadingState label="Loading graph…" />
      ) : (
        <>
          <GraphViewer mermaidSyntax={mermaidSyntax} highlightIds={justAdded} />
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 rounded-2xl border border-line bg-surface px-5 py-4">
            {LEGEND.map((l) => (
              <div key={l.label} className="flex items-center gap-2 text-xs text-ink-muted">
                <span className="h-3 w-3 rounded" style={{ backgroundColor: l.color }} />
                {l.label}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

import { useState, useEffect } from 'react';
import api from '../api/client';
import GraphViewer from '../components/GraphViewer';
import { useProject } from '../lib/project';
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

  useEffect(() => {
    loadGraph();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxNodes, projectId]);

  const loadGraph = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getGraphData(projectId, maxNodes);
      setMermaidSyntax(data.mermaid_syntax);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Graph"
        subtitle="Dependencies across features, specs, flows, tests and docs."
        actions={
          <div className="flex items-center gap-2">
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
            <Button variant="secondary" icon={<IconRefresh size={16} />} onClick={loadGraph} loading={loading}>
              Refresh
            </Button>
          </div>
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={loadGraph} />
      ) : loading ? (
        <LoadingState label="Loading graph…" />
      ) : (
        <>
          <GraphViewer mermaidSyntax={mermaidSyntax} />
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

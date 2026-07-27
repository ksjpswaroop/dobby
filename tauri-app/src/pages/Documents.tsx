import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { DocumentsResponse, DocumentItem } from '../api/client';
import { Card, Button, PageHeader, Badge, LoadingState, ErrorState, EmptyState } from '../components/ui';
import { IconDoc, IconBolt, IconLayers, IconDownload, IconRefresh, IconMindmap } from '../lib/icons';
import { mindmapApi } from '../features/mindmap/api';
import { cn } from '../lib/cn';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';

const LABELS: Record<string, string> = {
  feature: 'Feature Spec',
  feature_spec: 'Feature Spec',
  user_story: 'User Story',
  functional_analysis: 'Functional Analysis',
  flowchart: 'Flowchart',
  pseudocode: 'Pseudocode',
  tdd_tests: 'TDD Tests',
  documentation: 'Documentation',
};

function statusTone(s: string): 'success' | 'warning' | 'neutral' {
  if (s === 'verified' || s === 'finalized') return 'success';
  if (s === 'draft' || s === 'pending_review') return 'warning';
  return 'neutral';
}

export default function Documents() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { projectId } = useProject();

  const [data, setData] = useState<DocumentsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mapping, setMapping] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.listDocuments(projectId);
      setData(res);
      // auto-select the first document
      const first = res.features.find((f) => f.documents.length)?.documents[0];
      setSelectedId((prev) => prev ?? first?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSelectedId(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const selected: DocumentItem | undefined = useMemo(() => {
    if (!data || !selectedId) return undefined;
    for (const f of data.features) {
      const d = f.documents.find((x) => x.id === selectedId);
      if (d) return d;
    }
    return undefined;
  }, [data, selectedId]);

  const download = (d: DocumentItem) => {
    const blob = new Blob([d.content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${d.title.replace(/[^\w.-]+/g, '_')}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast('Downloaded', 'success');
  };

  /**
   * Turn a generated document into a mind map.
   *
   * Generated docs are already heading-structured markdown, which is exactly
   * what the outline importer consumes — so a spec becomes a navigable map with
   * no extra conversion step.
   */
  const toMindMap = async (d: DocumentItem) => {
    if (!d.content?.trim()) {
      toast('That document is empty', 'error');
      return;
    }
    setMapping(true);
    try {
      const r = await mindmapApi.importOutline(projectId, d.content, d.title);
      toast(`Mind map created — ${r.nodes_imported} nodes`, 'success');
      navigate('/mindmap');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not build a mind map', 'error');
    } finally {
      setMapping(false);
    }
  };

  if (loading) return <LoadingState label="Loading documents…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const totalDocs = data?.features.reduce((n, f) => n + f.documents.length, 0) ?? 0;

  return (
    <div>
      <PageHeader
        title="Documents"
        subtitle={`${data?.feature_count ?? 0} feature${(data?.feature_count ?? 0) === 1 ? '' : 's'} · ${totalDocs} documents in this project`}
        actions={
          <div className="flex gap-2">
            <Button variant="ghost" icon={<IconRefresh size={16} />} onClick={load} aria-label="Refresh" />
            <Button variant="secondary" icon={<IconBolt size={16} />} onClick={() => navigate('/yolo')}>
              Generate
            </Button>
          </div>
        }
      />

      {totalDocs === 0 ? (
        <EmptyState
          icon={<IconDoc size={22} />}
          title="No documents yet"
          description="Generate a full set of engineering documents from an idea — all 7 artifacts per feature."
          action={
            <div className="flex gap-2">
              <Button variant="primary" icon={<IconBolt size={16} />} onClick={() => navigate('/yolo')}>
                Generate one (YOLO)
              </Button>
              <Button variant="secondary" icon={<IconLayers size={16} />} onClick={() => navigate('/bulk')}>
                Generate many (Bulk)
              </Button>
            </div>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
          {/* Left: feature → docs list */}
          <div className="space-y-4">
            {data!.features.map((f) => (
              <Card key={f.feature.id} className="overflow-hidden">
                <div className="border-b border-line px-4 py-2.5">
                  <div className="truncate text-sm font-semibold" title={f.feature.title}>
                    {f.feature.title}
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-muted">{f.documents.length} documents</div>
                </div>
                <div className="p-1.5">
                  {f.documents.map((d) => (
                    <button
                      key={d.id}
                      onClick={() => setSelectedId(d.id)}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                        selectedId === d.id ? 'bg-brand/10 text-brand' : 'text-ink hover:bg-surface2'
                      )}
                    >
                      <IconDoc size={15} className="shrink-0 opacity-70" />
                      <span className="flex-1 truncate">{LABELS[d.node_type] ?? d.title}</span>
                      <span className="text-[10px] text-ink-muted">{d.word_count}w</span>
                    </button>
                  ))}
                </div>
              </Card>
            ))}
          </div>

          {/* Right: reader */}
          <Card className="flex min-h-[60vh] flex-col overflow-hidden">
            {selected ? (
              <>
                <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
                  <div className="min-w-0">
                    <div className="truncate font-semibold">{selected.title}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
                      <Badge tone="brand">{LABELS[selected.node_type] ?? selected.node_type}</Badge>
                      <Badge tone={statusTone(selected.status)}>{selected.status.replace('_', ' ')}</Badge>
                      <span>{selected.word_count} words</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      variant="primary"
                      onClick={() => navigate(`/documents/${selected.id}`)}
                      title="Edit, version, comment on, and refine this document"
                    >
                      Open editor
                    </Button>
                    <Button
                      variant="ghost"
                      icon={<IconMindmap size={16} />}
                      loading={mapping}
                      onClick={() => toMindMap(selected)}
                      title="Turn this document's headings into a mind map"
                    >
                      Mind map
                    </Button>
                    <Button variant="secondary" icon={<IconDownload size={16} />} onClick={() => download(selected)}>
                      Export .md
                    </Button>
                  </div>
                </div>
                <pre
                  data-selectable
                  className="flex-1 overflow-auto whitespace-pre-wrap px-6 py-5 font-mono text-[13px] leading-relaxed text-ink"
                >
                  {selected.content || '(empty)'}
                </pre>
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-ink-muted">
                Select a document to read it.
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

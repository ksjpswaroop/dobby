import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Background, Controls, MiniMap, ReactFlow, ReactFlowProvider,
  type Edge, type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  workgraphApi, type NodeDetail, type WgNode, type WorkGraph as Graph,
} from '../features/workgraph/api';
import { Badge, Button, Card, EmptyState, PageHeader, Spinner } from '../components/ui';
import { IconGraph, IconAlert, IconX } from '../lib/icons';
import { useProject } from '../lib/project';

/** Colour carries meaning here: red is "in your way", not decoration. */
const TYPE_STYLE: Record<string, { border: string; bg: string; label: string }> = {
  goal: { border: '#7c3aed', bg: 'rgba(124,58,237,0.08)', label: 'NORTH STAR' },
  project: { border: '#0d9488', bg: 'rgba(13,148,136,0.08)', label: 'PROJECT' },
  decision: { border: '#dc2626', bg: 'rgba(220,38,38,0.08)', label: 'DECISION' },
  skill: { border: '#2563eb', bg: 'rgba(37,99,235,0.08)', label: 'SKILL' },
  document: { border: '#6b7280', bg: 'rgba(107,114,128,0.08)', label: 'DOCUMENT' },
};

// Bands by type, so the graph reads top-to-bottom as goal → work → what is in
// the way. A force layout would be prettier and far less legible.
const BAND_Y: Record<string, number> = {
  goal: 0, project: 200, decision: 0, skill: 0, document: 0,
};

const COL_W = 290;
const ROW_H = 150;
// Wrapping matters more than it looks: nine projects in one row makes
// fitView zoom out until nothing is readable.
const PER_ROW = 4;

function layout(graph: Graph): { nodes: Node[]; edges: Edge[] } {
  const byType: Record<string, WgNode[]> = {};
  for (const n of graph.nodes) (byType[n.type] ||= []).push(n);

  // Each band starts below the one above it, so wrapped rows never collide.
  const projectRows = Math.ceil((byType.project?.length ?? 0) / PER_ROW);
  BAND_Y.decision = 200 + Math.max(1, projectRows) * ROW_H + 80;
  BAND_Y.skill = BAND_Y.decision + ROW_H;
  BAND_Y.document = BAND_Y.skill + ROW_H;

  const nodes: Node[] = [];
  for (const [type, list] of Object.entries(byType)) {
    list.forEach((n, i) => {
      const col = i % PER_ROW;
      const row = Math.floor(i / PER_ROW);
      const inRow = Math.min(list.length - row * PER_ROW, PER_ROW);
      const style = TYPE_STYLE[n.type] ?? TYPE_STYLE.document;
      const overdue = n.type === 'decision' && n.meta?.overdue;
      nodes.push({
        id: n.id,
        position: {
          x: col * COL_W - (inRow * COL_W) / 2 + COL_W / 2,
          y: BAND_Y[type] + row * ROW_H,
        },
        data: {
          label: (
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontSize: 9, letterSpacing: '.08em', opacity: 0.7 }}>
                {style.label}{overdue ? ' · OVERDUE' : ''}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, marginTop: 3 }}>{n.title}</div>
              {n.subtitle && (
                <div style={{ fontSize: 11, opacity: 0.7, marginTop: 3 }}>
                  {n.subtitle.slice(0, 70)}
                </div>
              )}
            </div>
          ),
        },
        style: {
          width: 250, padding: 11, borderRadius: 14,
          border: `2px solid ${overdue ? '#dc2626' : style.border}`,
          background: style.bg, color: 'inherit',
          boxShadow: overdue ? '0 0 0 3px rgba(220,38,38,0.15)' : undefined,
        },
      });
    });
  }

  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    animated: e.type === 'blocked_by',
    label: e.type.replace('_', ' '),
    labelStyle: { fontSize: 10, fill: 'currentColor', opacity: 0.65 },
    style: {
      stroke: e.type === 'blocked_by' ? '#dc2626'
        : e.type === 'unlocks' ? '#2563eb' : '#7c3aed',
      strokeWidth: 1.6,
      strokeDasharray: e.type === 'blocked_by' ? '5 4' : undefined,
    },
  }));

  return { nodes, edges };
}

/**
 * How goals, projects, decisions, and skills connect.
 *
 * The graph is derived on read, so it can never disagree with the five
 * tables behind it — and every insight in the side panel is computed from
 * edges rather than phrased by a model.
 */
export default function WorkGraphPage() {
  const { projectId } = useProject();
  const navigate = useNavigate();

  const [graph, setGraph] = useState<Graph | null>(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<NodeDetail | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    workgraphApi.graph(projectId)
      .then(setGraph).catch(() => setGraph(null)).finally(() => setLoading(false));
  }, [projectId]);

  useEffect(load, [load]);

  const flow = useMemo(() => (graph ? layout(graph) : { nodes: [], edges: [] }), [graph]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    workgraphApi.node(projectId, node.id).then(setDetail).catch(() => setDetail(null));
  }, [projectId]);

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  if (!graph || graph.nodes.length === 0) {
    return (
      <div>
        <PageHeader title="Work Graph" subtitle="How your goals, projects, decisions, and skills connect." />
        <EmptyState
          icon={<IconGraph size={22} />}
          title="Nothing to connect yet"
          description="Add a goal, some backlog work, or a decision and the graph draws itself."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Work Graph"
        subtitle="How your goals, projects, decisions, and skills connect."
        actions={
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            {Object.entries(graph.counts).filter(([, n]) => n > 0).map(([type, n]) => (
              <span key={type} className="flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-full"
                      style={{ background: TYPE_STYLE[type]?.border }} />
                {n} {type}{n === 1 ? '' : 's'}
              </span>
            ))}
          </div>
        }
      />

      {graph.hidden_projects > 0 && (
        <p className="mb-3 flex items-center gap-1.5 text-[11px] text-ink-muted">
          <IconAlert size={12} />
          Showing the highest-value work — {graph.hidden_projects} more not drawn.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card className="overflow-hidden" >
          <div style={{ height: '68vh' }}>
            <ReactFlowProvider>
              <ReactFlow
                nodes={flow.nodes}
                edges={flow.edges}
                onNodeClick={onNodeClick}
                fitView
                proOptions={{ hideAttribution: true }}
                minZoom={0.2}
              >
                <Background gap={18} size={1} />
                <Controls showInteractive={false} />
                {/* The minimap only earns its space once the graph is bigger
                    than the viewport; below that it is an empty white box. */}
                {flow.nodes.length > 8 && (
                  <MiniMap
                    pannable
                    zoomable
                    maskColor="rgba(0,0,0,0.06)"
                    style={{ background: 'transparent',
                             border: '1px solid rgba(128,128,128,0.25)',
                             borderRadius: 10 }}
                    nodeColor={(n) => {
                      const id = String(n.id).split(':')[0];
                      return TYPE_STYLE[id]?.border ?? '#6b7280';
                    }}
                  />
                )}
              </ReactFlow>
            </ReactFlowProvider>
          </div>
        </Card>

        {/* Detail panel */}
        <Card className="overflow-hidden">
          {!detail ? (
            <div className="p-5 text-[13px] text-ink-muted">
              Select a node to see what it connects to and what to do next.
            </div>
          ) : (
            <div className="max-h-[68vh] overflow-y-auto p-5">
              <div className="mb-1 flex items-start justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider"
                      style={{ color: TYPE_STYLE[detail.node.type]?.border }}>
                  {TYPE_STYLE[detail.node.type]?.label}
                </span>
                <button onClick={() => setDetail(null)}
                        aria-label="Close details"
                        className="text-ink-muted hover:text-ink">
                  <IconX size={14} />
                </button>
              </div>

              <h3 className="text-lg font-semibold leading-snug text-ink">
                {detail.node.title}
              </h3>
              {detail.node.subtitle && (
                <p className="mt-1 text-[12.5px] text-ink-muted">{detail.node.subtitle}</p>
              )}

              {detail.node.type === 'decision' && detail.node.meta?.due_on && (
                <p className="mt-2">
                  <Badge tone={detail.node.meta.overdue ? 'danger' : 'warning'}>
                    {detail.node.meta.overdue ? 'Overdue' : 'Due'} {detail.node.meta.due_on}
                  </Badge>
                </p>
              )}

              {detail.insight && (
                <div className="mt-4 rounded-xl border border-line bg-surface2 p-3">
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                    Insight
                  </p>
                  <p className="text-[12.5px] text-ink">{detail.insight}</p>
                  <p className="mt-1.5 text-[10px] text-ink-muted">
                    Computed from your data — not generated.
                  </p>
                </div>
              )}

              {(detail.connected_to.length > 0 || detail.connected_from.length > 0) && (
                <div className="mt-4">
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                    Connected to
                  </p>
                  <ul className="space-y-1">
                    {[...detail.connected_to, ...detail.connected_from].map((c, i) => (
                      <li key={`${c.node.id}-${i}`} className="text-[12.5px]">
                        <span className="text-ink-muted">{c.type.replace('_', ' ')}: </span>
                        <button
                          onClick={() => workgraphApi.node(projectId, c.node.id).then(setDetail)}
                          className="text-brand hover:underline"
                        >
                          {c.node.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {detail.next_action && (
                <div className="mt-5">
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                    Next best action
                  </p>
                  <p className="mb-2 text-[12px] text-ink-muted">{detail.next_action.reason}</p>
                  <Button variant="primary" className="w-full"
                          onClick={() => navigate(detail.next_action!.route)}>
                    {detail.next_action.label}
                  </Button>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

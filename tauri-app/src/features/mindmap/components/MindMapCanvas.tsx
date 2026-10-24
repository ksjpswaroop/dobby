import { useCallback, useMemo } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useMindMapStore } from '../store';
import { branchColors, hiddenIds, layoutTree } from '../layout';
import { MindMapNodeCard, type MindNodeData } from './MindMapNode';
import { useTheme } from '../../../lib/theme';

const nodeTypes = { mind: MindMapNodeCard };

function CanvasInner() {
  const tree = useMindMapStore((s) => s.tree);
  const collapsed = useMindMapStore((s) => s.collapsed);
  const selectedNodeId = useMindMapStore((s) => s.selectedNodeId);
  const selectNode = useMindMapStore((s) => s.selectNode);
  const toggleCollapse = useMindMapStore((s) => s.toggleCollapse);
  const moveNode = useMindMapStore((s) => s.moveNode);
  const toggleChecked = useMindMapStore((s) => s.toggleChecked);
  const layout = useMindMapStore((s) => s.layout);
  const { resolved } = useTheme();

  const { nodes, edges, colors } = useMemo(() => {
    if (!tree) {
      return { nodes: [] as Node[], edges: [] as Edge[], colors: new Map<string, string>() };
    }

    const hidden = hiddenIds(tree, collapsed);
    const positioned = layoutTree(tree, collapsed, layout).filter((p) => !hidden.has(p.id));
    const colors = branchColors(tree);

    const rfNodes: Node[] = positioned.map((p) => ({
      id: p.id,
      type: 'mind',
      position: { x: p.x, y: p.y },
      selected: p.id === selectedNodeId,
      data: {
        title: p.node.title,
        nodeType: p.node.node_type,
        childCount: p.node.children.length,
        collapsed: collapsed.has(p.id),
        isRoot: p.depth === 0,
        branchColor: colors.get(p.id),
        color: p.node.color,
        checked: !!(p.node.metadata || {}).checked,
        onToggle: toggleCollapse,
        onToggleChecked: toggleChecked,
      } satisfies MindNodeData,
    }));

    const visible = new Set(positioned.map((p) => p.id));

    // Hierarchy edges, tinted to their branch so a colour traces all the way out
    // from the centre.
    const rfEdges: Edge[] = tree.flat
      .filter((n) => n.parent_id && visible.has(n.id) && visible.has(n.parent_id))
      .map((n) => ({
        id: `h-${n.id}`,
        source: n.parent_id as string,
        target: n.id,
        type: layout === 'radial' ? 'straight' : 'smoothstep',
        style: {
          stroke: colors.get(n.id) ?? 'rgb(var(--line))',
          strokeWidth: 1.5,
          opacity: 0.55,
        },
      }));

    // Cross-branch edges render dashed so they read differently from hierarchy
    tree.edges
      .filter((e) => visible.has(e.source_node_id) && visible.has(e.target_node_id))
      .forEach((e) =>
        rfEdges.push({
          id: `x-${e.id}`,
          source: e.source_node_id,
          target: e.target_node_id,
          type: 'smoothstep',
          animated: true,
          style: { stroke: 'rgb(var(--accent))', strokeWidth: 1.5, strokeDasharray: '4 3' },
        })
      );

    return { nodes: rfNodes, edges: rfEdges, colors };
  }, [tree, collapsed, selectedNodeId, toggleCollapse, toggleChecked, layout]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_e, node) => selectNode(node.id),
    [selectNode]
  );

  // Dropping one node onto another re-parents it; the backend rejects cycles.
  const onConnect: OnConnect = useCallback(
    (c) => {
      if (c.source && c.target) moveNode(c.target, c.source);
    },
    [moveNode]
  );

  return (
    <ReactFlow
      aria-label="Mind map canvas. Use the toolbar to add nodes; arrow keys pan."
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      onConnect={onConnect}
      onPaneClick={() => selectNode(null)}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      minZoom={0.2}
      maxZoom={1.75}
      proOptions={{ hideAttribution: true }}
      colorMode={resolved}
    >
      <Background gap={18} color="rgb(var(--line))" />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        maskColor="rgb(var(--surface2) / 0.6)"
        nodeColor={(n) => colors.get(n.id) ?? 'rgb(var(--brand))'}
        style={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))' }}
      />
    </ReactFlow>
  );
}

export function MindMapCanvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}

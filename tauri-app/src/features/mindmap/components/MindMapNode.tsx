import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { TYPE_COLOR } from '../types';
import { cn } from '../../../lib/cn';

export interface MindNodeData {
  title: string;
  nodeType: string;
  childCount: number;
  collapsed: boolean;
  isRoot: boolean;
  onToggle: (id: string) => void;
  [key: string]: unknown;
}

/**
 * A mind-map node card. Memoized because React Flow re-renders every node on
 * viewport changes, and a large map would otherwise stutter.
 */
function MindMapNodeInner({ id, data, selected }: NodeProps) {
  const d = data as MindNodeData;
  const accent = TYPE_COLOR[d.nodeType] ?? 'rgb(var(--brand))';

  return (
    <div
      role="treeitem"
      aria-selected={!!selected}
      aria-label={`${d.title}, type ${d.nodeType}${d.childCount ? `, ${d.childCount} children` : ''}`}
      aria-expanded={d.childCount > 0 ? !d.collapsed : undefined}
      className={cn(
        'group relative min-w-[168px] max-w-[260px] rounded-xl border bg-surface px-3 py-2 shadow-soft transition-shadow',
        selected ? 'border-brand ring-2 ring-brand/30' : 'border-line hover:shadow-card'
      )}
      style={{ borderLeft: `4px solid ${accent}` }}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-line" />

      <div
        className={cn(
          'truncate text-[13px] text-ink',
          d.isRoot ? 'font-semibold' : 'font-medium'
        )}
        title={d.title}
      >
        {d.title}
      </div>
      <div className="mt-0.5 flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: accent }} />
        <span className="truncate text-[10px] uppercase tracking-wide text-ink-muted">
          {d.nodeType}
        </span>
      </div>

      {d.childCount > 0 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            d.onToggle(id);
          }}
          title={d.collapsed ? 'Expand branch' : 'Collapse branch'}
          aria-label={d.collapsed ? 'Expand branch' : 'Collapse branch'}
          className="absolute -right-2.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full border border-line bg-surface text-[10px] font-semibold text-ink-muted shadow-soft hover:border-brand hover:text-brand"
        >
          {d.collapsed ? d.childCount : '−'}
        </button>
      )}

      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-line" />
    </div>
  );
}

export const MindMapNodeCard = memo(MindMapNodeInner);

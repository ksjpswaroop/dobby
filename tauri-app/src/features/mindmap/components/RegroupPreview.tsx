import { useMindMapStore } from '../store';
import { Modal } from '../../../components/Modal';
import { Button } from '../../../components/ui';
import type { ProposedNode } from '../api';

function Outline({ nodes, depth = 0 }: { nodes: ProposedNode[]; depth?: number }) {
  return (
    <ul className={depth ? 'ml-4 border-l border-line pl-3' : ''}>
      {nodes.map((n, i) => (
        <li key={`${n.title}-${i}`} className="py-0.5">
          <span className="text-sm text-ink">{n.title}</span>
          <span className="ml-2 text-[10px] uppercase tracking-wide text-ink-muted">
            {n.node_type}
          </span>
          {n.children?.length > 0 && <Outline nodes={n.children} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}

/**
 * Shows what the AI wants to do *before* anything changes. Accepting is the
 * only path that writes, and it snapshots the current map first.
 */
export function RegroupPreview() {
  const proposal = useMindMapStore((s) => s.proposal);
  const aiBusy = useMindMapStore((s) => s.aiBusy);
  const apply = useMindMapStore((s) => s.aiApplyRegroup);
  const dismiss = useMindMapStore((s) => s.dismissProposal);

  if (!proposal) return null;
  const { proposed, summary } = proposal;

  return (
    <Modal
      open
      onClose={dismiss}
      title="Proposed reorganization"
      footer={
        <>
          <Button variant="ghost" onClick={dismiss}>
            Reject
          </Button>
          <Button variant="primary" loading={aiBusy === 'regroup'} onClick={() => apply()}>
            Accept &amp; replace
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex items-center gap-4 rounded-xl bg-surface2 px-4 py-3 text-sm">
          <span className="text-ink-muted">
            Now: <span className="font-semibold text-ink">{summary.current_nodes}</span> nodes
          </span>
          <span className="text-ink-muted">→</span>
          <span className="text-ink-muted">
            Proposed: <span className="font-semibold text-brand">{summary.proposed_nodes}</span> nodes
          </span>
        </div>

        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            {proposed.title}
          </div>
          <div className="max-h-[40vh] overflow-y-auto rounded-xl border border-line p-3">
            <Outline nodes={proposed.children} />
          </div>
        </div>

        <p className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-ink-muted">
          Accepting replaces the current nodes. A snapshot of the existing map is saved
          first, so this can be restored.
        </p>
      </div>
    </Modal>
  );
}

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  planningApi, type Board as BoardData, type BoardColumnId, type Card as CardT, type Sprint,
} from '../features/planning/api';
import { Badge, Card, EmptyState, PageHeader, Spinner } from '../components/ui';
import { IconBacklog, IconAlert } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

// "blocked" is absent on purpose: it is derived from blocker rows, so it can
// never be a drop target. Moving a card there would let the board disagree
// with the blockers that produced it.
const MOVE_TARGETS: BoardColumnId[] = ['backlog', 'todo', 'in_progress', 'done'];

const COLUMN_TONE: Record<string, 'neutral' | 'brand' | 'warning' | 'success' | 'danger'> = {
  backlog: 'neutral', todo: 'neutral', in_progress: 'brand',
  blocked: 'danger', done: 'success',
};

export default function BoardPage() {
  const { projectId } = useProject();
  const { toast } = useToast();
  const navigate = useNavigate();

  const [board, setBoard] = useState<BoardData | null>(null);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [sprintFilter, setSprintFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    planningApi.board(projectId, sprintFilter || undefined)
      .then(setBoard).catch(() => setBoard(null)).finally(() => setLoading(false));
  };

  useEffect(load, [projectId, sprintFilter]);
  useEffect(() => {
    planningApi.sprints(projectId).then((r) => setSprints(r.sprints)).catch(() => setSprints([]));
  }, [projectId]);

  const move = async (card: CardT, to: BoardColumnId) => {
    setBusy(card.feature_id);
    try {
      await planningApi.move(card.feature_id, to);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not move', 'error');
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  if (!board || board.total === 0) {
    return (
      <div>
        <PageHeader title="Board" subtitle="Your Pareto-scored backlog as a board." />
        <EmptyState
          icon={<IconBacklog size={22} />}
          title="Nothing on the board"
          description="Add features to the backlog and they appear here automatically."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Board"
        subtitle="Blocked is computed from real blockers — it is never a place you drop something."
        actions={
          sprints.length > 0 && (
            <select
              value={sprintFilter}
              onChange={(e) => setSprintFilter(e.target.value)}
              className="input w-auto py-2"
            >
              <option value="">All work</option>
              {sprints.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          )
        }
      />

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        {board.columns.map((col) => (
          <div key={col.id} className="min-w-0">
            <div className="mb-2 flex items-center gap-2">
              <h3 className="text-[13px] font-semibold text-ink">{col.title}</h3>
              <Badge tone={COLUMN_TONE[col.id]}>{col.count}</Badge>
            </div>

            <div className="space-y-2">
              {col.cards.length === 0 && (
                <p className="rounded-xl border border-dashed border-line px-3 py-4 text-center text-[11px] text-ink-muted">
                  Empty
                </p>
              )}

              {col.cards.map((card) => (
                <Card key={card.feature_id} className="p-3">
                  <button
                    onClick={() => card.node_id && navigate(`/documents/${card.node_id}`)}
                    className="block w-full text-left"
                  >
                    <p className="text-[12.5px] font-medium leading-snug text-ink">{card.title}</p>
                  </button>

                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-muted">
                    <span className="font-semibold text-brand">{card.pareto_score.toFixed(2)}</span>
                    <span>I{card.impact} E{card.effort} R{card.risk}</span>
                    {card.estimate != null && <span>· {card.estimate}{card.estimate_unit === 'points' ? 'p' : 'h'}</span>}
                  </div>

                  {card.blocked && (
                    <p className="mt-1.5 flex items-center gap-1 text-[10px] text-danger">
                      <IconAlert size={10} /> waiting on a blocker
                    </p>
                  )}

                  {/* Column moves are buttons, not drag targets — keyboard
                      operable, and it keeps "blocked" impossible to pick. */}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {MOVE_TARGETS.filter((t) => t !== card.stored_column).map((t) => (
                      <button
                        key={t}
                        disabled={busy === card.feature_id}
                        onClick={() => move(card, t)}
                        className="rounded-md bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted transition-colors hover:text-brand disabled:opacity-40"
                      >
                        → {t.replace('_', ' ')}
                      </button>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

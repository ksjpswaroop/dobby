import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { pinsApi, type Pin } from '../features/pins/api';
import { Card } from './ui';
import { IconPin, IconBulb, IconBacklog, IconDoc } from '../lib/icons';
import { useProject } from '../lib/project';

const TYPE_ICON = { idea: IconBulb, feature: IconBacklog, document: IconDoc } as const;

/**
 * The builder's current focus, one click away. Reordering is keyboard-first
 * (←/→ move an item) rather than drag-only — the roadmap's DoD calls for
 * keyboard operability, and a keyboard path is also the simpler one to get
 * right.
 */
export function PinnedStrip() {
  const { projectId } = useProject();
  const navigate = useNavigate();
  const [pins, setPins] = useState<Pin[]>([]);

  const load = () => {
    pinsApi.list(projectId).then((r) => setPins(r.pins)).catch(() => setPins([]));
  };

  useEffect(load, [projectId]);

  const move = async (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= pins.length) return;
    const next = [...pins];
    [next[index], next[target]] = [next[target], next[index]];
    setPins(next);
    try {
      await pinsApi.reorder(projectId, next.map((p) => p.id));
    } catch {
      load();
    }
  };

  const unpin = async (p: Pin) => {
    setPins((prev) => prev.filter((x) => x.id !== p.id));
    try {
      await pinsApi.unpin(projectId, p.entity_type, p.entity_id);
    } finally {
      load();
    }
  };

  if (pins.length === 0) return null;

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line px-5 py-4 text-sm font-semibold">
        <IconPin size={16} className="text-brand" />
        Pinned
      </div>
      <div className="flex flex-wrap gap-2 p-4">
        {pins.map((p, i) => {
          const Icon = TYPE_ICON[p.entity_type];
          return (
            <div
              key={p.id}
              className="group flex items-center gap-2 rounded-xl border border-line bg-surface2 py-1.5 pl-3 pr-1.5"
            >
              <button
                onClick={() => navigate(p.route)}
                className="flex items-center gap-2 text-[13px] text-ink"
              >
                <Icon size={14} className="text-ink-muted" />
                <span className="max-w-[220px] truncate">{p.title}</span>
              </button>
              <div className="flex items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                <button
                  onClick={() => move(i, -1)}
                  disabled={i === 0}
                  aria-label={`Move ${p.title} earlier`}
                  className="rounded px-1 text-[11px] text-ink-muted hover:text-ink disabled:opacity-30"
                >
                  ←
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={i === pins.length - 1}
                  aria-label={`Move ${p.title} later`}
                  className="rounded px-1 text-[11px] text-ink-muted hover:text-ink disabled:opacity-30"
                >
                  →
                </button>
                <button
                  onClick={() => unpin(p)}
                  aria-label={`Unpin ${p.title}`}
                  className="rounded px-1 text-[11px] text-ink-muted hover:text-danger"
                >
                  ✕
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

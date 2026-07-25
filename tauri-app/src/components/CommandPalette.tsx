import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../lib/cn';
import { ALL_ITEMS, NAV_SECTIONS } from '../lib/nav';
import { IconSearch } from '../lib/icons';

/** Global ⌘K / Ctrl-K command palette: jump to any surface, live or planned. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // route -> category, for labels
  const catOf = useMemo(() => {
    const m = new Map<string, string>();
    NAV_SECTIONS.forEach((s) => s.items.forEach((i) => m.set(i.route, s.label)));
    return m;
  }, []);

  const results = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return ALL_ITEMS;
    return ALL_ITEMS.filter(
      (i) =>
        i.label.toLowerCase().includes(term) ||
        (catOf.get(i.route) || '').toLowerCase().includes(term) ||
        (i.blurb || '').toLowerCase().includes(term)
    );
  }, [q, catOf]);

  useEffect(() => {
    if (open) {
      setQ('');
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => setActive(0), [q]);

  if (!open) return null;

  const go = (route: string) => {
    navigate(route);
    onClose();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[active]) go(results[active].route);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl animate-scale-in overflow-hidden rounded-2xl border border-line bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-line px-4">
          <IconSearch size={16} className="text-ink-muted" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder="Search or jump to…"
            className="w-full bg-transparent py-3.5 text-sm text-ink outline-none placeholder:text-ink-muted"
          />
          <kbd className="rounded-md border border-line bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted">
            esc
          </kbd>
        </div>
        <div className="max-h-[52vh] overflow-y-auto p-1.5">
          {results.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-ink-muted">No matches.</div>
          )}
          {results.map((i, idx) => (
            <button
              key={i.route}
              onMouseEnter={() => setActive(idx)}
              onClick={() => go(i.route)}
              className={cn(
                'flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                idx === active ? 'bg-brand/10 text-brand' : 'text-ink hover:bg-surface2'
              )}
            >
              <i.icon size={16} />
              <span className="flex-1 truncate">{i.label}</span>
              <span className="text-[11px] text-ink-muted">{catOf.get(i.route)}</span>
              {i.status === 'planned' && (
                <span className="rounded-md bg-surface2 px-1.5 py-0.5 text-[10px] font-medium text-ink-muted">
                  soon
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

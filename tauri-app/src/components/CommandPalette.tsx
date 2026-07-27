import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../lib/cn';
import { buildCommands, buildModelCommands, buildPinCommands, type Command } from '../lib/commands';
import { useTheme } from '../lib/theme';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';
import api, { type SearchResult } from '../api/client';
import { IconSearch, IconDoc, IconFolder, IconBacklog, IconLogs } from '../lib/icons';

const RESULT_ICON = {
  project: IconFolder,
  document: IconDoc,
  feature: IconBacklog,
  run: IconLogs,
} as const;

/**
 * The Command Center: one ⌘K surface that *runs actions*, switches models,
 * navigates anywhere, and searches your local content — not just a nav jumper.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const { toast } = useToast();
  const { projectId } = useProject();

  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const [models, setModels] = useState<Command[]>([]);
  const [pinned, setPinned] = useState<Command[]>([]);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const ctx = useMemo(
    () => ({ navigate, toast, setTheme, projectId, close: onClose }),
    [navigate, toast, setTheme, projectId, onClose]
  );

  // Pinned first: the builder's current focus should always be fastest to reach.
  const commands = useMemo(
    () => [...pinned, ...buildCommands(ctx), ...models],
    [ctx, models, pinned]
  );

  // Load model-switch commands once the palette first opens.
  useEffect(() => {
    if (open && models.length === 0) buildModelCommands(ctx).then(setModels);
    // Pins change often, so refresh them on every open rather than once.
    if (open) buildPinCommands(ctx).then(setPinned);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open) {
      setQ('');
      setActive(0);
      setResults([]);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Debounced content search — only for queries worth a round-trip.
  useEffect(() => {
    const term = q.trim();
    if (!open || term.length < 2) {
      setResults([]);
      return;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const r = await api.search(term, undefined, 8); // global: jump anywhere
        setResults(r.results);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 180);
    return () => clearTimeout(t);
  }, [q, open, projectId]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) {
      return [
        ...commands.filter((c) => c.group === 'Pinned'),
        ...commands.filter((c) => c.group === 'Actions').slice(0, 8),
      ];
    }
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(term) ||
        c.group.toLowerCase().includes(term) ||
        (c.keywords || '').toLowerCase().includes(term)
    );
  }, [q, commands]);

  // A single flat list so arrow keys traverse commands then search results.
  const rows = useMemo(
    () => [
      ...filtered.map((c) => ({ kind: 'command' as const, cmd: c })),
      ...results.map((r) => ({ kind: 'result' as const, res: r })),
    ],
    [filtered, results]
  );

  useEffect(() => setActive(0), [q]);

  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  if (!open) return null;

  const runRow = (i: number) => {
    const row = rows[i];
    if (!row) return;
    if (row.kind === 'command') {
      row.cmd.run();
    } else {
      navigate(row.res.route);
      onClose();
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, rows.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      runRow(active);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  let lastGroup = '';

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
            placeholder="Run a command, switch model, or search your work…"
            className="w-full bg-transparent py-3.5 text-sm text-ink outline-none placeholder:text-ink-muted"
          />
          <kbd className="rounded-md border border-line bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted">
            esc
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[56vh] overflow-y-auto p-1.5">
          {rows.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-ink-muted">
              {searching ? 'Searching…' : 'No matches.'}
            </div>
          )}

          {rows.map((row, idx) => {
            const isActive = idx === active;
            if (row.kind === 'command') {
              const c = row.cmd;
              const header = c.group !== lastGroup ? c.group : null;
              lastGroup = c.group;
              return (
                <div key={c.id}>
                  {header && (
                    <div className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                      {header}
                    </div>
                  )}
                  <button
                    data-active={isActive}
                    onMouseEnter={() => setActive(idx)}
                    onClick={() => runRow(idx)}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                      isActive ? 'bg-brand/10 text-brand' : 'text-ink hover:bg-surface2'
                    )}
                  >
                    <c.icon size={16} />
                    <span className="flex-1 truncate">{c.label}</span>
                    {c.hint && <span className="text-[11px] text-ink-muted">{c.hint}</span>}
                  </button>
                </div>
              );
            }

            const r = row.res;
            const Icon = RESULT_ICON[r.type] ?? IconDoc;
            const first = idx === filtered.length;
            return (
              <div key={`${r.type}-${r.id}`}>
                {first && (
                  <div className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                    In your work
                  </div>
                )}
                <button
                  data-active={isActive}
                  onMouseEnter={() => setActive(idx)}
                  onClick={() => runRow(idx)}
                  className={cn(
                    'flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors',
                    isActive ? 'bg-brand/10' : 'hover:bg-surface2'
                  )}
                >
                  <Icon size={16} className={cn('mt-0.5', isActive ? 'text-brand' : 'text-ink-muted')} />
                  <span className="min-w-0 flex-1">
                    <span className={cn('block truncate text-sm', isActive ? 'text-brand' : 'text-ink')}>
                      {r.title}
                    </span>
                    {r.snippet && (
                      <span className="block truncate text-[11px] text-ink-muted">{r.snippet}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-[11px] text-ink-muted">{r.subtitle}</span>
                </button>
              </div>
            );
          })}
        </div>

        <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[11px] text-ink-muted">
          <span>↑↓ navigate</span>
          <span>↵ run</span>
          <span className="ml-auto">{rows.length} result{rows.length === 1 ? '' : 's'}</span>
        </div>
      </div>
    </div>
  );
}

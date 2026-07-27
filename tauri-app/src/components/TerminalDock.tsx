import { useEffect, useRef, useState } from 'react';
import { authedFetch } from '../lib/auth';
import { Badge, Spinner } from './ui';
import { IconAlert, IconTerminal, IconX } from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';

const BASE = 'http://localhost:8000/api/v1/terminal';

const MIN_HEIGHT = 140;
const MAX_HEIGHT = 640;
const DEFAULT_HEIGHT = 280;
const HEIGHT_KEY = 'dobby-terminal-height';

interface Entry {
  command: string;
  stdout?: string;
  stderr?: string;
  exit_code?: number;
  ran: boolean;
  reason?: string;
  timed_out?: boolean;
  duration_ms?: number;
  error?: string;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await authedFetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((j as any).detail || `Request failed (${r.status})`);
  return j as T;
}

/**
 * The terminal, docked to the bottom of the shell.
 *
 * A terminal is somewhere you glance at while working, not a destination you
 * navigate to — you want it *and* the page you were on. Docking it keeps both,
 * and the drawer collapses to nothing when unused so it costs no space.
 *
 * The panel stays mounted while open so scrollback and history survive
 * navigation; only the drawer's height animates.
 */
export function TerminalDock({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { projectId } = useProject();

  const [meta, setMeta] = useState<{ allowlist: string[]; workspace: string } | null>(null);
  const [command, setCommand] = useState('');
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<{ decision: string; reason: string } | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [height, setHeight] = useState(() => {
    const saved = Number(localStorage.getItem(HEIGHT_KEY));
    return saved >= MIN_HEIGHT && saved <= MAX_HEIGHT ? saved : DEFAULT_HEIGHT;
  });

  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragging = useRef(false);

  useEffect(() => {
    if (!open) return;
    authedFetch(`${BASE}/meta?project_id=${projectId}`)
      .then((r) => r.json())
      .then(setMeta)
      .catch(() => {});
    // Focus the prompt when the drawer opens — the reason you opened it.
    const t = window.setTimeout(() => inputRef.current?.focus(), 60);
    return () => window.clearTimeout(t);
  }, [open, projectId]);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [entries, open]);

  // Pre-flight: say what will happen before Enter is pressed.
  useEffect(() => {
    if (!command.trim()) {
      setCheck(null);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      post<{ decision: string; reason: string }>('/check',
                                                 { command, project_id: projectId })
        .then((c) => !cancelled && setCheck(c))
        .catch(() => !cancelled && setCheck(null));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [command, projectId]);

  // Drag the top edge to resize.
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, window.innerHeight - e.clientY));
      setHeight(next);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = '';
      localStorage.setItem(HEIGHT_KEY, String(height));
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [height]);

  const submit = async () => {
    const cmd = command.trim();
    if (!cmd || busy) return;
    setBusy(true);
    setHistory((h) => [...h, cmd]);
    setHistIdx(-1);
    setCommand('');
    try {
      const r = await post<Entry>('/run', { project_id: projectId, command: cmd });
      setEntries((e) => [...e, { ...r, command: cmd }]);
    } catch (e) {
      setEntries((prev) => [
        ...prev,
        { command: cmd, ran: false, error: e instanceof Error ? e.message : 'Failed' },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    } else if (e.key === 'Escape') {
      onClose();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const next = histIdx < 0 ? history.length - 1 : Math.max(0, histIdx - 1);
      if (history[next] !== undefined) {
        setHistIdx(next);
        setCommand(history[next]);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIdx < 0) return;
      const next = histIdx + 1;
      if (next >= history.length) {
        setHistIdx(-1);
        setCommand('');
      } else {
        setHistIdx(next);
        setCommand(history[next]);
      }
    }
  };

  return (
    <div
      className={cn(
        'shrink-0 overflow-hidden border-t border-line bg-surface transition-[height] duration-200',
        open ? '' : 'border-t-0'
      )}
      style={{
        height: open ? height : 0,
        // `visibility: hidden` rather than unmounting: scrollback and history
        // survive the drawer closing, but the prompt leaves the tab order.
        // Height alone is not enough — a 0px input is still focusable, so you
        // could Tab into an invisible terminal and type into it.
        visibility: open ? 'visible' : 'hidden',
      }}
      aria-hidden={!open}
    >
      {/* Drag handle */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize the terminal"
        onMouseDown={() => {
          dragging.current = true;
          document.body.style.cursor = 'ns-resize';
        }}
        className="h-1 w-full cursor-ns-resize bg-transparent hover:bg-brand/30"
      />

      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <IconTerminal size={13} className="text-brand" />
        <span className="text-[12px] font-medium text-ink">Terminal</span>
        {meta && (
          <span className="truncate font-mono text-[10px] text-ink-muted">
            {meta.workspace}
          </span>
        )}
        {meta && !meta.allowlist.length && (
          <span className="flex items-center gap-1 text-[10px] text-warning">
            <IconAlert size={10} /> allowlist empty — everything asks
          </span>
        )}
        <button
          onClick={() => setEntries([])}
          className="ml-auto rounded px-1.5 py-0.5 text-[11px] text-ink-muted hover:bg-surface2"
        >
          Clear
        </button>
        <button
          onClick={onClose}
          aria-label="Close the terminal"
          className="rounded p-1 text-ink-muted hover:bg-surface2 hover:text-ink"
        >
          <IconX size={13} />
        </button>
      </div>

      <div
        className="overflow-y-auto bg-surface2/20 px-3 py-2 font-mono text-[12px]"
        style={{ height: Math.max(0, height - 74) }}
      >
        {!entries.length ? (
          <p className="text-ink-muted">
            Try <code>ls</code> or <code>pwd</code>. No shell — one command at a time.
          </p>
        ) : (
          entries.map((e, i) => (
            <div key={i} className="mb-2">
              <div className="flex items-center gap-2">
                <span className="text-brand">$</span>
                <span className="text-ink">{e.command}</span>
                {e.ran && e.exit_code !== undefined && (
                  <Badge tone={e.exit_code === 0 ? 'success' : 'danger'}>
                    {e.exit_code}
                  </Badge>
                )}
                {e.duration_ms != null && (
                  <span className="text-[10px] text-ink-muted">{e.duration_ms} ms</span>
                )}
              </div>
              {e.error && <div className="text-danger">{e.error}</div>}
              {!e.ran && !e.error && (
                <div className="text-warning">
                  Not run — {e.reason}. Approve it in the Inbox.
                </div>
              )}
              {e.timed_out && <div className="text-warning">Timed out and was killed.</div>}
              {e.stdout && <pre className="whitespace-pre-wrap text-ink">{e.stdout}</pre>}
              {e.stderr && <pre className="whitespace-pre-wrap text-danger">{e.stderr}</pre>}
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>

      <div className="flex items-center gap-2 border-t border-line px-3 py-1.5">
        <span className="font-mono text-[13px] text-brand">$</span>
        <input
          ref={inputRef}
          className="flex-1 border-0 bg-transparent font-mono text-[12px] text-ink outline-none placeholder:text-ink-muted"
          placeholder="Run a command…"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={onKey}
          disabled={busy}
          spellCheck={false}
          aria-label="Command"
        />
        {busy && <Spinner size={12} />}
        {check && (
          <span
            className={cn(
              'shrink-0 text-[10px]',
              check.decision === 'denied'
                ? 'text-danger'
                : check.decision === 'allowed'
                ? 'text-success'
                : 'text-warning'
            )}
          >
            {check.decision === 'denied'
              ? 'refused'
              : check.decision === 'allowed'
              ? 'runs immediately'
              : 'will ask'}
          </span>
        )}
      </div>
    </div>
  );
}

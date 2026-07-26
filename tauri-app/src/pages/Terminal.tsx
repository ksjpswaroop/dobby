import { useEffect, useRef, useState } from 'react';
import { authedFetch } from '../lib/auth';
import { Badge, Button, Card, CardBody, PageHeader, Spinner } from '../components/ui';
import { IconAlert, IconTerminal } from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const BASE = 'http://localhost:8000/api/v1/terminal';

interface Entry {
  command: string;
  stdout?: string;
  stderr?: string;
  exit_code?: number;
  ran: boolean;
  approved?: boolean;
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
  if (!r.ok) throw new Error(j.detail || `Request failed (${r.status})`);
  return j as T;
}

export default function TerminalPage() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [meta, setMeta] = useState<{ allowlist: string[]; workspace: string } | null>(null);
  const [command, setCommand] = useState('');
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<{ decision: string; reason: string } | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    authedFetch(`${BASE}/meta?project_id=${projectId}`)
      .then((r) => r.json())
      .then(setMeta)
      .catch(() => {});
  }, [projectId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [entries]);

  // Tell the user what will happen before they press enter.
  useEffect(() => {
    if (!command.trim()) {
      setCheck(null);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      post<{ decision: string; reason: string }>('/check', { command })
        .then((c) => !cancelled && setCheck(c))
        .catch(() => !cancelled && setCheck(null));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [command]);

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
      if (!r.ran) toast(`Not run — ${r.reason}`, 'error');
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
    <div>
      <PageHeader
        title="Terminal"
        subtitle="Run commands inside this project's workspace. Anything not on the allowlist asks first."
      />

      <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
        <IconAlert size={13} className="text-warning" />
        <span>
          No shell — commands run as a direct process, so pipes, redirects and
          chaining are unavailable by design.
        </span>
        {meta && (
          <>
            <span>·</span>
            <code className="rounded bg-surface2 px-1.5 py-0.5">{meta.workspace}</code>
            <span>·</span>
            <span>
              allowlist:{' '}
              {meta.allowlist.length
                ? meta.allowlist.join(', ')
                : <span className="text-warning">empty — everything asks</span>}
            </span>
          </>
        )}
      </div>

      <Card className="overflow-hidden">
        <div className="max-h-[52vh] min-h-[220px] overflow-y-auto bg-surface2/30 p-4 font-mono text-[12px]">
          {!entries.length ? (
            <p className="text-ink-muted">
              Nothing run yet. Try <code>ls</code> or <code>pwd</code>.
            </p>
          ) : (
            entries.map((e, i) => (
              <div key={i} className="mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-brand">$</span>
                  <span className="text-ink">{e.command}</span>
                  {e.ran && e.exit_code !== undefined && (
                    <Badge tone={e.exit_code === 0 ? 'success' : 'danger'}>
                      exit {e.exit_code}
                    </Badge>
                  )}
                  {e.duration_ms != null && (
                    <span className="text-[10px] text-ink-muted">{e.duration_ms} ms</span>
                  )}
                </div>
                {e.error && <div className="mt-1 text-danger">{e.error}</div>}
                {!e.ran && !e.error && (
                  <div className="mt-1 text-warning">
                    Not run — {e.reason}. Check the Inbox to approve it.
                  </div>
                )}
                {e.timed_out && <div className="mt-1 text-warning">Timed out and was killed.</div>}
                {e.stdout && (
                  <pre className="mt-1 whitespace-pre-wrap text-ink">{e.stdout}</pre>
                )}
                {e.stderr && (
                  <pre className="mt-1 whitespace-pre-wrap text-danger">{e.stderr}</pre>
                )}
              </div>
            ))
          )}
          <div ref={endRef} />
        </div>

        <CardBody className="border-t border-line py-2.5">
          <div className="flex items-center gap-2">
            <span className="font-mono text-brand">$</span>
            <input
              className="input flex-1 border-0 bg-transparent font-mono text-[13px] focus:ring-0"
              placeholder="Type a command and press Enter"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              onKeyDown={onKey}
              disabled={busy}
              spellCheck={false}
              aria-label="Command"
            />
            {busy && <Spinner size={14} />}
            <Button variant="primary" onClick={submit} disabled={!command.trim() || busy}>
              Run
            </Button>
          </div>
          {check && (
            <p
              className={cn(
                'mt-1.5 text-[11px]',
                check.decision === 'denied'
                  ? 'text-danger'
                  : check.decision === 'allowed'
                  ? 'text-success'
                  : 'text-warning'
              )}
            >
              {check.decision === 'denied'
                ? `Refused — ${check.reason}. This cannot be approved.`
                : check.decision === 'allowed'
                ? `Runs immediately — ${check.reason}.`
                : `Will ask for approval — ${check.reason}.`}
            </p>
          )}
        </CardBody>
      </Card>

      <p className="mt-3 flex items-center gap-1.5 text-[11px] text-ink-muted">
        <IconTerminal size={12} />
        Every command is recorded in Logs &amp; Traces. Destructive operations are
        refused outright, with or without approval.
      </p>
    </div>
  );
}

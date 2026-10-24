import { useCallback, useEffect, useState } from 'react';
import { authedFetch } from '../lib/auth';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { Modal } from '../components/Modal';
import { IconAlert, IconPlus, IconServer, IconTrash } from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const BASE = 'http://localhost:8000/api/v1/mcp';

interface Server {
  id: string;
  name: string;
  transport: string;
  command: string;
  args: string[];
  url: string;
  connected: boolean;
  tool_count: number;
}

interface Suggested {
  name: string;
  transport: string;
  command?: string;
  args?: string[];
  url?: string;
  blurb: string;
}

interface Tool {
  name: string;
  description: string;
  server_name: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authedFetch(`${BASE}${path}`, init);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((j as any).detail || `Request failed (${r.status})`);
  return j as T;
}

export default function Connections() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [servers, setServers] = useState<Server[]>([]);
  const [suggested, setSuggested] = useState<Suggested[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: '', transport: 'stdio', command: 'npx',
                                     args: '', url: '' });

  const load = useCallback(async () => {
    try {
      const r = await call<{ servers: Server[]; suggested: Suggested[] }>('/servers');
      setServers(r.servers);
      setSuggested(r.suggested);
      const t = await call<{ tools: Tool[] }>('/tools');
      setTools(t.tools);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not load connections', 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const connect = async (s: Server) => {
    setBusy(s.id);
    try {
      const r = await call<{ connected: boolean; reason?: string; session?: any }>(
        `/servers/${s.id}/connect?project_id=${projectId}`, { method: 'POST' }
      );
      await load();
      if (r.connected) {
        toast(`Connected — ${r.session?.tools?.length ?? 0} tools available`, 'success');
      } else {
        toast(`Not connected — ${r.reason}. Check the Inbox.`, 'error');
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not connect', 'error');
    } finally {
      setBusy(null);
    }
  };

  const act = async (path: string, ok: string) => {
    try {
      await call(path, { method: path.endsWith('disconnect') ? 'POST' : 'DELETE' });
      await load();
      toast(ok, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Failed', 'error');
    }
  };

  const addFrom = async (s: Suggested) => {
    try {
      await call('/servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: s.name, transport: s.transport, command: s.command ?? '',
          args: s.args ?? [], url: s.url ?? '',
        }),
      });
      await load();
      toast(`Added ${s.name}`, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not add', 'error');
    }
  };

  const submit = async () => {
    try {
      await call('/servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          transport: form.transport,
          command: form.command.trim(),
          args: form.args.trim() ? form.args.trim().split(/\s+/) : [],
          url: form.url.trim(),
        }),
      });
      setAdding(false);
      setForm({ name: '', transport: 'stdio', command: 'npx', args: '', url: '' });
      await load();
      toast('Server added', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not add', 'error');
    }
  };

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  const notAdded = suggested.filter(
    (s) => !servers.some((x) => x.name.toLowerCase() === s.name.toLowerCase())
  );

  return (
    <div>
      <PageHeader
        title="Connections"
        subtitle="MCP servers give Dobby new tools. Connecting asks permission first."
        actions={
          <Button variant="primary" icon={<IconPlus size={16} />} onClick={() => setAdding(true)}>
            Add a server
          </Button>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-xl border border-line bg-surface2/40 px-4 py-2.5 text-[12px] text-ink-muted">
        <IconAlert size={14} className="mt-px shrink-0 text-warning" />
        <span>
          A stdio server runs as a process on this machine; an http server receives
          whatever you send it. Registering one is free — <strong>connecting</strong> is
          what asks for approval.
        </span>
      </div>

      {!servers.length ? (
        <Card>
          <EmptyState
            icon={<IconServer size={22} />}
            title="No servers registered"
            description="MCP is the standard way tools plug into AI apps. Add one below and every tool it exposes becomes available to Dobby."
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {servers.map((s) => (
            <Card key={s.id}>
              <CardBody className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">{s.name}</span>
                    <Badge tone={s.connected ? 'success' : 'neutral'}>
                      {s.connected ? `${s.tool_count} tools` : 'not connected'}
                    </Badge>
                    <code className="rounded bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted">
                      {s.transport}
                    </code>
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-ink-muted">
                    {s.transport === 'stdio'
                      ? `${s.command} ${(s.args || []).join(' ')}`
                      : s.url}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {s.connected ? (
                    <Button variant="ghost"
                            onClick={() => act(`/servers/${s.id}/disconnect`, 'Disconnected')}>
                      Disconnect
                    </Button>
                  ) : (
                    <Button variant="secondary" loading={busy === s.id}
                            onClick={() => connect(s)}>
                      Connect
                    </Button>
                  )}
                  <button
                    aria-label={`Remove ${s.name}`}
                    onClick={() => act(`/servers/${s.id}`, 'Removed')}
                    className="rounded-lg p-1.5 text-ink-muted hover:text-danger"
                  >
                    <IconTrash size={14} />
                  </button>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {tools.length > 0 && (
        <>
          <h2 className="mb-2 mt-6 text-[13px] font-semibold text-ink">
            Available tools ({tools.length})
          </h2>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {tools.map((t) => (
              <Card key={`${t.server_name}.${t.name}`}>
                <CardBody className="py-2.5">
                  <div className="flex items-center gap-2">
                    <code className="text-[12px] font-medium text-brand">{t.name}</code>
                    <span className="text-[10px] text-ink-muted">{t.server_name}</span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[11px] text-ink-muted">
                    {t.description}
                  </p>
                </CardBody>
              </Card>
            ))}
          </div>
        </>
      )}

      {notAdded.length > 0 && (
        <>
          <h2 className="mb-2 mt-6 text-[13px] font-semibold text-ink">Suggested</h2>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {notAdded.map((s) => (
              <button
                key={s.name}
                onClick={() => addFrom(s)}
                className="rounded-xl border border-line px-3 py-2.5 text-left transition-colors hover:border-brand hover:bg-brand/5"
              >
                <span className="block text-[13px] font-medium text-ink">{s.name}</span>
                <span className="block text-[11px] text-ink-muted">{s.blurb}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <Modal open={adding} onClose={() => setAdding(false)} title="Add an MCP server">
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink">Name</span>
            <input className="input w-full" value={form.name}
                   onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />
          </label>
          <div className="flex gap-2">
            {['stdio', 'http'].map((t) => (
              <button
                key={t}
                onClick={() => setForm({ ...form, transport: t })}
                aria-pressed={form.transport === t}
                className={cn(
                  'flex-1 rounded-xl border px-3 py-2 text-[13px] transition-colors',
                  form.transport === t ? 'border-brand bg-brand/5 text-brand'
                                       : 'border-line text-ink-muted'
                )}
              >
                {t === 'stdio' ? 'Local process (stdio)' : 'HTTP endpoint'}
              </button>
            ))}
          </div>
          {form.transport === 'stdio' ? (
            <>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-ink">Command</span>
                <input className="input w-full font-mono text-[12px]" value={form.command}
                       onChange={(e) => setForm({ ...form, command: e.target.value })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-ink">Arguments</span>
                <input className="input w-full font-mono text-[12px]"
                       placeholder="-y @modelcontextprotocol/server-memory"
                       value={form.args}
                       onChange={(e) => setForm({ ...form, args: e.target.value })} />
              </label>
            </>
          ) : (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">URL</span>
              <input className="input w-full font-mono text-[12px]"
                     placeholder="http://127.0.0.1:3333/mcp" value={form.url}
                     onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </label>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            <Button variant="primary" disabled={!form.name.trim()} onClick={submit}>
              Add
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

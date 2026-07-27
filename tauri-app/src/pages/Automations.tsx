import { useCallback, useEffect, useState } from 'react';
import {
  automationApi, type ActionKind, type Automation, type AutomationRun, type Preset,
} from '../features/automations/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { Modal } from '../components/Modal';
import {
  IconAlert, IconBolt, IconCheck, IconFlow, IconPlus, IconRefresh, IconTrash,
} from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

function when(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  const mins = Math.round((d.getTime() - Date.now()) / 60000);
  if (mins > 0 && mins < 60) return `in ${mins} min`;
  if (mins < 0 && mins > -60) return `${-mins} min ago`;
  return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

const STATUS_TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = {
  ok: 'success', failed: 'danger', skipped: 'warning', running: 'warning',
};

export default function Automations() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [items, setItems] = useState<Automation[]>([]);
  const [actions, setActions] = useState<ActionKind[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);

  // New-automation form
  const [name, setName] = useState('');
  const [action, setAction] = useState('digest');
  const [cronExpr, setCronExpr] = useState('0 9 * * 1-5');
  const [topic, setTopic] = useState('');
  const [preview, setPreview] = useState<{ description: string; next_run: string | null;
                                           never: boolean } | null>(null);
  const [cronError, setCronError] = useState('');

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

  const load = useCallback(async () => {
    try {
      const r = await automationApi.list(projectId);
      setItems(r.automations);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not load automations', 'error');
    } finally {
      setLoading(false);
    }
  }, [projectId, toast]);

  useEffect(() => {
    load();
    automationApi.meta().then((m) => {
      setActions(m.actions);
      setPresets(m.presets);
    }).catch(() => {});
  }, [load]);

  // A running automation finishes on its own schedule; poll while one is in flight.
  useEffect(() => {
    if (!items.some((a) => a.is_running)) return;
    const t = window.setInterval(load, 4000);
    return () => window.clearInterval(t);
  }, [items, load]);

  // Validate the schedule as it is typed, so a bad cron never reaches Save.
  useEffect(() => {
    if (!creating || !cronExpr.trim()) return;
    let cancelled = false;
    const t = window.setTimeout(() => {
      automationApi.preview(cronExpr, tz)
        .then((p) => { if (!cancelled) { setPreview(p); setCronError(''); } })
        .catch((e) => { if (!cancelled) { setPreview(null); setCronError(e.message); } });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(t); };
  }, [cronExpr, creating, tz]);

  const openRuns = async (id: string) => {
    setOpenId(id);
    try {
      setRuns(await automationApi.runs(id));
      await automationApi.markRead(id);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not load runs', 'error');
    }
  };

  const create = async () => {
    if (!name.trim() || cronError) return;
    setBusy(true);
    try {
      await automationApi.create({
        project_id: projectId, name: name.trim(), action, cron: cronExpr,
        timezone: tz,
        action_config: action === 'research' && topic.trim() ? { topic: topic.trim() } : {},
      });
      setCreating(false);
      setName(''); setTopic('');
      await load();
      toast('Automation scheduled', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not create', 'error');
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      await load();
      toast(ok, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Failed', 'error');
    }
  };

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  const open = items.find((a) => a.id === openId);

  return (
    <div>
      <PageHeader
        title="Automations"
        subtitle="Work that runs on a schedule, whether or not the app is in front of you."
        actions={
          <Button variant="primary" icon={<IconPlus size={16} />} onClick={() => setCreating(true)}>
            New automation
          </Button>
        }
      />

      {!items.length ? (
        <Card>
          <EmptyState
            icon={<IconFlow size={22} />}
            title="Nothing scheduled yet"
            description="Run research every Monday, generate documents for the top backlog feature overnight, or get a digest of what changed each morning."
            action={
              <Button variant="primary" icon={<IconPlus size={16} />} onClick={() => setCreating(true)}>
                Schedule something
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((a) => (
            <Card key={a.id}>
              <CardBody className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium text-ink">{a.name}</span>
                    {a.unread_count > 0 && (
                      <span className="rounded-full bg-brand px-1.5 py-px text-[10px] font-semibold text-white">
                        {a.unread_count}
                      </span>
                    )}
                    {a.is_running && (
                      <span className="flex items-center gap-1 text-[11px] text-warning">
                        <Spinner size={11} /> running
                      </span>
                    )}
                    {!a.enabled && <Badge tone="neutral">paused</Badge>}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                    <span>{a.schedule_text}</span>
                    <span>·</span>
                    <span>next {when(a.next_run)}</span>
                    <span>·</span>
                    <span>{a.run_count} run{a.run_count === 1 ? '' : 's'}</span>
                    {a.last_status && (
                      <Badge tone={STATUS_TONE[a.last_status] ?? 'neutral'}>{a.last_status}</Badge>
                    )}
                  </div>
                  {a.last_error && (
                    <p className="mt-1 flex items-start gap-1 text-[11px] text-danger">
                      <IconAlert size={12} className="mt-px shrink-0" />
                      {a.last_error}
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-1.5">
                  <Button variant="ghost" onClick={() => openRuns(a.id)}>History</Button>
                  <Button
                    variant="ghost"
                    icon={<IconBolt size={14} />}
                    disabled={a.is_running}
                    onClick={() => act(() => automationApi.runNow(a.id), 'Started')}
                  >
                    Run now
                  </Button>
                  <button
                    role="switch"
                    aria-checked={a.enabled}
                    aria-label={a.enabled ? `Pause ${a.name}` : `Resume ${a.name}`}
                    onClick={() =>
                      act(() => automationApi.setEnabled(a.id, !a.enabled),
                          a.enabled ? 'Paused' : 'Resumed')
                    }
                    className={cn(
                      'relative h-5 w-9 shrink-0 rounded-full transition-colors',
                      a.enabled ? 'bg-brand' : 'bg-line'
                    )}
                  >
                    <span
                      className={cn(
                        'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform',
                        a.enabled ? 'translate-x-4' : 'translate-x-0.5'
                      )}
                    />
                  </button>
                  <button
                    aria-label={`Delete ${a.name}`}
                    onClick={() => {
                      if (window.confirm(`Delete “${a.name}”?`)) {
                        act(() => automationApi.remove(a.id), 'Deleted');
                      }
                    }}
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

      {/* Run history */}
      <Modal open={!!openId} onClose={() => setOpenId(null)} title={open?.name ?? 'Run history'}>
        {!runs.length ? (
          <p className="py-6 text-center text-[13px] text-ink-muted">
            This automation hasn't run yet.
          </p>
        ) : (
          <ul className="max-h-[55vh] space-y-2 overflow-y-auto">
            {runs.map((r) => (
              <li key={r.id} className="rounded-xl border border-line px-3 py-2">
                <div className="flex items-center gap-2 text-[11px]">
                  <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{r.status}</Badge>
                  <span className="text-ink-muted">via {r.trigger_source}</span>
                  <span className="text-ink-muted">{when(r.started_at)}</span>
                  {r.duration_ms != null && (
                    <span className="text-ink-muted">{r.duration_ms} ms</span>
                  )}
                </div>
                {r.summary && <p className="mt-1 text-[12px] text-ink">{r.summary}</p>}
                {r.error && <p className="mt-1 text-[12px] text-danger">{r.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </Modal>

      {/* New automation */}
      <Modal open={creating} onClose={() => setCreating(false)} title="New automation">
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink">Name</span>
            <input
              className="input w-full"
              placeholder="Monday market check"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </label>

          <div>
            <span className="mb-1 block text-[12px] font-medium text-ink">What should it do?</span>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setAction(a.id)}
                  aria-pressed={action === a.id}
                  className={cn(
                    'rounded-xl border px-3 py-2 text-left transition-colors',
                    action === a.id ? 'border-brand bg-brand/5' : 'border-line hover:border-brand/50'
                  )}
                >
                  <span className="block text-[13px] font-medium text-ink">{a.label}</span>
                  <span className="block text-[11px] text-ink-muted">{a.blurb}</span>
                </button>
              ))}
            </div>
          </div>

          {action === 'research' && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">
                Research topic <span className="text-ink-muted">(defaults to the name)</span>
              </span>
              <input
                className="input w-full"
                placeholder="Competitor pricing changes"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
              />
            </label>
          )}

          <div>
            <span className="mb-1 block text-[12px] font-medium text-ink">When?</span>
            <div className="mb-1.5 flex flex-wrap gap-1.5">
              {presets.map((p) => (
                <button
                  key={p.cron}
                  onClick={() => setCronExpr(p.cron)}
                  className={cn(
                    'rounded-lg border px-2 py-1 text-[11px] transition-colors',
                    cronExpr === p.cron
                      ? 'border-brand bg-brand/5 text-brand'
                      : 'border-line text-ink-muted hover:border-brand/50'
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <input
              className="input w-full font-mono text-[12px]"
              value={cronExpr}
              onChange={(e) => setCronExpr(e.target.value)}
              aria-label="Cron schedule"
            />
            {cronError ? (
              <p className="mt-1 text-[11px] text-danger">{cronError}</p>
            ) : preview ? (
              <p className="mt-1 text-[11px] text-ink-muted">
                {preview.never ? (
                  <span className="text-warning">This schedule will never fire.</span>
                ) : (
                  <>
                    <IconCheck size={11} className="mr-1 inline text-success" />
                    {preview.description} · first run {when(preview.next_run)}
                  </>
                )}
              </p>
            ) : null}
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button
              variant="primary"
              loading={busy}
              disabled={!name.trim() || !!cronError || preview?.never}
              onClick={create}
            >
              Schedule it
            </Button>
          </div>
        </div>
      </Modal>

      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-ink-muted">
        <IconRefresh size={12} />
        The scheduler runs inside Dobby and checks every 30 seconds. Anything missed while
        the app was closed runs once on startup.
      </p>
    </div>
  );
}

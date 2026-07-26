import { useCallback, useEffect, useState } from 'react';
import { inboxApi, type Ask, type Grant } from '../features/inbox/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { IconAlert, IconCheck, IconControl, IconTrash, IconX } from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const RISK_STYLE: Record<string, string> = {
  high: 'border-danger/40 bg-danger/5',
  medium: 'border-warning/40 bg-warning/5',
  low: 'border-line',
};

const RISK_TONE: Record<string, 'danger' | 'warning' | 'neutral'> = {
  high: 'danger', medium: 'warning', low: 'neutral',
};

const STATE_TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = {
  approved: 'success', denied: 'danger', expired: 'warning',
  cancelled: 'neutral', pending: 'warning',
};

function ago(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return d.toLocaleDateString();
}

export default function Inbox() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [asks, setAsks] = useState<Ask[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'pending' | 'history' | 'grants'>('pending');
  const [busy, setBusy] = useState<string | null>(null);
  const [remember, setRemember] = useState<Set<string>>(new Set());
  const [reply, setReply] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const r = await inboxApi.load(projectId);
      setAsks(r.asks);
      setGrants(r.grants);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not load the inbox', 'error');
    } finally {
      setLoading(false);
    }
  }, [projectId, toast]);

  useEffect(() => {
    // Clear anything stranded by a restart before the first render of the list.
    inboxApi.reconcile(projectId).catch(() => {}).finally(load);
  }, [projectId, load]);

  // Something may be waiting on an answer right now, so poll while any ask is
  // pending — a request raised by a background job should appear without a
  // manual refresh.
  useEffect(() => {
    if (!asks.some((a) => a.state === 'pending')) return;
    const t = window.setInterval(load, 5000);
    return () => window.clearInterval(t);
  }, [asks, load]);

  const decide = async (ask: Ask, approved: boolean) => {
    setBusy(ask.id);
    try {
      const hours = approved && remember.has(ask.id) ? 24 : undefined;
      await inboxApi.answer(ask.id, approved, reply[ask.id] || '', hours);
      await load();
      toast(approved ? (hours ? 'Approved and remembered for 24h' : 'Approved')
                     : 'Denied', approved ? 'success' : 'info');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not record that', 'error');
      await load();
    } finally {
      setBusy(null);
    }
  };

  const pending = asks.filter((a) => a.state === 'pending');
  const history = asks.filter((a) => a.state !== 'pending');

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  return (
    <div>
      <PageHeader
        title="Inbox"
        subtitle="Decisions Dobby is waiting on, and the standing permissions you've granted."
      />

      <div className="mb-4 flex gap-1">
        {([
          ['pending', `Waiting${pending.length ? ` (${pending.length})` : ''}`],
          ['history', 'History'],
          ['grants', `Permissions${grants.length ? ` (${grants.length})` : ''}`],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            aria-pressed={tab === id}
            className={cn(
              'rounded-xl px-3 py-1.5 text-[13px] font-medium transition-colors',
              tab === id ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface2'
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'pending' && (
        !pending.length ? (
          <Card>
            <EmptyState
              icon={<IconCheck size={22} />}
              title="Nothing needs you"
              description="When Dobby wants to do something consequential — reach a third-party service, run a command, send a message — it asks here first."
            />
          </Card>
        ) : (
          <div className="space-y-2">
            {pending.map((a) => (
              <div
                key={a.id}
                className={cn('rounded-2xl border p-4', RISK_STYLE[a.risk] ?? RISK_STYLE.low)}
              >
                <div className="flex items-start gap-2">
                  <IconAlert
                    size={16}
                    className={cn('mt-0.5 shrink-0',
                                  a.risk === 'high' ? 'text-danger' : 'text-warning')}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">{a.title}</span>
                      <Badge tone={RISK_TONE[a.risk] ?? 'neutral'}>{a.risk} risk</Badge>
                      {a.awaited && (
                        <span className="flex items-center gap-1 text-[11px] text-warning">
                          <Spinner size={10} /> something is waiting
                        </span>
                      )}
                    </div>
                    {a.detail && (
                      <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">{a.detail}</p>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                      {a.capability && (
                        <code className="rounded bg-surface2 px-1.5 py-0.5">{a.capability}</code>
                      )}
                      {a.target && <code className="truncate">{a.target}</code>}
                      <span>· from {a.source}</span>
                      <span>· {ago(a.created_at)}</span>
                    </div>

                    <input
                      className="input mt-2.5 w-full py-1.5 text-[12px]"
                      placeholder="Add a note (optional)"
                      value={reply[a.id] ?? ''}
                      onChange={(e) => setReply((p) => ({ ...p, [a.id]: e.target.value }))}
                    />

                    <div className="mt-2.5 flex flex-wrap items-center gap-2">
                      <Button
                        variant="primary"
                        icon={<IconCheck size={15} />}
                        loading={busy === a.id}
                        onClick={() => decide(a, true)}
                      >
                        Approve
                      </Button>
                      <Button
                        variant="secondary"
                        icon={<IconX size={15} />}
                        disabled={busy === a.id}
                        onClick={() => decide(a, false)}
                      >
                        Deny
                      </Button>
                      {a.capability && (
                        <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-ink-muted">
                          <input
                            type="checkbox"
                            checked={remember.has(a.id)}
                            onChange={() =>
                              setRemember((p) => {
                                const n = new Set(p);
                                n.has(a.id) ? n.delete(a.id) : n.add(a.id);
                                return n;
                              })
                            }
                          />
                          Don't ask again for this for 24h
                        </label>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {tab === 'history' && (
        !history.length ? (
          <Card><CardBody className="py-8 text-center text-[13px] text-ink-muted">
            Nothing decided yet.
          </CardBody></Card>
        ) : (
          <div className="space-y-1.5">
            {history.map((a) => (
              <Card key={a.id}>
                <CardBody className="flex items-center gap-3 py-2.5">
                  <Badge tone={STATE_TONE[a.state] ?? 'neutral'}>{a.state}</Badge>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-ink">{a.title}</div>
                    {a.answer && (
                      <div className="truncate text-[11px] text-ink-muted">“{a.answer}”</div>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] text-ink-muted">{ago(a.created_at)}</span>
                </CardBody>
              </Card>
            ))}
          </div>
        )
      )}

      {tab === 'grants' && (
        !grants.length ? (
          <Card>
            <EmptyState
              icon={<IconControl size={22} />}
              title="No standing permissions"
              description="When you approve something and tick “don't ask again”, it appears here — and you can take it back at any time."
            />
          </Card>
        ) : (
          <div className="space-y-1.5">
            {grants.map((g) => (
              <Card key={g.id}>
                <CardBody className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-[13px]">
                      <code className="rounded bg-surface2 px-1.5 py-0.5 text-[11px]">
                        {g.capability}
                      </code>
                      <span className="truncate text-ink">{g.target || '(no target)'}</span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-ink-muted">
                      used {g.use_count} time{g.use_count === 1 ? '' : 's'}
                      {g.last_used_at && ` · last ${ago(g.last_used_at)}`}
                      {g.expires_at ? ' · expires' : ' · until revoked'}
                    </div>
                  </div>
                  <button
                    aria-label={`Revoke ${g.capability} for ${g.target}`}
                    onClick={async () => {
                      await inboxApi.revokeGrant(g.id);
                      await load();
                      toast('Permission revoked', 'success');
                    }}
                    className="shrink-0 rounded-lg p-1.5 text-ink-muted hover:text-danger"
                  >
                    <IconTrash size={14} />
                  </button>
                </CardBody>
              </Card>
            ))}
          </div>
        )
      )}
    </div>
  );
}

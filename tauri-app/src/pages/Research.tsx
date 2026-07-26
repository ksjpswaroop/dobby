import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  researchApi, type Brief, type BriefSummary, type ProposedFeature, type Track,
} from '../features/research/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import {
  IconAlert, IconBacklog, IconCheck, IconPlus, IconResearch, IconTrash,
} from '../lib/icons';
import { cn } from '../lib/cn';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';
import { Modal } from '../components/Modal';

const RUNNING: Brief['status'][] = ['planning', 'researching', 'synthesizing'];

const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  complete: 'success',
  failed: 'danger',
  pending: 'neutral',
};

function statusTone(s: string) {
  return STATUS_TONE[s] ?? 'warning';
}

/**
 * Render a track's markdown well enough to read without pulling in a parser.
 *
 * The generated sections use a deliberately narrow subset — headings, bullets,
 * bold, and tables — so a small renderer covers it. Anything richer belongs in
 * the exported document, not here.
 */
function Markdown({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  const lines = text.split('\n');
  let list: string[] = [];
  let table: string[] = [];

  const flushList = (key: string) => {
    if (!list.length) return;
    blocks.push(
      <ul key={key} className="my-2 space-y-1 pl-4">
        {list.map((l, i) => (
          <li key={i} className="list-disc text-[13px] leading-relaxed text-ink">
            <Inline text={l} />
          </li>
        ))}
      </ul>
    );
    list = [];
  };

  const flushTable = (key: string) => {
    if (table.length < 2) {
      table = [];
      return;
    }
    const rows = table
      .filter((r) => !/^\s*\|?[\s:|-]+\|?\s*$/.test(r))
      .map((r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
    const [head, ...body] = rows;
    blocks.push(
      <div key={key} className="my-3 overflow-x-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr>
              {head.map((c, i) => (
                <th key={i} className="border-b border-line px-2 py-1.5 text-left font-medium text-ink">
                  <Inline text={c} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j} className="border-b border-line/60 px-2 py-1.5 align-top text-ink-muted">
                    <Inline text={c} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    table = [];
  };

  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (line.trim().startsWith('|')) {
      flushList(`l${i}`);
      table.push(line.trim());
      return;
    }
    flushTable(`t${i}`);

    if (/^\s*[-*+]\s+/.test(line)) {
      list.push(line.replace(/^\s*[-*+]\s+/, ''));
      return;
    }
    flushList(`l${i}`);

    const h = /^(#{2,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      blocks.push(
        <h4
          key={i}
          className={cn(
            'mt-4 font-semibold text-ink',
            level <= 2 ? 'text-[15px]' : 'text-[13px] uppercase tracking-wide text-ink-muted'
          )}
        >
          {h[2]}
        </h4>
      );
      return;
    }
    if (line.trim()) {
      blocks.push(
        <p key={i} className="my-2 text-[13px] leading-relaxed text-ink">
          <Inline text={line} />
        </p>
      );
    }
  });
  flushList('lend');
  flushTable('tend');

  return <div>{blocks}</div>;
}

/** Bold and italic only — enough for the generated prose. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_|\*[^*]+\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**'))
          return <strong key={i} className="font-semibold">{p.slice(2, -2)}</strong>;
        if ((p.startsWith('_') && p.endsWith('_')) || (p.startsWith('*') && p.endsWith('*')))
          return <em key={i} className="italic text-ink-muted">{p.slice(1, -1)}</em>;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

/** A finding the model could not back with a source is called out, not hidden. */
function Finding({ content }: { content: string }) {
  const m = /^\[(unverified|inferred|estimated?)]\s*/i.exec(content);
  return (
    <li className="flex gap-2 text-[13px] leading-relaxed">
      {m ? (
        <span
          className="mt-[3px] shrink-0 rounded px-1 py-px text-[10px] font-medium uppercase tracking-wide text-warning ring-1 ring-warning/40"
          title="Not backed by a retrieved source — treat as a lead to verify, not a fact."
        >
          {m[1].toLowerCase()}
        </span>
      ) : (
        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand" />
      )}
      <span className="text-ink">{m ? content.slice(m[0].length) : content}</span>
    </li>
  );
}

export default function Research() {
  const { projectId } = useProject();
  const { toast } = useToast();
  const navigate = useNavigate();

  const [briefs, setBriefs] = useState<BriefSummary[]>([]);
  const [active, setActive] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [topic, setTopic] = useState('');
  const [context, setContext] = useState('');
  const [provider, setProvider] = useState<{ active: string; remote: boolean }>({
    active: 'none', remote: false,
  });
  const [tab, setTab] = useState<string>('summary');
  const [proposals, setProposals] = useState<ProposedFeature[] | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const loadList = useCallback(async () => {
    try {
      setBriefs(await researchApi.list(projectId));
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not load research', 'error');
    } finally {
      setLoading(false);
    }
  }, [projectId, toast]);

  useEffect(() => {
    loadList();
    researchApi.providers().then((p) =>
      setProvider({
        active: p.active,
        remote: !!p.providers.find((x) => x.id === p.active)?.remote,
      })
    ).catch(() => {});
  }, [loadList]);

  const open = useCallback(async (id: string) => {
    try {
      const b = await researchApi.get(id);
      setActive(b);
      setProposals(null);
      setTab(b.summary ? 'summary' : b.tracks[0]?.kind ?? 'summary');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not open that brief', 'error');
    }
  }, [toast]);

  // While a brief is running, re-fetch it so tracks fill in as they finish.
  useEffect(() => {
    if (!active || !RUNNING.includes(active.status)) {
      if (poll.current) window.clearInterval(poll.current);
      return;
    }
    poll.current = window.setInterval(async () => {
      try {
        const b = await researchApi.get(active.id);
        setActive(b);
        if (!RUNNING.includes(b.status)) {
          loadList();
          toast(b.status === 'complete' ? 'Research complete' : 'Research failed',
                b.status === 'complete' ? 'success' : 'error');
        }
      } catch {
        /* transient; the next tick retries */
      }
    }, 4000);
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [active, loadList, toast]);

  const start = async () => {
    if (!topic.trim()) return;
    setBusy(true);
    try {
      const b = await researchApi.create(projectId, topic.trim(), context.trim());
      await researchApi.run(b.id);
      setCreating(false);
      setTopic('');
      setContext('');
      await loadList();
      await open(b.id);
      toast('Research started', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not start research', 'error');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm('Delete this research brief?')) return;
    try {
      await researchApi.remove(id);
      if (active?.id === id) setActive(null);
      await loadList();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not delete', 'error');
    }
  };

  const propose = async () => {
    if (!active) return;
    setBusy(true);
    try {
      const f = await researchApi.proposeFeatures(active.id);
      setProposals(f);
      setPicked(new Set(f.map((_, i) => i)));
      if (!f.length) toast('The model proposed no features', 'error');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not propose features', 'error');
    } finally {
      setBusy(false);
    }
  };

  const accept = async () => {
    if (!active || !proposals) return;
    const chosen = proposals.filter((_, i) => picked.has(i));
    if (!chosen.length) return;
    setBusy(true);
    try {
      const r = await researchApi.acceptFeatures(active.id, chosen);
      toast(`${r.created} feature${r.created === 1 ? '' : 's'} added to the backlog`,
            'success');
      setProposals(null);
      navigate('/backlog');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not add to the backlog', 'error');
    } finally {
      setBusy(false);
    }
  };

  const running = active && RUNNING.includes(active.status);
  const shown: Track | undefined = active?.tracks.find((t) => t.kind === tab);
  const grounded = active?.sources.some((s) => s.kind === 'web');

  return (
    <div>
      <PageHeader
        title="Research"
        subtitle="Understand the product, market, competition, business model, and feasibility — before you build."
        actions={
          <Button variant="primary" icon={<IconPlus size={16} />}
                  onClick={() => setCreating(true)}>
            New research
          </Button>
        }
      />

      {provider.active === 'none' && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/5 px-4 py-2.5 text-[12px] text-ink-muted">
          <IconAlert size={15} className="mt-px shrink-0 text-warning" />
          <span>
            No web search is configured, so research runs on the model's own
            knowledge. Findings it cannot source are tagged{' '}
            <span className="font-medium text-warning">unverified</span> — treat
            those as leads, not facts.{' '}
            <button onClick={() => navigate('/settings')}
                    className="font-medium text-brand hover:underline">
              Configure search
            </button>
          </span>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        {/* Brief list */}
        <Card className="h-fit">
          <CardBody className="p-2">
            {loading ? (
              <div className="flex justify-center py-8"><Spinner size={18} /></div>
            ) : !briefs.length ? (
              <p className="px-2 py-6 text-center text-[12px] text-ink-muted">
                No research yet.
              </p>
            ) : (
              <ul className="space-y-1">
                {briefs.map((b) => (
                  <li key={b.id}>
                    <button
                      onClick={() => open(b.id)}
                      className={cn(
                        'group flex w-full items-start gap-2 rounded-xl px-2.5 py-2 text-left transition-colors',
                        active?.id === b.id ? 'bg-brand/10' : 'hover:bg-surface2'
                      )}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-ink">
                          {b.topic}
                        </span>
                        <Badge tone={statusTone(b.status)}>{b.status}</Badge>
                      </span>
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label={`Delete ${b.topic}`}
                        onClick={(e) => { e.stopPropagation(); remove(b.id); }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { e.stopPropagation(); remove(b.id); }
                        }}
                        className="mt-0.5 rounded p-1 text-ink-muted opacity-0 hover:text-danger group-hover:opacity-100"
                      >
                        <IconTrash size={13} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {/* Reader */}
        {!active ? (
          <Card>
            <EmptyState
              icon={<IconResearch size={22} />}
              title="Research before you build"
              description="Five tracks — product, market, competition, business model, and technical feasibility — then promote the findings straight into your backlog."
              action={
                <Button variant="primary" icon={<IconPlus size={16} />}
                        onClick={() => setCreating(true)}>
                  Start research
                </Button>
              }
            />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="border-b border-line px-5 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-ink">{active.topic}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                    <Badge tone={statusTone(active.status)}>{active.status}</Badge>
                    <span>{grounded ? 'web-sourced' : 'model knowledge'}</span>
                    {active.run_id && (
                      <button onClick={() => navigate('/logs')}
                              className="text-brand hover:underline">
                        view trace
                      </button>
                    )}
                  </div>
                </div>
                {active.status === 'complete' && (
                  <Button variant="secondary" icon={<IconBacklog size={15} />}
                          loading={busy} onClick={propose}>
                    Send to backlog
                  </Button>
                )}
              </div>

              {running && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {active.tracks.map((t) => (
                    <span
                      key={t.kind}
                      className={cn(
                        'rounded-lg px-2 py-0.5 text-[11px]',
                        t.status === 'complete'
                          ? 'bg-success/10 text-success'
                          : t.status === 'researching'
                          ? 'bg-brand/10 text-brand'
                          : t.status === 'failed'
                          ? 'bg-danger/10 text-danger'
                          : 'bg-surface2 text-ink-muted'
                      )}
                    >
                      {t.status === 'researching' && '· '}
                      {t.label}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {active.error && (
              <div role="alert" className="border-b border-danger/30 bg-danger/10 px-5 py-2 text-[12px] text-danger">
                {active.error}
              </div>
            )}

            {/* Track tabs */}
            <div className="flex flex-wrap gap-1 border-b border-line px-3 py-2">
              {active.summary && (
                <button
                  onClick={() => setTab('summary')}
                  aria-pressed={tab === 'summary'}
                  className={cn(
                    'rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors',
                    tab === 'summary' ? 'bg-brand/10 text-brand'
                                      : 'text-ink-muted hover:bg-surface2'
                  )}
                >
                  Summary
                </button>
              )}
              {active.tracks.map((t) => (
                <button
                  key={t.kind}
                  onClick={() => setTab(t.kind)}
                  aria-pressed={tab === t.kind}
                  disabled={t.status === 'pending'}
                  className={cn(
                    'rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-40',
                    tab === t.kind ? 'bg-brand/10 text-brand'
                                   : 'text-ink-muted hover:bg-surface2'
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <CardBody>
              {tab === 'summary' ? (
                active.summary ? (
                  <Markdown text={active.summary} />
                ) : (
                  <p className="py-6 text-center text-[13px] text-ink-muted">
                    {running ? 'Researching…' : 'No summary yet.'}
                  </p>
                )
              ) : !shown ? null : shown.status === 'complete' ? (
                <>
                  <Markdown text={shown.content} />
                  {shown.learnings.length > 0 && (
                    <details className="mt-4 border-t border-line pt-3">
                      <summary className="cursor-pointer text-[12px] font-medium text-ink-muted">
                        {shown.learnings.length} raw findings
                      </summary>
                      <ul className="mt-2 space-y-1.5">
                        {shown.learnings.map((l) => (
                          <Finding key={l.id} content={l.content} />
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              ) : shown.status === 'failed' ? (
                <p className="py-6 text-center text-[13px] text-danger">
                  {shown.error || 'This track produced nothing usable.'}
                </p>
              ) : (
                <div className="flex items-center justify-center gap-2 py-8 text-[13px] text-ink-muted">
                  <Spinner size={16} /> Researching {shown.label.toLowerCase()}…
                </div>
              )}
            </CardBody>
          </Card>
        )}
      </div>

      {/* New research */}
      <Modal open={creating} onClose={() => setCreating(false)} title="New research">
        <div className="space-y-3">
          <div>
            <label htmlFor="r-topic" className="mb-1 block text-[12px] font-medium text-ink">
              What should we research?
            </label>
            <input
              id="r-topic"
              className="input w-full"
              placeholder="A local-first AI notes app for consultants"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="r-ctx" className="mb-1 block text-[12px] font-medium text-ink">
              Anything we should know? <span className="text-ink-muted">(optional)</span>
            </label>
            <textarea
              id="r-ctx"
              className="input h-20 w-full resize-none"
              placeholder="Bootstrapped, targeting the EU, B2B only…"
              value={context}
              onChange={(e) => setContext(e.target.value)}
            />
          </div>
          <p className="text-[11px] text-ink-muted">
            Five tracks run in parallel. This takes a few minutes on a local model.
            {provider.remote && (
              <>
                {' '}Search queries will be sent to{' '}
                <span className="font-medium text-warning">{provider.active}</span>.
              </>
            )}
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!topic.trim()}
                    onClick={start}>
              Start research
            </Button>
          </div>
        </div>
      </Modal>

      {/* Feature proposals */}
      <Modal open={!!proposals} onClose={() => setProposals(null)}
             title="Add findings to the backlog">
        {proposals && (
          <div className="space-y-2">
            <p className="text-[12px] text-ink-muted">
              Each feature traces back to the research. Uncheck anything you don't want.
            </p>
            <ul className="max-h-[45vh] space-y-1.5 overflow-y-auto">
              {proposals.map((f, i) => (
                <li key={i}>
                  <label className="flex cursor-pointer gap-2 rounded-xl border border-line px-3 py-2 hover:border-brand">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={picked.has(i)}
                      onChange={() =>
                        setPicked((p) => {
                          const n = new Set(p);
                          n.has(i) ? n.delete(i) : n.add(i);
                          return n;
                        })
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium text-ink">{f.title}</span>
                      <span className="block text-[12px] text-ink-muted">{f.description}</span>
                      <span className="mt-1 flex gap-2 text-[10px] uppercase tracking-wide text-ink-muted">
                        <span>impact {f.impact}</span>
                        <span>effort {f.effort}</span>
                        <span>risk {f.risk}</span>
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setProposals(null)}>Cancel</Button>
              <Button variant="primary" icon={<IconCheck size={15} />} loading={busy}
                      disabled={!picked.size} onClick={accept}>
                Add {picked.size} to backlog
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

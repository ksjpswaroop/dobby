import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { decisionsApi, type Decision } from '../features/decisions/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { IconScale, IconAlert, IconCheck, IconPlus } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const TABS = [
  { label: 'Open', value: 'open' },
  { label: 'Decided', value: 'decided' },
  { label: 'Superseded', value: 'superseded' },
] as const;

/**
 * The forks work is waiting behind. Ordering is deliberate: overdue, then due
 * soon, then by how much work is blocked — an undated decision holding up
 * three things matters more than a dated one holding up nothing.
 */
export default function Decisions() {
  const { projectId } = useProject();
  const { toast } = useToast();
  const navigate = useNavigate();

  const [tab, setTab] = useState<'open' | 'decided' | 'superseded'>('open');
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [dueOn, setDueOn] = useState('');
  const [optionA, setOptionA] = useState('');
  const [optionB, setOptionB] = useState('');
  const [deciding, setDeciding] = useState<string | null>(null);
  const [rationale, setRationale] = useState('');

  const load = () => {
    setLoading(true);
    decisionsApi.list(projectId, tab)
      .then((r) => setDecisions(r.decisions))
      .catch(() => setDecisions([]))
      .finally(() => setLoading(false));
  };

  useEffect(load, [projectId, tab]);

  const create = async () => {
    if (!title.trim()) return;
    try {
      await decisionsApi.create(projectId, title.trim(), question.trim(),
        dueOn || undefined,
        [optionA, optionB].filter((o) => o.trim()).map((label) => ({ label: label.trim() })));
      setTitle(''); setQuestion(''); setDueOn(''); setOptionA(''); setOptionB('');
      setCreating(false);
      setTab('open');
      load();
      toast('Decision captured', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not create', 'error');
    }
  };

  const decide = async (d: Decision, optionId: string) => {
    try {
      await decisionsApi.decide(d.id, optionId, rationale.trim());
      setDeciding(null);
      setRationale('');
      load();
      toast('Decided — any work waiting on this is released', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not decide', 'error');
    }
  };

  return (
    <div>
      <PageHeader
        title="Decisions"
        subtitle="The forks your work is waiting behind. Deciding one releases everything blocked by it."
        actions={
          <Button variant="primary" icon={<IconPlus size={14} />}
                  onClick={() => setCreating((v) => !v)}>
            New decision
          </Button>
        }
      />

      {creating && (
        <Card className="mb-4">
          <CardBody className="space-y-2.5">
            <input
              value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="What has to be decided? e.g. RAG vs. Structured Reasoning for Verity"
              className="w-full rounded-xl border border-line bg-surface2 px-3.5 py-2.5 text-sm outline-none focus:border-brand/50"
            />
            <textarea
              value={question} onChange={(e) => setQuestion(e.target.value)}
              rows={2} placeholder="Context — what makes this a real fork?"
              className="w-full rounded-xl border border-line bg-surface2 px-3.5 py-2.5 text-[13px] outline-none focus:border-brand/50"
            />
            <div className="grid gap-2 sm:grid-cols-3">
              <input value={optionA} onChange={(e) => setOptionA(e.target.value)}
                     placeholder="Option A"
                     className="rounded-xl border border-line bg-surface2 px-3 py-2 text-[13px] outline-none focus:border-brand/50" />
              <input value={optionB} onChange={(e) => setOptionB(e.target.value)}
                     placeholder="Option B"
                     className="rounded-xl border border-line bg-surface2 px-3 py-2 text-[13px] outline-none focus:border-brand/50" />
              <input type="date" value={dueOn} onChange={(e) => setDueOn(e.target.value)}
                     className="rounded-xl border border-line bg-surface2 px-3 py-2 text-[13px] outline-none focus:border-brand/50" />
            </div>
            <div className="flex gap-2">
              <Button variant="primary" disabled={!title.trim()} onClick={create}>Create</Button>
              <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            </div>
          </CardBody>
        </Card>
      )}

      <div className="mb-4 flex gap-1 rounded-xl bg-surface2 p-1">
        {TABS.map((t) => (
          <button
            key={t.value}
            onClick={() => setTab(t.value)}
            className={`flex-1 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${
              tab === t.value ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner size={20} /></div>
      ) : decisions.length === 0 ? (
        <EmptyState
          icon={<IconScale size={22} />}
          title={tab === 'open' ? 'No open decisions' : `Nothing ${tab}`}
          description={tab === 'open'
            ? 'When something is genuinely a fork — two viable paths and work waiting behind the choice — capture it here.'
            : 'Decisions you settle will show up here with the reasoning you recorded.'}
        />
      ) : (
        <div className="space-y-3">
          {decisions.map((d) => (
            <Card key={d.id}>
              <CardBody>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-[15px] font-semibold leading-snug text-ink">{d.title}</h3>
                    {d.question && (
                      <p className="mt-1 text-[13px] text-ink-muted">{d.question}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    {d.overdue && (
                      <Badge tone="danger">
                        <IconAlert size={10} className="mr-1 inline" />overdue
                      </Badge>
                    )}
                    {!d.overdue && d.due_soon && <Badge tone="warning">due soon</Badge>}
                    {d.due_on && !d.overdue && !d.due_soon && (
                      <Badge tone="neutral">due {d.due_on}</Badge>
                    )}
                    {d.blocking_count > 0 && (
                      <Badge tone="brand">
                        blocking {d.blocking_count}
                      </Badge>
                    )}
                    {d.status === 'decided' && (
                      <Badge tone="success">
                        <IconCheck size={10} className="mr-1 inline" />decided
                      </Badge>
                    )}
                  </div>
                </div>

                <ul className="mt-3 space-y-1.5">
                  {d.options.map((o) => (
                    <li key={o.id}
                        className={`flex items-start gap-2 rounded-xl border px-3 py-2 ${
                          o.chosen ? 'border-success/40 bg-success/5' : 'border-line'
                        }`}>
                      <span className="mt-0.5 text-[11px] text-ink-muted">
                        {o.chosen ? '✓' : '○'}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="text-[13px] text-ink">{o.label}</span>
                        {o.note && (
                          <span className="block text-[11.5px] text-ink-muted">{o.note}</span>
                        )}
                      </span>
                      {d.status === 'open' && deciding === d.id && (
                        <Button variant="secondary" onClick={() => decide(d, o.id)}>
                          Choose
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>

                {d.rationale && (
                  <p className="mt-2.5 border-l-2 border-line pl-3 text-[12.5px] italic text-ink-muted">
                    {d.rationale}
                  </p>
                )}

                {d.status === 'open' && (
                  <div className="mt-3">
                    {deciding === d.id ? (
                      <div className="space-y-2">
                        <textarea
                          value={rationale} onChange={(e) => setRationale(e.target.value)}
                          rows={2}
                          placeholder="Why this one? (recorded permanently)"
                          className="w-full rounded-xl border border-line bg-surface2 px-3 py-2 text-[12.5px] outline-none focus:border-brand/50"
                        />
                        <Button variant="ghost" onClick={() => { setDeciding(null); setRationale(''); }}>
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" disabled={d.options.length === 0}
                                onClick={() => setDeciding(d.id)}>
                          {d.options.length ? 'Decide' : 'Add options first'}
                        </Button>
                        <Button variant="ghost" onClick={() => navigate('/workgraph')}>
                          See it in the graph
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

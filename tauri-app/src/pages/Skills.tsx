import { useEffect, useState } from 'react';
import { skillsApi, type Skill, type SkillRun } from '../features/skills/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { IconSkill, IconCheck, IconX, IconSparkles } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const STEP_LABEL: Record<string, string> = {
  sources: '2 · Sources', intent: '1 · Intent',
  guardrails: '3 · Guardrails', review: '4 · Review',
};

/**
 * Skill Studio. The permissions panel is the important part: it renders
 * straight from the skill's own configuration, so what it says a skill can
 * and cannot do is what the code will actually enforce.
 */
export default function Skills() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const [input, setInput] = useState('');
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<SkillRun | null>(null);

  const load = () => {
    setLoading(true);
    skillsApi.list(projectId)
      .then((r) => {
        setSkills(r.skills);
        setSelected((prev) => r.skills.find((s) => s.id === prev?.id) ?? r.skills[0] ?? null);
      })
      .catch(() => setSkills([]))
      .finally(() => setLoading(false));
  };

  useEffect(load, [projectId]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      load();
      toast(ok, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Failed', 'error');
    }
  };

  const execute = async (simulate: boolean) => {
    if (!selected) return;
    setRunning(true);
    setRun(null);
    try {
      setRun(await skillsApi.run(selected.id, input, simulate));
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Run failed', 'error');
    } finally {
      setRunning(false);
      load();
    }
  };

  if (loading) return <div className="flex justify-center py-16"><Spinner size={20} /></div>;

  if (skills.length === 0) {
    return (
      <div>
        <PageHeader title="Skill Studio" subtitle="Build and refine what Dobby does for you." />
        <EmptyState icon={<IconSkill size={22} />} title="No skills yet"
                    description="Built-in skills seed on startup — restart the backend if this looks empty." />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Skill Studio"
        subtitle="Intent, sources, guardrails, and who approves — one saved thing."
      />

      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        {/* Skill list */}
        <Card className="overflow-hidden">
          <div className="border-b border-line px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            Skills
          </div>
          <ul className="max-h-[64vh] overflow-y-auto p-1.5">
            {skills.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => { setSelected(s); setRun(null); }}
                  className={`w-full rounded-lg px-2.5 py-2 text-left transition-colors ${
                    selected?.id === s.id ? 'bg-brand/10' : 'hover:bg-surface2'
                  }`}
                >
                  <span className={`block truncate text-[12.5px] ${
                    selected?.id === s.id ? 'text-brand' : 'text-ink'}`}>
                    {s.name}
                  </span>
                  <span className="mt-0.5 flex items-center gap-1.5">
                    <Badge tone={s.state === 'published' ? 'success' : 'neutral'}>
                      {s.state}
                    </Badge>
                    {s.builtin && <Badge tone="brand">built-in</Badge>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        {selected && (
          <div className="space-y-4">
            {/* The four steps */}
            <Card>
              <CardBody>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-ink">{selected.name}</h2>
                    <p className="mt-0.5 text-[13px] text-ink-muted">{selected.description}</p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {selected.builtin ? (
                      <Button variant="secondary"
                              onClick={() => act(() => skillsApi.fork(selected.id, projectId),
                                                 'Forked — edit your copy')}>
                        Fork to edit
                      </Button>
                    ) : selected.state === 'draft' ? (
                      <Button variant="primary"
                              onClick={() => act(() => skillsApi.publish(selected.id),
                                                 'Published')}>
                        Publish
                      </Button>
                    ) : null}
                  </div>
                </div>

                <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                      1 · Intent
                    </dt>
                    <dd className="mt-0.5 text-[12.5px] text-ink">{selected.goal || '—'}</dd>
                    <dd className="mt-0.5 text-[11.5px] text-ink-muted">
                      {selected.expected_output}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                      2 · Sources
                    </dt>
                    <dd className="mt-0.5 text-[12.5px] text-ink">
                      {selected.sources.map((s) => s.replace('_', ' ')).join(', ') || 'none'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                      3 · Guardrails
                    </dt>
                    <dd className="mt-0.5 text-[12.5px] text-ink">
                      {selected.rules.join(' · ') || 'none'}
                    </dd>
                    <dd className="mt-0.5 text-[11.5px] text-ink-muted">
                      {selected.local_only ? 'Local data only.' : 'May use the web.'}
                      {selected.max_output_words > 0 &&
                        ` Max ${selected.max_output_words} words.`}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                      4 · Review
                    </dt>
                    <dd className="mt-0.5 text-[12.5px] text-ink">
                      {selected.approval_mode === 'manual'
                        ? 'You approve every external action'
                        : selected.approval_mode.replace('_', ' ')}
                    </dd>
                    <dd className="mt-0.5 text-[11.5px] text-ink-muted">
                      Then: {selected.output_action.replace('_', ' ')}
                    </dd>
                  </div>
                </dl>
              </CardBody>
            </Card>

            {/* Permissions — rendered from config, so it cannot overstate */}
            <Card>
              <CardBody>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  Permissions
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <ul className="space-y-1">
                    {selected.permissions.can.map((c) => (
                      <li key={c} className="flex items-start gap-1.5 text-[12.5px] text-ink">
                        <IconCheck size={13} className="mt-0.5 shrink-0 text-success" />
                        {c}
                      </li>
                    ))}
                  </ul>
                  <ul className="space-y-1">
                    {selected.permissions.cannot.map((c) => (
                      <li key={c} className="flex items-start gap-1.5 text-[12.5px] text-ink-muted">
                        <IconX size={13} className="mt-0.5 shrink-0 text-danger" />
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              </CardBody>
            </Card>

            {/* Run */}
            <Card>
              <CardBody className="space-y-2.5">
                <input
                  value={input} onChange={(e) => setInput(e.target.value)}
                  placeholder="What should this skill work on?"
                  className="w-full rounded-xl border border-line bg-surface2 px-3.5 py-2.5 text-[13px] outline-none focus:border-brand/50"
                />
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" icon={<IconSparkles size={14} />}
                          loading={running} disabled={selected.builtin}
                          onClick={() => execute(true)}>
                    Run simulation
                  </Button>
                  <Button variant="secondary" loading={running}
                          disabled={selected.builtin || selected.state !== 'published'}
                          onClick={() => execute(false)}>
                    Run for real
                  </Button>
                  {selected.builtin && (
                    <span className="self-center text-[11px] text-ink-muted">
                      Fork this built-in before running it.
                    </span>
                  )}
                </div>

                {run && (
                  <div className="mt-2 rounded-xl border border-line p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge tone={run.ok ? 'success' : 'danger'}>
                        {run.ok ? 'ok' : 'failed'}
                      </Badge>
                      {run.simulated && <Badge tone="warning">simulation — nothing written</Badge>}
                      <span className="text-[11px] text-ink-muted">
                        {(run.duration_ms / 1000).toFixed(1)}s
                      </span>
                    </div>
                    <ul className="mb-2 space-y-0.5">
                      {run.trace.map((t) => (
                        <li key={t.step} className="flex items-start gap-2 text-[11.5px]">
                          <span className={t.ok ? 'text-success' : 'text-danger'}>
                            {t.ok ? '✓' : '✗'}
                          </span>
                          <span className="w-24 shrink-0 text-ink-muted">
                            {STEP_LABEL[t.step] ?? t.step}
                          </span>
                          <span className="text-ink">{t.detail}</span>
                        </li>
                      ))}
                    </ul>
                    {run.error && <p className="text-[12px] text-danger">{run.error}</p>}
                    {run.output && (
                      <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface2 p-2.5 text-[11.5px] text-ink">
                        {run.output}
                      </pre>
                    )}
                  </div>
                )}
              </CardBody>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

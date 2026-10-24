import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import api, { WizardStepResult } from '../api/client';
import { Card, Button, PageHeader, Badge, ErrorState, Spinner } from '../components/ui';
import { IconWizard, IconCheck, IconArrowLeft, IconChevronRight, IconGraph } from '../lib/icons';
import { cn } from '../lib/cn';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';

const STEPS = [
  'Feature Spec',
  'User Story',
  'Analysis',
  'Flowchart',
  'Pseudocode',
  'TDD Tests',
  'Documentation',
];

export default function Wizard() {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const { projectId } = useProject();

  const [started, setStarted] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [featureTitle, setFeatureTitle] = useState('');
  const [featureDescription, setFeatureDescription] = useState('');

  const [currentStep, setCurrentStep] = useState(1); // step about to be / just generated
  const [results, setResults] = useState<WizardStepResult[]>([]);
  const [active, setActive] = useState<WizardStepResult | null>(null);
  const [acceptedDraft, setAcceptedDraft] = useState(false);
  const [userEdit, setUserEdit] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // Prefill from ?feature=
  useEffect(() => {
    const feature = new URLSearchParams(location.search).get('feature');
    if (feature) setFeatureTitle(feature);
  }, [location.search]);

  const handleStart = async () => {
    if (!featureTitle.trim() || !featureDescription.trim()) {
      toast('Enter a title and description', 'error');
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const result = await api.startWizard(projectId, featureTitle, featureDescription);
      if (result.success) {
        setSessionId(result.session_id);
        setStarted(true);
      } else {
        setError('Failed to start wizard session');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start wizard');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async (force = false) => {
    if (!sessionId) return;
    try {
      setLoading(true);
      setError(null);
      // When forcing, keep the currently shown draft content instead of
      // regenerating, so "Use anyway" accepts exactly what the user sees.
      const edit = force ? active?.content ?? userEdit : userEdit;
      const result = await api.executeWizardStep(sessionId, edit || undefined, force);
      setActive(result);
      setAcceptedDraft(force && !result.passed);
      setResults((prev) => [...prev.filter((r) => r.step !== result.step), result]);
      setCurrentStep(result.step);
      setUserEdit('');
      if ((result.passed || force) && result.step >= 7) setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate step');
    } finally {
      setLoading(false);
    }
  };

  const handleContinue = () => {
    setActive(null);
    setAcceptedDraft(false);
    setCurrentStep((s) => Math.min(s + 1, 7));
  };

  /* ----------------------------------------------------------------------- */
  /* Start screen                                                            */
  /* ----------------------------------------------------------------------- */
  if (!started) {
    return (
      <div className="mx-auto max-w-2xl">
        <PageHeader title="Wizard" subtitle="Guided generation with a verification gate at every step." />
        {error && <ErrorState message={error} onRetry={() => setError(null)} />}
        <Card className="mt-2 p-6">
          <div className="mb-5 flex items-start gap-3 rounded-xl bg-brand/5 p-4 text-sm text-ink-muted">
            <IconWizard size={18} className="mt-0.5 shrink-0 text-brand" />
            <p>
              Dobby generates seven artifacts in sequence — spec, story, analysis, flowchart,
              pseudocode, tests and docs. Each is verified before you continue.
            </p>
          </div>
          <div className="space-y-4">
            <div>
              <label className="label">Feature title</label>
              <input
                className="input"
                value={featureTitle}
                onChange={(e) => setFeatureTitle(e.target.value)}
                placeholder="e.g., Smart action-item detection"
              />
            </div>
            <div>
              <label className="label">Feature description</label>
              <textarea
                className="input"
                rows={4}
                value={featureDescription}
                onChange={(e) => setFeatureDescription(e.target.value)}
                placeholder="Describe the feature in detail…"
              />
            </div>
            <div className="flex gap-2 pt-1">
              <Button variant="primary" loading={loading} onClick={handleStart} className="flex-1">
                Start wizard
              </Button>
              <Button variant="ghost" icon={<IconArrowLeft size={16} />} onClick={() => navigate('/')}>
                Back
              </Button>
            </div>
          </div>
        </Card>
      </div>
    );
  }

  /* ----------------------------------------------------------------------- */
  /* Completion screen                                                       */
  /* ----------------------------------------------------------------------- */
  if (done) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card className="p-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-success/10 text-success">
            <IconCheck size={28} />
          </div>
          <h2 className="text-xl font-semibold">Wizard complete</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">
            All seven steps passed verification. Your feature documentation is saved to the graph.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <Button variant="secondary" onClick={() => navigate('/')}>
              Dashboard
            </Button>
            <Button variant="primary" icon={<IconGraph size={16} />} onClick={() => navigate('/graph')}>
              View graph
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  /* ----------------------------------------------------------------------- */
  /* Step screen                                                             */
  /* ----------------------------------------------------------------------- */
  const completedCount = results.filter((r) => r.passed).length;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Wizard"
        subtitle={featureTitle}
        actions={<Badge tone="brand">{completedCount} / 7 done</Badge>}
      />

      {/* Progress rail */}
      <div className="mb-6 flex gap-1.5">
        {STEPS.map((name, i) => {
          const step = i + 1;
          const passed = results.find((r) => r.step === step)?.passed;
          return (
            <div key={name} className="flex-1">
              <div
                className={cn(
                  'h-1.5 rounded-full transition-colors',
                  passed ? 'bg-success' : step === currentStep ? 'bg-brand' : 'bg-surface2'
                )}
              />
              <span
                className={cn(
                  'mt-1.5 hidden text-[10px] sm:block',
                  step === currentStep ? 'font-medium text-ink' : 'text-ink-muted'
                )}
              >
                {name}
              </span>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-semibold">
            Step {currentStep}: {STEPS[currentStep - 1]}
          </h2>
          {active && (
            <Badge tone={active.passed ? 'success' : acceptedDraft ? 'warning' : 'danger'}>
              {acceptedDraft ? 'Draft · ' : ''}Score {Math.round(active.verification_score)}
            </Badge>
          )}
        </div>

        <div className="p-5">
          {/* Content area */}
          {loading ? (
            <div className="flex flex-col items-center gap-3 py-16 text-ink-muted">
              <Spinner size={26} className="text-brand" />
              <span className="text-sm">Generating {STEPS[currentStep - 1]}…</span>
            </div>
          ) : active ? (
            <pre
              data-selectable
              className="max-h-[46vh] overflow-auto whitespace-pre-wrap rounded-xl bg-surface2 p-4 font-mono text-[13px] leading-relaxed text-ink"
            >
              {active.content || '(No content returned.)'}
            </pre>
          ) : (
            <div className="rounded-xl border border-dashed border-line py-14 text-center text-sm text-ink-muted">
              Ready to generate <span className="font-medium text-ink">{STEPS[currentStep - 1]}</span>.
            </div>
          )}

          {/* Edit box (shown before generating or to retry a failed step) */}
          {(!active || (!active.passed && !acceptedDraft)) && (
            <div className="mt-4">
              <label className="label">Optional guidance for this step</label>
              <textarea
                className="input"
                rows={2}
                value={userEdit}
                onChange={(e) => setUserEdit(e.target.value)}
                placeholder="Add requirements or corrections…"
              />
            </div>
          )}

          {/* Actions */}
          <div className="mt-4 flex gap-2">
            {!active && (
              <Button variant="primary" loading={loading} onClick={() => handleGenerate(false)} className="flex-1">
                Generate {STEPS[currentStep - 1]}
              </Button>
            )}
            {active && !active.passed && !acceptedDraft && (
              <>
                <Button variant="primary" loading={loading} onClick={() => handleGenerate(false)} className="flex-1">
                  Regenerate
                </Button>
                <Button
                  variant="secondary"
                  loading={loading}
                  onClick={() => handleGenerate(true)}
                  title="Accept this draft despite the low score and continue"
                >
                  Use anyway
                </Button>
              </>
            )}
            {active && (active.passed || acceptedDraft) && active.step < 7 && (
              <Button
                variant="primary"
                icon={<IconChevronRight size={16} />}
                onClick={handleContinue}
                className="flex-1"
              >
                Continue to {STEPS[active.step]}
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

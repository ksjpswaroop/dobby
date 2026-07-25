import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import api, { YoloGenerationResult } from '../api/client';
import { Card, Button, PageHeader, ScoreRing, Spinner, ErrorState } from '../components/ui';
import { IconBolt, IconArrowLeft, IconCheck, IconX, IconGraph } from '../lib/icons';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';

const ARTIFACTS: { key: string; label: string }[] = [
  { key: 'feature_spec', label: 'Feature specification' },
  { key: 'user_story', label: 'User story' },
  { key: 'functional_analysis', label: 'Functional analysis' },
  { key: 'flowchart', label: 'Flowchart' },
  { key: 'pseudocode', label: 'Pseudocode' },
  { key: 'tdd_tests', label: 'TDD tests' },
  { key: 'documentation', label: 'Documentation' },
];

export default function Yolo() {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const { projectId } = useProject();

  const [featureTitle, setFeatureTitle] = useState('');
  const [featureDescription, setFeatureDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<YoloGenerationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const feature = new URLSearchParams(location.search).get('feature');
    if (feature) setFeatureTitle(feature);
  }, [location.search]);

  const handleGenerate = async () => {
    if (!featureTitle.trim() || !featureDescription.trim()) {
      toast('Enter a title and description', 'error');
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setResult(await api.generateYolo(projectId, featureTitle, featureDescription));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate');
    } finally {
      setLoading(false);
    }
  };

  const handleAccept = async () => {
    if (!result?.feature_node_id) return;
    try {
      setLoading(true);
      await api.acceptYoloGeneration(projectId, result.feature_node_id);
      toast('Generation accepted and saved', 'success');
      navigate('/graph');
    } catch {
      toast('Failed to accept generation', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleReject = () => {
    setResult(null);
    setError(null);
  };

  /* Generating state */
  if (loading && !result) {
    return (
      <div className="mx-auto max-w-lg">
        <Card className="p-8 text-center">
          <Spinner size={30} className="mx-auto text-accent" />
          <h2 className="mt-4 text-lg font-semibold">Generating all seven artifacts…</h2>
          <p className="mt-1 text-sm text-ink-muted">This usually takes 2–5 minutes.</p>
          <div className="mt-6 space-y-2 text-left">
            {ARTIFACTS.map((a) => (
              <div key={a.key} className="flex items-center gap-3 rounded-lg bg-surface2 px-3 py-2 text-sm">
                <Spinner size={14} className="text-accent" />
                {a.label}
              </div>
            ))}
          </div>
        </Card>
      </div>
    );
  }

  /* Result state */
  if (result) {
    return (
      <div className="mx-auto max-w-2xl">
        <PageHeader title="YOLO result" subtitle={featureTitle} />
        <Card className="p-6">
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
            <ScoreRing score={result.verification_score} />
            <div className="flex-1 text-center sm:text-left">
              <h2 className="text-lg font-semibold">
                {result.passed ? 'Passed verification' : 'Below threshold'}
              </h2>
              <p className="mt-1 text-sm text-ink-muted">
                {result.passed
                  ? 'All artifacts met the ≥85 quality bar and are ready to save.'
                  : 'Some artifacts scored under 85. You can reject and regenerate.'}
              </p>
              {result.error && <p className="mt-2 text-sm text-danger">{result.error}</p>}
            </div>
          </div>

          <div className="mt-6 space-y-2">
            <h3 className="text-sm font-semibold text-ink-muted">Generated artifacts</h3>
            {ARTIFACTS.map((a) => {
              const content = result.all_content?.[a.key];
              return (
                <details key={a.key} className="group rounded-xl border border-line bg-surface2/50">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm font-medium">
                    <IconCheck size={15} className="text-success" />
                    {a.label}
                    <span className="ml-auto text-xs text-ink-muted group-open:hidden">Show</span>
                    <span className="ml-auto hidden text-xs text-ink-muted group-open:inline">Hide</span>
                  </summary>
                  {content && (
                    <pre
                      data-selectable
                      className="max-h-[40vh] overflow-auto whitespace-pre-wrap border-t border-line px-4 py-3 font-mono text-[12.5px] leading-relaxed text-ink"
                    >
                      {content}
                    </pre>
                  )}
                </details>
              );
            })}
          </div>
        </Card>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="success"
            icon={<IconCheck size={16} />}
            loading={loading}
            disabled={!result.passed}
            onClick={handleAccept}
            className="flex-1"
          >
            Accept &amp; save
          </Button>
          <Button variant="danger" icon={<IconX size={16} />} onClick={handleReject} className="flex-1">
            Reject
          </Button>
          <Button variant="secondary" icon={<IconGraph size={16} />} onClick={() => navigate('/graph')}>
            View graph
          </Button>
        </div>
      </div>
    );
  }

  /* Start form */
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="YOLO" subtitle="Generate everything in one pass, then review." />
      {error && <ErrorState message={error} onRetry={() => setError(null)} />}
      <Card className="mt-2 p-6">
        <div className="mb-5 flex items-start gap-3 rounded-xl bg-warning/10 p-4 text-sm text-ink-muted">
          <IconBolt size={18} className="mt-0.5 shrink-0 text-warning" />
          <p>
            YOLO generates all seven artifacts without stopping for review. It's fast, but check the
            output before accepting.
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
            <Button variant="primary" icon={<IconBolt size={16} />} onClick={handleGenerate} className="flex-1">
              Generate instantly
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

import { useState } from 'react';
import api, { BulkResponse } from '../api/client';
import { Card, Button, PageHeader, Spinner, ErrorState } from '../components/ui';
import { cn } from '../lib/cn';
import { IconBolt } from '../lib/icons';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';

const DOCS = [
  { key: 'feature_spec', label: 'Spec' },
  { key: 'user_story', label: 'Story' },
  { key: 'functional_analysis', label: 'Analysis' },
  { key: 'flowchart', label: 'Flow' },
  { key: 'pseudocode', label: 'Pseudo' },
  { key: 'tdd_tests', label: 'Tests' },
  { key: 'documentation', label: 'Docs' },
];

const PLACEHOLDER = `One idea per line. Optional description after a "|".

Dark mode | Toggle light/dark theme with persistence
CSV import | Bulk import records with validation
Two-factor auth`;

function parseIdeas(text: string): { title: string; description: string }[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [title, ...rest] = line.split('|');
      return { title: title.trim(), description: rest.join('|').trim() };
    })
    .filter((i) => i.title);
}

function Cell({ present, passed, score }: { present: boolean; passed: boolean; score: number }) {
  const tone = !present ? 'missing' : passed ? 'pass' : 'weak';
  return (
    <td className="px-2 py-2 text-center">
      <span
        title={present ? `score ${score}` : 'missing'}
        className={cn(
          'inline-flex h-6 min-w-[2.2rem] items-center justify-center rounded-md text-[11px] font-semibold',
          tone === 'pass' && 'bg-success/15 text-success',
          tone === 'weak' && 'bg-warning/15 text-warning',
          tone === 'missing' && 'bg-danger/15 text-danger'
        )}
      >
        {present ? Math.round(score) : '—'}
      </span>
    </td>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={cn('mt-1 text-2xl font-semibold', tone)}>{value}</p>
    </Card>
  );
}

export default function Bulk() {
  const { toast } = useToast();
  const { projectId } = useProject();
  const [text, setText] = useState('');
  const [concurrency, setConcurrency] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkResponse | null>(null);

  const ideas = parseIdeas(text);

  const run = async () => {
    if (ideas.length === 0) {
      toast('Enter at least one idea', 'error');
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setResult(null);
      setResult(await api.generateBulk(ideas, concurrency, projectId));
      toast('Bulk generation complete', 'success');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk generation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Bulk generate"
        subtitle="Generate all 7 documents for many ideas at once — a full-coverage run."
      />

      {!loading && (
        <Card className="p-5">
          <label className="label">Ideas</label>
          <textarea
            className="input font-mono text-[13px]"
            rows={7}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={PLACEHOLDER}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm text-ink-muted">
              {ideas.length} idea{ideas.length !== 1 ? 's' : ''} · {ideas.length * 7} documents
            </span>
            <div className="flex items-center gap-2">
              <label className="text-sm text-ink-muted">Concurrency</label>
              <select
                className="input w-auto py-2"
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
              >
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <Button variant="primary" icon={<IconBolt size={16} />} onClick={run}>
                Generate all
              </Button>
            </div>
          </div>
        </Card>
      )}

      {loading && (
        <Card className="p-10 text-center">
          <Spinner size={30} className="mx-auto text-brand" />
          <h2 className="mt-4 text-lg font-semibold">
            Generating {ideas.length} ideas × 7 documents…
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            Running up to {concurrency} in parallel on the local model. This can take a while.
          </p>
        </Card>
      )}

      {error && <ErrorState message={error} onRetry={run} />}

      {result && !loading && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Ideas OK" value={`${result.ideas_ok}/${result.total_ideas}`} />
            <Stat
              label="Documents generated"
              value={`${result.documents_generated}/${result.documents_expected}`}
              tone={
                result.documents_generated === result.documents_expected
                  ? 'text-success'
                  : 'text-warning'
              }
            />
            <Stat
              label="Passed verification"
              value={`${result.documents_passed}/${result.documents_expected}`}
              tone="text-brand"
            />
            <Stat
              label="Gaps"
              value={String(result.gaps.length)}
              tone={result.gaps.length ? 'text-danger' : 'text-success'}
            />
          </div>

          <Card className="overflow-hidden">
            <div className="border-b border-line px-5 py-3 text-sm font-semibold">
              Coverage matrix
              <span className="ml-2 font-normal text-ink-muted">
                (number = verification score; — = missing)
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-ink-muted">
                    <th className="px-4 py-2 text-left font-medium">Idea</th>
                    {DOCS.map((d) => (
                      <th key={d.key} className="px-2 py-2 text-center font-medium">
                        {d.label}
                      </th>
                    ))}
                    <th className="px-3 py-2 text-center font-medium">Overall</th>
                  </tr>
                </thead>
                <tbody>
                  {result.results.map((r) => (
                    <tr key={r.title} className="border-b border-line last:border-0">
                      <td className="max-w-[220px] truncate px-4 py-2 font-medium" title={r.title}>
                        {r.title}
                        {r.error && <span className="ml-2 text-xs text-danger">{r.error}</span>}
                      </td>
                      {DOCS.map((d) => {
                        const doc = r.documents.find((x) => x.name === d.key);
                        return (
                          <Cell
                            key={d.key}
                            present={!!doc?.present}
                            passed={!!doc?.passed}
                            score={doc?.score ?? 0}
                          />
                        );
                      })}
                      <td className="px-3 py-2 text-center">
                        <span
                          className={cn(
                            'font-semibold',
                            r.overall_passed ? 'text-success' : 'text-warning'
                          )}
                        >
                          {Math.round(r.overall_score)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {result.gaps.length > 0 && (
            <Card className="p-5">
              <h3 className="mb-2 text-sm font-semibold text-danger">Gaps (missing documents)</h3>
              <ul className="space-y-1 text-sm text-ink-muted">
                {result.gaps.map((g) => (
                  <li key={g.idea}>
                    <span className="font-medium text-ink">{g.idea}</span>: {g.missing.join(', ')}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

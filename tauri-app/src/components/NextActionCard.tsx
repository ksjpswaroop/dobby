import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { copilotApi, type NextAction } from '../features/copilot/api';
import { Badge, Button, Card } from './ui';
import { IconSparkles } from '../lib/icons';
import { useProject } from '../lib/project';

/**
 * The single most valuable next step. The *reason* is always deterministic —
 * computed from pending approvals, failed runs, untriaged captures, Pareto
 * scores — and only the wording is model-phrased. A recommendation whose
 * justification is invented is one you learn to ignore.
 */
export function NextActionCard() {
  const { projectId } = useProject();
  const navigate = useNavigate();
  const [data, setData] = useState<NextAction | null>(null);

  useEffect(() => {
    copilotApi.nextAction(projectId).then(setData).catch(() => setData(null));
  }, [projectId]);

  if (!data?.suggestion) return null;
  const s = data.suggestion;

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 px-5 py-4">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
          <IconSparkles size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-ink">Do this next</p>
            {!data.phrased_by_model && (
              <Badge tone="neutral" className="text-[10px]">computed</Badge>
            )}
          </div>
          <p className="mt-0.5 text-[13px] text-ink">{data.message}</p>
          <p className="mt-0.5 text-[11px] text-ink-muted">{s.reason}</p>

          {data.alternatives.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.alternatives.map((a) => (
                <button
                  key={a.kind}
                  onClick={() => navigate(a.route)}
                  className="chip bg-surface2 text-ink-muted hover:text-brand"
                >
                  {a.title}
                </button>
              ))}
            </div>
          )}
        </div>
        <Button variant="primary" onClick={() => navigate(s.route)}>
          Go
        </Button>
      </div>
    </Card>
  );
}

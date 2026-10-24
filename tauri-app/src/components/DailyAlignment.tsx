import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { copilotApi, type NextAction } from '../features/copilot/api';
import { planningApi } from '../features/planning/api';
import { Badge, Button } from './ui';
import { IconChevronRight } from '../lib/icons';
import { useProject } from '../lib/project';

interface Home {
  greeting: string;
  user_name: string;
  today: string;
  clear: boolean;
}

interface Block {
  feature_id: string | null;
  title: string;
  kind: string;
  start: string;
  end: string;
  minutes: number;
  partial?: boolean;
  why?: string;
}

interface Schedule {
  blocks: Block[];
  utilisation: number;
  capacity_human: string;
  not_today: { title: string }[];
}

const KIND_LABEL: Record<string, string> = {
  deep_work: 'Focus', admin: 'Admin', collaboration: 'Together', break: '',
};

/**
 * The opening screen: today's date, a greeting, the one outcome that matters,
 * and the plan that serves it.
 *
 * The outcome is the *computed* next-best-action rather than a field someone
 * types. A "today's outcome" you have to write yourself is one more empty box
 * to face at 9am; one derived from what is actually blocking you is a claim
 * the app can stand behind.
 */
export function DailyAlignment() {
  const { projectId } = useProject();
  const navigate = useNavigate();

  const [home, setHome] = useState<Home | null>(null);
  const [action, setAction] = useState<NextAction | null>(null);
  const [schedule, setSchedule] = useState<Schedule | null>(null);

  useEffect(() => {
    planningApi.today(projectId).then(setHome).catch(() => setHome(null));
    copilotApi.nextAction(projectId, false).then(setAction).catch(() => setAction(null));
    planningApi.planDay(projectId).then(setSchedule).catch(() => setSchedule(null));
  }, [projectId]);

  const work = (schedule?.blocks ?? []).filter((b) => b.kind !== 'break');

  return (
    <section>
      {home?.today && (
        <p className="text-[12px] text-ink-muted">{home.today}</p>
      )}

      <h1 className="display mt-1.5 text-[40px] leading-[1.08] text-ink">
        {home?.greeting ?? 'Hello'}
        {home?.user_name ? `, ${home.user_name}` : ''}
      </h1>

      {/* Today's outcome */}
      {action?.suggestion && (
        <div className="mt-8">
          <p className="eyebrow">Today's outcome</p>
          <div className="rule-accent mt-3">
            <h2 className="display text-[24px] leading-snug text-ink">
              {action.suggestion.title}
            </h2>
            <p className="mt-2 max-w-xl text-[13px] leading-relaxed text-ink-muted">
              {action.suggestion.reason}
            </p>
            <Button
              variant="ghost"
              className="mt-2 -ml-3"
              onClick={() => navigate(action.suggestion!.route)}
            >
              Go there <IconChevronRight size={14} />
            </Button>
          </div>
        </div>
      )}

      {/* Prioritized plan */}
      {work.length > 0 && (
        <div className="mt-9">
          <div className="flex items-baseline justify-between gap-3">
            <p className="eyebrow">Prioritized plan</p>
            {schedule && (
              <p className="text-[11px] text-ink-muted">
                {schedule.utilisation}% of {schedule.capacity_human}
              </p>
            )}
          </div>

          <ul className="mt-3 divide-y divide-line border-t border-line">
            {work.map((b, i) => (
              <li key={`${b.title}-${i}`}>
                <button
                  onClick={() => navigate(b.feature_id ? '/board' : '/')}
                  className="group flex w-full items-start gap-5 py-4 text-left"
                >
                  <span className="plan-numeral mt-0.5 w-5 shrink-0">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-[15px] font-medium text-ink">{b.title}</span>
                      {i === 0 && <Badge tone="brand">Most important</Badge>}
                      {b.partial && <Badge tone="neutral">first block</Badge>}
                    </span>
                    {b.why && (
                      <span className="mt-1 block text-[12px] leading-relaxed text-ink-muted">
                        {b.why}
                      </span>
                    )}
                    <span className="mt-1.5 flex items-center gap-2 text-[11px] text-ink-muted">
                      <span className="tabular-nums">{b.start} – {b.end}</span>
                      {KIND_LABEL[b.kind] && <span>· {KIND_LABEL[b.kind]}</span>}
                    </span>
                  </span>
                  <IconChevronRight
                    size={15}
                    className="mt-1 shrink-0 text-ink-muted/40 transition-colors group-hover:text-ink-muted"
                  />
                </button>
              </li>
            ))}
          </ul>

          {schedule && schedule.not_today.length > 0 && (
            <p className="mt-3 text-[11px] text-ink-muted">
              {schedule.not_today.length} more ready, but the day is full.
            </p>
          )}
        </div>
      )}

      {work.length === 0 && home?.clear && (
        <p className="mt-8 max-w-lg text-[13px] leading-relaxed text-ink-muted">
          Nothing is waiting on you. Capture an idea, or pick something from the
          backlog to shape the day around.
        </p>
      )}
    </section>
  );
}

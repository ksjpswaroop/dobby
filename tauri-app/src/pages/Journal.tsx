import { useEffect, useState } from 'react';
import { journalApi, type JournalEntry } from '../features/journal/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { renderMarkdown } from '../lib/markdown';
import { IconNotes, IconSparkles } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const today = () => new Date().toISOString().slice(0, 10);

/**
 * A dated reflection, not a second capture inbox — Ideas already owns
 * frictionless capture. The draft button is the point: writing an entry from
 * a blank page is the habit everyone abandons; correcting one assembled from
 * the day you actually had is one people keep.
 */
export default function Journal() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [streak, setStreak] = useState<{ current_streak: number; entries: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [drafting, setDrafting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [body, setBody] = useState('');
  const [date, setDate] = useState(today());

  const load = () => {
    setLoading(true);
    journalApi.list(projectId)
      .then((r) => {
        setEntries(r.entries);
        const existing = r.entries.find((e) => e.entry_date === date);
        setBody(existing?.body ?? '');
      })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
    journalApi.streak(projectId).then(setStreak).catch(() => setStreak(null));
  };

  useEffect(load, [projectId, date]);

  const draft = async () => {
    setDrafting(true);
    try {
      const d = await journalApi.autoDraft(projectId, false, date);
      setBody(d.body);
      toast(d.event_count
        ? `Drafted from ${d.event_count} things that happened`
        : 'Nothing recorded that day — over to you', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not draft', 'error');
    } finally {
      setDrafting(false);
    }
  };

  const save = async () => {
    if (!body.trim()) return;
    setSaving(true);
    try {
      await journalApi.write(projectId, body, date, `Journal — ${date}`);
      load();
      toast('Saved', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Journal"
        subtitle="What happened, and what you learned."
        actions={streak && (
          <span className="text-[12px] text-ink-muted">
            {streak.current_streak > 0
              ? `${streak.current_streak}-day writing streak`
              : `${streak.entries} entries`}
          </span>
        )}
      />

      <Card className="mb-5">
        <CardBody className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date" value={date} onChange={(e) => setDate(e.target.value)}
              className="rounded-xl border border-line bg-surface2 px-3 py-1.5 text-[13px] outline-none focus:border-brand/50"
            />
            <Button variant="ghost" icon={<IconSparkles size={14} />}
                    loading={drafting} onClick={draft}>
              Draft from my day
            </Button>
            <span className="text-[11px] text-ink-muted">
              Assembled from what you actually did — nothing invented.
            </span>
          </div>
          <textarea
            value={body} onChange={(e) => setBody(e.target.value)}
            rows={12}
            placeholder="What happened today? What went well? What was hard?"
            className="w-full rounded-xl border border-line bg-surface2 p-3.5 font-mono text-[12.5px] leading-relaxed outline-none focus:border-brand/50"
          />
          <Button variant="primary" loading={saving} disabled={!body.trim()}
                  onClick={save}>
            Save entry
          </Button>
        </CardBody>
      </Card>

      {loading ? (
        <div className="flex justify-center py-10"><Spinner size={20} /></div>
      ) : entries.length === 0 ? (
        <EmptyState
          icon={<IconNotes size={22} />}
          title="Nothing written yet"
          description="Use “Draft from my day” to start from what actually happened, then say what it meant."
        />
      ) : (
        <div className="space-y-3">
          {entries.map((e) => (
            <Card key={e.id}>
              <CardBody>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold text-ink">{e.entry_date}</span>
                  {e.auto_drafted && <Badge tone="warning">draft — not yet edited</Badge>}
                  {e.highlights.map((h) => (
                    <Badge key={h} tone="neutral">{h}</Badge>
                  ))}
                  <button
                    onClick={() => { setDate(e.entry_date); setBody(e.body); }}
                    className="ml-auto text-[11px] text-brand hover:underline"
                  >
                    Edit
                  </button>
                </div>
                <div
                  className="text-[13px] text-ink"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(e.body).html }}
                />
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

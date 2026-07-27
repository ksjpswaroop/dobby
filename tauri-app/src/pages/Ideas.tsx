import { useEffect, useState } from 'react';
import { ideasApi, type Idea, type IdeaStatus } from '../features/ideas/api';
import { pinsApi } from '../features/pins/api';
import {
  Badge, Button, Card, CardBody, EmptyState, PageHeader, Spinner,
} from '../components/ui';
import { IconBulb, IconResearch, IconBacklog, IconTrash, IconCheck, IconPin } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

const TABS: { label: string; value: IdeaStatus | 'all' }[] = [
  { label: 'Inbox', value: 'inbox' },
  { label: 'Backlog', value: 'backlog' },
  { label: 'Research', value: 'research' },
  { label: 'Archived', value: 'archived' },
];

/**
 * The lowest-friction capture object in the app: no title, no type, just
 * text. Triage here is what turns a raw thought into a Pareto-scored backlog
 * feature or a research brief — nothing is deleted along the way.
 */
export default function Ideas() {
  const { projectId } = useProject();
  const { toast } = useToast();

  const [tab, setTab] = useState<IdeaStatus | 'all'>('inbox');
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState('');
  const [capturing, setCapturing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(new Set());

  const loadPins = () => {
    pinsApi.list(projectId)
      .then((r) => setPinnedIds(new Set(
        r.pins.filter((p) => p.entity_type === 'idea').map((p) => p.entity_id)
      )))
      .catch(() => {});
  };

  const load = () => {
    setLoading(true);
    loadPins();
    ideasApi.list(projectId, tab === 'all' ? undefined : tab)
      .then((r) => setIdeas(r.ideas))
      .catch(() => setIdeas([]))
      .finally(() => setLoading(false));
  };

  const togglePin = async (ideaId: string) => {
    const isPinned = pinnedIds.has(ideaId);
    setPinnedIds((prev) => {
      const next = new Set(prev);
      isPinned ? next.delete(ideaId) : next.add(ideaId);
      return next;
    });
    try {
      if (isPinned) await pinsApi.unpin(projectId, 'idea', ideaId);
      else await pinsApi.pin(projectId, 'idea', ideaId);
      toast(isPinned ? 'Unpinned' : 'Pinned', 'success');
    } catch {
      loadPins();
    }
  };

  useEffect(load, [projectId, tab]);

  const capture = async () => {
    const value = text.trim();
    if (!value) return;
    setCapturing(true);
    try {
      await ideasApi.capture(projectId, value);
      setText('');
      toast('Captured', 'success');
      if (tab === 'inbox' || tab === 'all') load();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not capture', 'error');
    } finally {
      setCapturing(false);
    }
  };

  const withBusy = async (id: string, fn: () => Promise<unknown>, okMsg: string) => {
    setBusyId(id);
    try {
      await fn();
      toast(okMsg, 'success');
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Action failed', 'error');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Ideas"
        subtitle="Capture a thought in one line, triage it into a backlog feature or a research brief whenever you're ready."
      />

      <Card className="mb-5">
        <CardBody className="flex gap-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) capture();
            }}
            placeholder="What's on your mind? (⌘⏎ to capture)"
            className="w-full rounded-xl border border-line bg-surface2 px-3.5 py-2.5 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-brand/50"
          />
          <Button variant="primary" loading={capturing} disabled={!text.trim()} onClick={capture}>
            Capture
          </Button>
        </CardBody>
      </Card>

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
      ) : ideas.length === 0 ? (
        <EmptyState
          icon={<IconBulb size={22} />}
          title="Nothing here yet"
          description={tab === 'inbox'
            ? 'Capture your first idea above — no title, no structure, just the thought.'
            : 'Ideas triaged into this bucket will show up here.'}
        />
      ) : (
        <div className="space-y-2.5">
          {ideas.map((idea) => (
            <Card key={idea.id}>
              <CardBody className="flex items-start gap-3 py-3.5">
                <p className="min-w-0 flex-1 text-sm text-ink">{idea.text}</p>
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    onClick={() => togglePin(idea.id)}
                    aria-label={pinnedIds.has(idea.id) ? 'Unpin this idea' : 'Pin this idea'}
                    className={`rounded-lg p-1.5 transition-colors ${
                      pinnedIds.has(idea.id)
                        ? 'text-brand' : 'text-ink-muted hover:text-ink'
                    }`}
                  >
                    <IconPin size={14} />
                  </button>
                  {idea.status === 'inbox' ? (
                    <>
                      <Button
                        variant="ghost" icon={<IconBacklog size={13} />}
                        loading={busyId === idea.id}
                        onClick={() => withBusy(idea.id, () => ideasApi.triageToBacklog(idea.id), 'Added to backlog')}
                      >
                        Backlog
                      </Button>
                      <Button
                        variant="ghost" icon={<IconResearch size={13} />}
                        loading={busyId === idea.id}
                        onClick={() => withBusy(idea.id, () => ideasApi.triageToResearch(idea.id), 'Research brief created')}
                      >
                        Research
                      </Button>
                      <Button
                        variant="ghost" icon={<IconTrash size={13} />}
                        loading={busyId === idea.id}
                        onClick={() => withBusy(idea.id, () => ideasApi.archive(idea.id), 'Archived')}
                      >
                        Archive
                      </Button>
                    </>
                  ) : (
                    <Badge tone={idea.status === 'archived' ? 'neutral' : 'success'}>
                      {idea.status === 'backlog' && <IconCheck size={11} className="mr-1 inline" />}
                      {idea.status}
                    </Badge>
                  )}
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

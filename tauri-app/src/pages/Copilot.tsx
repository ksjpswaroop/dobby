import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  copilotApi, type ChatMessage, type ChatThread,
} from '../features/copilot/api';
import { Button, Card, EmptyState, PageHeader, Spinner } from '../components/ui';
import { renderMarkdown } from '../lib/markdown';
import { IconSparkles, IconTrash, IconPlus, IconDoc } from '../lib/icons';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';

/**
 * Grounded chat over your own documents. Answers carry citations back to the
 * nodes they were built from — an answer you cannot trace is one you should
 * not trust, so the citations are part of the message, not a debug view.
 */
export default function Copilot() {
  const { projectId } = useProject();
  const { toast } = useToast();
  const navigate = useNavigate();

  const [scope, setScope] = useState<'project' | 'global'>('project');
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const loadThreads = () => {
    copilotApi.threads(scope === 'project' ? projectId : null, scope)
      .then((r) => {
        setThreads(r.threads);
        setActiveId((prev) => (prev && r.threads.some((t) => t.id === prev)) ? prev : r.threads[0]?.id ?? null);
      })
      .catch(() => setThreads([]));
  };

  useEffect(loadThreads, [projectId, scope]);

  useEffect(() => {
    if (!activeId) { setMessages([]); return; }
    copilotApi.messages(activeId).then((r) => setMessages(r.messages)).catch(() => setMessages([]));
  }, [activeId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, asking]);

  const newThread = async () => {
    try {
      const t = await copilotApi.createThread(scope === 'project' ? projectId : null);
      setThreads((prev) => [t, ...prev]);
      setActiveId(t.id);
      setMessages([]);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not start a chat', 'error');
    }
  };

  const send = async () => {
    const q = question.trim();
    if (!q) return;

    let threadId = activeId;
    if (!threadId) {
      try {
        const t = await copilotApi.createThread(scope === 'project' ? projectId : null);
        setThreads((prev) => [t, ...prev]);
        setActiveId(t.id);
        threadId = t.id;
      } catch {
        toast('Could not start a chat', 'error');
        return;
      }
    }

    setQuestion('');
    setAsking(true);
    // Show the question immediately; the server persists both turns.
    setMessages((prev) => [...prev, {
      id: `local-${Date.now()}`, role: 'user', content: q,
      citations: [], model: '', latency_ms: 0, created_at: new Date().toISOString(),
    }]);

    try {
      const answer = await copilotApi.ask(threadId, q);
      setMessages((prev) => [...prev, answer]);
      loadThreads();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The copilot could not answer', 'error');
    } finally {
      setAsking(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Copilot"
        subtitle="Ask questions about your work. Answers are grounded in your own documents and cite them."
        actions={
          <>
            <div className="flex gap-1 rounded-xl bg-surface2 p-1">
              {(['project', 'global'] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setScope(s)}
                  className={`rounded-lg px-3 py-1 text-[12px] font-medium capitalize transition-colors ${
                    scope === s ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  {s === 'project' ? 'This project' : 'All projects'}
                </button>
              ))}
            </div>
            <Button variant="secondary" icon={<IconPlus size={14} />} onClick={newThread}>
              New chat
            </Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        {/* Threads */}
        <Card className="overflow-hidden">
          <div className="border-b border-line px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            Chats
          </div>
          {threads.length === 0 ? (
            <p className="p-4 text-[12px] text-ink-muted">No chats yet.</p>
          ) : (
            <ul className="max-h-[60vh] overflow-y-auto">
              {threads.map((t) => (
                <li key={t.id} className="flex items-center gap-1 px-2 py-1">
                  <button
                    onClick={() => setActiveId(t.id)}
                    className={`min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-[12.5px] transition-colors ${
                      activeId === t.id ? 'bg-brand/10 text-brand' : 'text-ink hover:bg-surface2'
                    }`}
                  >
                    {t.title}
                  </button>
                  <button
                    onClick={async () => {
                      await copilotApi.deleteThread(t.id);
                      if (activeId === t.id) setActiveId(null);
                      loadThreads();
                    }}
                    aria-label={`Delete chat ${t.title}`}
                    className="rounded p-1 text-ink-muted hover:text-danger"
                  >
                    <IconTrash size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Conversation */}
        <Card className="flex flex-col overflow-hidden">
          <div className="h-[56vh] overflow-y-auto p-4">
            {messages.length === 0 && !asking ? (
              <EmptyState
                icon={<IconSparkles size={22} />}
                title="Ask about your work"
                description={scope === 'project'
                  ? 'Questions are answered from this project’s documents and backlog.'
                  : 'Questions are answered across every project on this machine.'}
              />
            ) : (
              <div className="space-y-4">
                {messages.map((m) => (
                  <div key={m.id}>
                    <div className={m.role === 'user' ? 'flex justify-end' : ''}>
                      <div
                        className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] ${
                          m.role === 'user'
                            ? 'bg-brand/10 text-ink'
                            : 'bg-surface2 text-ink'
                        }`}
                      >
                        {m.role === 'assistant' ? (
                          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content).html }} />
                        ) : (
                          <span className="whitespace-pre-wrap">{m.content}</span>
                        )}
                      </div>
                    </div>

                    {m.role === 'assistant' && m.citations.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <span className="text-[10px] uppercase tracking-wider text-ink-muted">
                          Sources
                        </span>
                        {m.citations.map((c) => (
                          <button
                            key={c.node_id}
                            onClick={() => navigate(`/documents/${c.node_id}`)}
                            className="chip bg-surface2 text-ink-muted hover:text-brand"
                            title={`Relevance ${c.score}`}
                          >
                            <IconDoc size={10} className="mr-1 inline" />
                            [{c.index}] {c.title}
                          </button>
                        ))}
                      </div>
                    )}

                    {m.role === 'assistant' && m.model && (
                      <p className="mt-1 text-[10px] text-ink-muted">
                        {m.model} · {(m.latency_ms / 1000).toFixed(1)}s
                      </p>
                    )}
                  </div>
                ))}
                {asking && (
                  <div className="flex items-center gap-2 text-[12px] text-ink-muted">
                    <Spinner size={14} /> Thinking…
                  </div>
                )}
              </div>
            )}
            <div ref={endRef} />
          </div>

          <div className="flex gap-2 border-t border-line p-3">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask about your documents, backlog, or research…"
              className="w-full rounded-xl border border-line bg-surface2 px-3.5 py-2.5 text-[13px] outline-none focus:border-brand/50"
            />
            <Button variant="primary" loading={asking} disabled={!question.trim()} onClick={send}>
              Ask
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

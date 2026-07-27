import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  documentsApi, type DocComment, type DocumentDetail, type DocStatus,
  type DocVersion, type LinkMap, type RefineAction, type RefinePreview,
} from '../features/documents/api';
import { Badge, Button, Card, LoadingState, ErrorState, Spinner } from '../components/ui';
import { renderMarkdown } from '../lib/markdown';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';
import {
  IconSparkles, IconCheck, IconTrash, IconRefresh, IconArrowLeft,
} from '../lib/icons';

const AUTOSAVE_MS = 1200;

const STATUS_TONE: Record<DocStatus, 'neutral' | 'warning' | 'success'> = {
  draft: 'neutral', in_review: 'warning', approved: 'success',
};

const NEXT_STATUS: Record<DocStatus, { to: DocStatus; label: string }[]> = {
  draft: [{ to: 'in_review', label: 'Send to review' }],
  in_review: [{ to: 'approved', label: 'Approve' }, { to: 'draft', label: 'Back to draft' }],
  approved: [{ to: 'in_review', label: 'Reopen review' }],
};

type Panel = 'preview' | 'versions' | 'comments' | 'links';

/**
 * The editor that makes generated documents living rather than read-only.
 * Autosave is debounced and snapshots server-side, so every keystroke run is
 * recoverable without spamming the version list.
 */
export default function DocumentEditor() {
  const { nodeId = '' } = useParams();
  const { projectId } = useProject();
  const { toast } = useToast();
  const navigate = useNavigate();

  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [panel, setPanel] = useState<Panel>('preview');

  const [versions, setVersions] = useState<DocVersion[]>([]);
  const [comments, setComments] = useState<DocComment[]>([]);
  const [linkMap, setLinkMap] = useState<LinkMap | null>(null);
  const [diff, setDiff] = useState<string[] | null>(null);

  const [selection, setSelection] = useState({ start: 0, end: 0, text: '' });
  const [refining, setRefining] = useState(false);
  const [preview, setPreview] = useState<RefinePreview | null>(null);
  const [regenIndex, setRegenIndex] = useState<number | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState('');
  const [commentInput, setCommentInput] = useState('');

  const taRef = useRef<HTMLTextAreaElement>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    documentsApi.get(nodeId)
      .then((d) => { setDoc(d); setContent(d.content); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load'))
      .finally(() => setLoading(false));
  }, [nodeId]);

  useEffect(load, [load]);

  const refreshPanel = useCallback(() => {
    if (panel === 'versions') documentsApi.versions(nodeId).then((r) => setVersions(r.versions)).catch(() => {});
    if (panel === 'comments') documentsApi.comments(nodeId).then((r) => setComments(r.comments)).catch(() => {});
    if (panel === 'links') documentsApi.links(nodeId, projectId).then(setLinkMap).catch(() => {});
  }, [panel, nodeId, projectId]);

  useEffect(refreshPanel, [refreshPanel]);

  const persist = useCallback(async (next: string) => {
    setSaving(true);
    try {
      const updated = await documentsApi.save(nodeId, next);
      setDoc(updated);
      setDirty(false);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Save failed', 'error');
    } finally {
      setSaving(false);
    }
  }, [nodeId, toast]);

  const onChange = (next: string) => {
    setContent(next);
    setDirty(true);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => persist(next), AUTOSAVE_MS);
  };

  // A pending debounce must not outlive the page, or the last edit is lost.
  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current); }, []);

  const captureSelection = () => {
    const ta = taRef.current;
    if (!ta) return;
    const { selectionStart: start, selectionEnd: end } = ta;
    setSelection({ start, end, text: content.slice(start, end) });
  };

  const rendered = useMemo(() => renderMarkdown(content), [content]);

  const changeStatus = async (to: DocStatus) => {
    try {
      setDoc(await documentsApi.setStatus(nodeId, to));
      toast(`Moved to ${to.replace('_', ' ')}`, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not change status', 'error');
    }
  };

  const runRefine = async (action: RefineAction, tone = 'plain') => {
    if (!selection.text.trim()) { toast('Select some text first', 'error'); return; }
    setRefining(true);
    setPreview(null);
    try {
      setPreview(await documentsApi.refinePreview(content, selection.text, action, tone));
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Refine failed', 'error');
    } finally {
      setRefining(false);
    }
  };

  const applyRefine = async () => {
    if (!preview) return;
    try {
      const updated = await documentsApi.refineApply(
        nodeId, selection.start, selection.end, preview.refined);
      setDoc(updated);
      setContent(updated.content);
      setPreview(null);
      setSelection({ start: 0, end: 0, text: '' });
      toast('Applied', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not apply', 'error');
    }
  };

  const regenerate = async (index: number) => {
    setRegenIndex(index);
    try {
      const out = await documentsApi.regenerateSection(nodeId, index);
      setDoc(out.document);
      setContent(out.document.content);
      toast('Section regenerated', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Regeneration failed', 'error');
    } finally {
      setRegenIndex(null);
    }
  };

  const restore = async (versionId: string) => {
    try {
      const updated = await documentsApi.restore(nodeId, versionId);
      setDoc(updated);
      setContent(updated.content);
      setDiff(null);
      refreshPanel();
      toast('Restored', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Restore failed', 'error');
    }
  };

  const addTag = async () => {
    const name = tagInput.trim();
    if (!name) return;
    try {
      setDoc(await documentsApi.addTag(nodeId, projectId, name));
      setTagInput('');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not add tag', 'error');
    }
  };

  const addComment = async () => {
    const body = commentInput.trim();
    if (!body) return;
    try {
      await documentsApi.addComment(
        nodeId, body,
        selection.text ? selection.start : undefined,
        selection.text ? selection.end : undefined);
      setCommentInput('');
      documentsApi.comments(nodeId).then((r) => setComments(r.comments));
      documentsApi.get(nodeId).then(setDoc);
      toast('Comment added', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not comment', 'error');
    }
  };

  if (loading) return <LoadingState label="Loading document…" />;
  if (error || !doc) return <ErrorState message={error || 'Not found'} onRetry={load} />;

  return (
    <div>
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <button
            onClick={() => navigate('/documents')}
            className="mb-1 flex items-center gap-1 text-[12px] text-ink-muted hover:text-ink"
          >
            <IconArrowLeft size={13} /> Documents
          </button>
          <h1 className="truncate text-xl font-semibold tracking-tight text-ink">{doc.title}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
            <Badge tone={STATUS_TONE[doc.status]}>{doc.status.replace('_', ' ')}</Badge>
            <span>{doc.node_type}</span>
            <span>· {doc.word_count} words</span>
            <span>· v{doc.version_count}</span>
            {doc.open_comments > 0 && <span>· {doc.open_comments} open comments</span>}
            <span className="text-brand">
              {saving ? 'Saving…' : dirty ? 'Unsaved' : 'Saved'}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {NEXT_STATUS[doc.status].map((t) => (
            <Button key={t.to} variant="secondary" onClick={() => changeStatus(t.to)}>
              {t.label}
            </Button>
          ))}
          <Button
            variant="ghost" icon={<IconSparkles size={14} />}
            onClick={async () => {
              try { setSummary((await documentsApi.summarize(nodeId)).summary); }
              catch (e) { toast(e instanceof Error ? e.message : 'Failed', 'error'); }
            }}
          >
            Summarize
          </Button>
        </div>
      </div>

      {/* Tags */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {doc.tags.map((t) => (
          <span key={t.id} className="chip bg-surface2 text-ink-muted">
            #{t.name}
            <button
              onClick={async () => setDoc(await documentsApi.removeTag(nodeId, t.id))}
              aria-label={`Remove tag ${t.name}`}
              className="ml-1 hover:text-danger"
            >
              ✕
            </button>
          </span>
        ))}
        <input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addTag(); }}
          placeholder="+ tag"
          className="w-24 rounded-lg border border-line bg-transparent px-2 py-0.5 text-[11px] outline-none focus:border-brand/50"
        />
      </div>

      {summary && (
        <Card className="mb-3">
          <div className="flex items-start gap-2 p-4">
            <IconSparkles size={15} className="mt-0.5 shrink-0 text-accent" />
            <div
              className="min-w-0 flex-1 text-[13px] text-ink"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(summary).html }}
            />
            <button onClick={() => setSummary(null)} className="text-[11px] text-ink-muted">✕</button>
          </div>
        </Card>
      )}

      {/* AI refine bar */}
      <Card className="mb-3">
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
          <span className="text-[12px] text-ink-muted">
            {selection.text
              ? `${selection.text.split(/\s+/).filter(Boolean).length} words selected`
              : 'Select text to refine'}
          </span>
          <div className="ml-auto flex flex-wrap gap-1.5">
            <Button variant="ghost" disabled={!selection.text || refining}
                    onClick={() => runRefine('shorten')}>Shorten</Button>
            <Button variant="ghost" disabled={!selection.text || refining}
                    onClick={() => runRefine('expand')}>Expand</Button>
            <Button variant="ghost" disabled={!selection.text || refining}
                    onClick={() => runRefine('tone', 'formal')}>More formal</Button>
            <Button variant="ghost" disabled={!selection.text || refining}
                    onClick={() => runRefine('tone', 'plain')}>Plainer</Button>
            {refining && <Spinner size={15} />}
          </div>
        </div>

        {preview && (
          <div className="border-t border-line px-4 py-3">
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              Preview · {preview.original_words} → {preview.refined_words} words
            </p>
            <p className="whitespace-pre-wrap rounded-xl bg-surface2 p-3 text-[13px] text-ink">
              {preview.refined}
            </p>
            <div className="mt-2 flex gap-2">
              <Button variant="primary" icon={<IconCheck size={13} />} onClick={applyRefine}>
                Apply
              </Button>
              <Button variant="ghost" onClick={() => setPreview(null)}>Discard</Button>
            </div>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Editor */}
        <Card className="overflow-hidden">
          <div className="border-b border-line px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            Markdown
          </div>
          <textarea
            ref={taRef}
            value={content}
            onChange={(e) => onChange(e.target.value)}
            onSelect={captureSelection}
            onKeyUp={captureSelection}
            onMouseUp={captureSelection}
            spellCheck
            className="h-[62vh] w-full resize-none bg-transparent p-4 font-mono text-[12.5px] leading-relaxed text-ink outline-none"
          />
        </Card>

        {/* Side panel */}
        <Card className="overflow-hidden">
          <div className="flex gap-1 border-b border-line px-2 py-1.5">
            {(['preview', 'versions', 'comments', 'links'] as Panel[]).map((p) => (
              <button
                key={p}
                onClick={() => { setPanel(p); setDiff(null); }}
                className={`rounded-lg px-2.5 py-1 text-[12px] font-medium capitalize transition-colors ${
                  panel === p ? 'bg-surface2 text-ink' : 'text-ink-muted hover:text-ink'
                }`}
              >
                {p}
                {p === 'comments' && doc.open_comments > 0 && ` (${doc.open_comments})`}
              </button>
            ))}
          </div>

          <div className="h-[62vh] overflow-y-auto p-4">
            {panel === 'preview' && (
              <>
                <div
                  className="text-[13px] text-ink"
                  dangerouslySetInnerHTML={{ __html: rendered.html }}
                />
                {doc.sections.length > 1 && (
                  <div className="mt-5 border-t border-line pt-3">
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                      Regenerate a section
                    </p>
                    <ul className="space-y-1">
                      {doc.sections.map((s) => (
                        <li key={s.index} className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-[12px] text-ink-muted">
                            {s.heading || '(opening text)'} · {s.word_count}w
                          </span>
                          <Button
                            variant="ghost"
                            icon={<IconRefresh size={12} />}
                            loading={regenIndex === s.index}
                            onClick={() => regenerate(s.index)}
                          >
                            Redo
                          </Button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}

            {panel === 'versions' && (
              diff ? (
                <>
                  <Button variant="ghost" className="mb-2" onClick={() => setDiff(null)}>
                    ← Back to history
                  </Button>
                  <pre className="overflow-x-auto text-[11.5px] leading-relaxed">
                    {diff.map((line, i) => (
                      <div
                        key={i}
                        className={
                          line.startsWith('+') && !line.startsWith('+++') ? 'text-success'
                            : line.startsWith('-') && !line.startsWith('---') ? 'text-danger'
                              : line.startsWith('@@') ? 'text-brand' : 'text-ink-muted'
                        }
                      >
                        {line}
                      </div>
                    ))}
                  </pre>
                </>
              ) : versions.length === 0 ? (
                <p className="text-[13px] text-ink-muted">
                  No history yet — every edit from here is snapshotted.
                </p>
              ) : (
                <ul className="space-y-2">
                  {versions.map((v) => (
                    <li key={v.id} className="rounded-xl border border-line px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[12px] font-medium text-ink">v{v.version}</span>
                        <Badge tone="neutral">{v.reason.replace('_', ' ')}</Badge>
                      </div>
                      <p className="mt-0.5 text-[11px] text-ink-muted">
                        {new Date(v.created_at).toLocaleString()} · {v.word_count}w
                        {v.note && ` · ${v.note}`}
                      </p>
                      <div className="mt-1.5 flex gap-2">
                        <button
                          onClick={async () => setDiff((await documentsApi.diff(nodeId, v.id)).diff)}
                          className="text-[11px] text-brand hover:underline"
                        >
                          Diff
                        </button>
                        <button
                          onClick={() => restore(v.id)}
                          className="text-[11px] text-brand hover:underline"
                        >
                          Restore
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )
            )}

            {panel === 'comments' && (
              <>
                <div className="mb-3">
                  <textarea
                    value={commentInput}
                    onChange={(e) => setCommentInput(e.target.value)}
                    rows={2}
                    placeholder={selection.text
                      ? `Comment on "${selection.text.slice(0, 40)}…"`
                      : 'Leave yourself a note…'}
                    className="w-full rounded-xl border border-line bg-surface2 p-2.5 text-[12.5px] outline-none focus:border-brand/50"
                  />
                  <Button variant="secondary" className="mt-1.5" onClick={addComment}>
                    Add comment
                  </Button>
                </div>
                {comments.length === 0 ? (
                  <p className="text-[13px] text-ink-muted">No comments yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {comments.map((c) => (
                      <li
                        key={c.id}
                        className={`rounded-xl border border-line px-3 py-2 ${c.resolved ? 'opacity-55' : ''}`}
                      >
                        {c.anchor_text && (
                          <p className="mb-1 border-l-2 border-brand/40 pl-2 text-[11px] italic text-ink-muted">
                            {c.anchor_text.slice(0, 90)}
                          </p>
                        )}
                        <p className="text-[12.5px] text-ink">{c.body}</p>
                        <div className="mt-1 flex items-center gap-2 text-[11px]">
                          <button
                            onClick={async () => {
                              c.resolved
                                ? await documentsApi.reopenComment(c.id)
                                : await documentsApi.resolveComment(c.id);
                              documentsApi.comments(nodeId).then((r) => setComments(r.comments));
                              documentsApi.get(nodeId).then(setDoc);
                            }}
                            className="text-brand hover:underline"
                          >
                            {c.resolved ? 'Reopen' : 'Resolve'}
                          </button>
                          <button
                            onClick={async () => {
                              await documentsApi.deleteComment(c.id);
                              documentsApi.comments(nodeId).then((r) => setComments(r.comments));
                              documentsApi.get(nodeId).then(setDoc);
                            }}
                            className="text-ink-muted hover:text-danger"
                          >
                            <IconTrash size={11} />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}

            {panel === 'links' && (
              !linkMap ? <Spinner size={16} /> : (
                <>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                    Links out
                  </p>
                  {linkMap.outgoing.length === 0 ? (
                    <p className="mb-4 text-[12.5px] text-ink-muted">
                      None. Use [[Document Title]] to link.
                    </p>
                  ) : (
                    <ul className="mb-4 space-y-1">
                      {linkMap.outgoing.map((l) => (
                        <li key={l.title} className="text-[12.5px]">
                          {l.resolved ? (
                            <button
                              onClick={() => navigate(`/documents/${l.node_id}`)}
                              className="text-brand hover:underline"
                            >
                              {l.title}
                            </button>
                          ) : (
                            <span className="text-ink-muted">{l.title} · unresolved</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                    Backlinks
                  </p>
                  {linkMap.backlinks.length === 0 ? (
                    <p className="text-[12.5px] text-ink-muted">Nothing links here yet.</p>
                  ) : (
                    <ul className="space-y-1">
                      {linkMap.backlinks.map((b) => (
                        <li key={b.node_id}>
                          <button
                            onClick={() => navigate(`/documents/${b.node_id}`)}
                            className="text-[12.5px] text-brand hover:underline"
                          >
                            {b.title}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

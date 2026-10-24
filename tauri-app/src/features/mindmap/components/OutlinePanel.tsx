import { useEffect, useRef, useState } from 'react';
import { useMindMapStore } from '../store';
import { mindmapApi } from '../api';
import { Button, Spinner } from '../../../components/ui';
import { useToast } from '../../../lib/toast';
import { IconArrowLeft, IconCheck, IconSparkles, IconX } from '../../../lib/icons';
import { cn } from '../../../lib/cn';

type Tab = 'outline' | 'chat';

const SUGGESTIONS = [
  'Add a branch about risks',
  'Make it shorter — merge related branches',
  'Expand the smallest branch with more detail',
  'Rewrite every title to be under five words',
];

/**
 * Text side of the mind map: edit the whole map as markdown, or change it by
 * asking.
 *
 * Both routes go through the same outline format, which is what lets a map move
 * between Dobby and any other tool that speaks heading markdown. Keeping them in
 * one panel — rather than adding two more toolbar buttons — is deliberate: the
 * canvas toolbar was already the busiest surface in the app.
 */
export function OutlinePanel({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const activeMapId = useMindMapStore((s) => s.activeMapId);
  const tree = useMindMapStore((s) => s.tree);
  const chatBusy = useMindMapStore((s) => s.chatBusy);
  const saving = useMindMapStore((s) => s.saving);
  const revertPoint = useMindMapStore((s) => s.revertPoint);
  const chatEdit = useMindMapStore((s) => s.chatEdit);
  const replaceOutline = useMindMapStore((s) => s.replaceOutline);
  const importOutline = useMindMapStore((s) => s.importOutline);
  const revertLast = useMindMapStore((s) => s.revertLast);
  const { toast } = useToast();

  const [tab, setTab] = useState<Tab>('chat');
  const [text, setText] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [history, setHistory] = useState<{ text: string; ok: boolean; note: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Pull the outline whenever the map changes underneath us — unless the user
  // has unsaved edits in the box, which we must not clobber.
  useEffect(() => {
    let cancelled = false;
    if (!activeMapId) return;
    if (dirty) return;
    setLoaded(false);
    mindmapApi
      .exportText(activeMapId, 'outline')
      .then((t) => {
        if (!cancelled) {
          setText(t);
          setLoaded(true);
        }
      })
      .catch(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
    // `tree` is a dependency so the box refreshes after canvas edits.
  }, [activeMapId, tree, dirty]);

  useEffect(() => {
    if (tab === 'chat') inputRef.current?.focus();
  }, [tab]);

  const send = async (raw: string) => {
    const value = raw.trim();
    if (!value || chatBusy) return;
    setInstruction('');
    const ok = await chatEdit(value);
    const err = useMindMapStore.getState().error;
    setHistory((h) => [
      ...h,
      { text: value, ok, note: ok ? 'Applied' : err || 'Failed' },
    ]);
    if (ok) toast('Map updated', 'success');
  };

  const applyOutline = async () => {
    if (!text.trim()) return;
    if (activeMapId) {
      const ok = await replaceOutline(text);
      if (ok) {
        setDirty(false);
        toast('Map rebuilt from the outline', 'success');
      } else {
        toast(useMindMapStore.getState().error || 'Could not apply', 'error');
      }
      return;
    }
    // No map open yet — treat the text as a brand-new map.
    try {
      await importOutline(projectId, text);
      setDirty(false);
      toast('Mind map created', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Import failed', 'error');
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast('Outline copied', 'success');
    } catch {
      toast('Could not copy to the clipboard', 'error');
    }
  };

  return (
    <aside
      className="flex w-[360px] shrink-0 flex-col border-l border-line bg-surface"
      aria-label="Outline and AI editing"
    >
      <div className="flex items-center gap-1 border-b border-line px-3 py-2">
        {(['chat', 'outline'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-pressed={tab === t}
            className={cn(
              'rounded-lg px-2.5 py-1 text-[12px] font-medium capitalize transition-colors',
              tab === t ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface2'
            )}
          >
            {t === 'chat' ? 'Ask' : 'Outline'}
          </button>
        ))}
        <button
          onClick={onClose}
          aria-label="Close the outline panel"
          className="ml-auto rounded-lg p-1 text-ink-muted hover:bg-surface2 hover:text-ink"
        >
          <IconX size={15} />
        </button>
      </div>

      {revertPoint && (
        <div className="flex items-center gap-2 border-b border-line bg-warning/5 px-3 py-2 text-[11px] text-ink-muted">
          <span className="flex-1">The whole map was rewritten.</span>
          <button
            onClick={() => revertLast()}
            className="flex items-center gap-1 font-medium text-brand hover:underline"
          >
            <IconArrowLeft size={12} /> Undo that
          </button>
        </div>
      )}

      {tab === 'chat' ? (
        <>
          <div className="flex-1 overflow-y-auto p-3">
            {history.length === 0 ? (
              <div className="space-y-3">
                <p className="text-[12px] leading-relaxed text-ink-muted">
                  Describe a change and the map is rewritten to match. Every edit
                  leaves a restore point, so nothing is lost.
                </p>
                <div className="space-y-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      disabled={!activeMapId || chatBusy}
                      className="w-full rounded-xl border border-line px-3 py-2 text-left text-[12px] text-ink transition-colors hover:border-brand hover:bg-brand/5 disabled:opacity-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <ul className="space-y-2">
                {history.map((h, i) => (
                  <li key={i} className="rounded-xl border border-line px-3 py-2">
                    <div className="text-[12px] text-ink">{h.text}</div>
                    <div
                      className={cn(
                        'mt-1 flex items-center gap-1 text-[11px]',
                        h.ok ? 'text-success' : 'text-danger'
                      )}
                    >
                      {h.ok && <IconCheck size={11} />}
                      {h.note}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {chatBusy && (
              <div className="mt-3 flex items-center gap-2 text-[12px] text-ink-muted">
                <Spinner size={14} /> Rewriting the map…
              </div>
            )}
          </div>

          <form
            className="flex items-center gap-2 border-t border-line p-3"
            onSubmit={(e) => {
              e.preventDefault();
              send(instruction);
            }}
          >
            <input
              ref={inputRef}
              className="input flex-1 py-1.5 text-[13px]"
              placeholder="What should change?"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              disabled={!activeMapId || chatBusy}
              aria-label="Describe a change to the mind map"
            />
            <Button
              type="submit"
              variant="primary"
              icon={<IconSparkles size={14} />}
              loading={chatBusy}
              disabled={!activeMapId || !instruction.trim()}
            >
              Send
            </Button>
          </form>
        </>
      ) : (
        <>
          <div className="flex-1 overflow-hidden p-3">
            {!loaded && activeMapId ? (
              <div className="flex h-full items-center justify-center">
                <Spinner size={18} />
              </div>
            ) : (
              <textarea
                className="input h-full w-full resize-none font-mono text-[12px] leading-relaxed"
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setDirty(true);
                }}
                spellCheck={false}
                aria-label="Mind map outline as markdown"
                placeholder={'# My map\n## First branch\n### A detail\n## Second branch'}
              />
            )}
          </div>
          <div className="flex items-center gap-2 border-t border-line p-3">
            <Button variant="ghost" onClick={copy} disabled={!text.trim()}>
              Copy
            </Button>
            <span className="flex-1 text-[11px] text-ink-muted">
              {dirty ? 'Unsaved changes' : 'Paste markdown from anywhere'}
            </span>
            <Button
              variant="primary"
              onClick={applyOutline}
              loading={saving}
              disabled={!text.trim() || !dirty}
              title="Rebuild the map from this text"
            >
              Apply
            </Button>
          </div>
        </>
      )}
    </aside>
  );
}

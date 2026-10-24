import { useEffect, useRef, useState } from 'react';
import { ideasApi } from '../features/ideas/api';
import { useProject } from '../lib/project';
import { useToast } from '../lib/toast';
import { IconBulb } from '../lib/icons';
import { Spinner } from './ui';

/**
 * Capture a thought without leaving whatever you were doing. An OS-global
 * hotkey needs the Tauri capabilities work already deferred elsewhere
 * (see the reveal-in-Finder note); this is the in-app equivalent — ⌘I from
 * any page opens this, Enter captures and closes, nothing else changes.
 */
export function QuickCapture({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { projectId } = useProject();
  const { toast } = useToast();
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setText('');
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;

  const submit = async () => {
    const value = text.trim();
    if (!value || saving) return;
    setSaving(true);
    try {
      await ideasApi.capture(projectId, value);
      toast('Idea captured', 'success');
      onClose();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not capture', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/40 p-4 pt-[16vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg animate-scale-in overflow-hidden rounded-2xl border border-line bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
          <IconBulb size={16} className="text-brand" />
          <span className="text-sm font-medium text-ink">Quick capture</span>
          <kbd className="ml-auto rounded-md border border-line bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted">
            esc
          </kbd>
        </div>
        <div className="p-4">
          <textarea
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose();
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={3}
            placeholder="What's on your mind?"
            className="w-full resize-none bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-muted"
          />
        </div>
        <div className="flex items-center justify-between border-t border-line px-4 py-2.5">
          <span className="text-[11px] text-ink-muted">Goes to your Idea Inbox — triage it later</span>
          {saving ? <Spinner size={16} /> : (
            <kbd className="rounded-md border border-line bg-surface2 px-1.5 py-0.5 text-[10px] text-ink-muted">
              ⏎ capture
            </kbd>
          )}
        </div>
      </div>
    </div>
  );
}

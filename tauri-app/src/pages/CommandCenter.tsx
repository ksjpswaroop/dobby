import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, PageHeader } from '../components/ui';
import { buildCommands, buildModelCommands, type Command } from '../lib/commands';
import { useTheme } from '../lib/theme';
import { useToast } from '../lib/toast';
import { useProject } from '../lib/project';
import { IconCommand } from '../lib/icons';

/**
 * The Command Center surface: a browsable directory of everything ⌘K can do.
 * The palette is the fast path; this page is the discoverable one.
 */
export default function CommandCenter() {
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const { toast } = useToast();
  const { projectId } = useProject();
  const [models, setModels] = useState<Command[]>([]);

  const ctx = useMemo(
    () => ({ navigate, toast, setTheme, projectId, close: () => {} }),
    [navigate, toast, setTheme, projectId]
  );

  useEffect(() => {
    buildModelCommands(ctx).then(setModels);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const all = useMemo(() => [...buildCommands(ctx), ...models], [ctx, models]);

  const groups = useMemo(() => {
    const m = new Map<string, Command[]>();
    all.forEach((c) => m.set(c.group, [...(m.get(c.group) ?? []), c]));
    return [...m.entries()];
  }, [all]);

  const openPalette = () =>
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true })
    );

  return (
    <div>
      <PageHeader
        title="Command Center"
        subtitle="Every action in Dobby, in one place. Press ⌘K anywhere for the fast path."
        actions={
          <Button variant="primary" icon={<IconCommand size={16} />} onClick={openPalette}>
            Open ⌘K
          </Button>
        }
      />

      <div className="space-y-5">
        {groups.map(([group, cmds]) => (
          <div key={group}>
            <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              {group} <span className="font-normal normal-case">· {cmds.length}</span>
            </h2>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {cmds.map((c) => (
                <button
                  key={c.id}
                  onClick={() => c.run()}
                  className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-left transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-card"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand">
                    <c.icon size={16} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-ink">{c.label}</span>
                    {c.hint && (
                      <span className="block truncate text-[11px] text-ink-muted">{c.hint}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

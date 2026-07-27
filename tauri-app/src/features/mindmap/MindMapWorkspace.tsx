import { useEffect, useState } from 'react';
import { useMindMapStore } from './store';
import { MindMapCanvas } from './components/MindMapCanvas';
import { NodeInspector } from './components/NodeInspector';
import { MapToolbar } from './components/MapToolbar';
import { OutlinePanel } from './components/OutlinePanel';
import { RegroupPreview } from './components/RegroupPreview';
import { MindMapErrorBoundary } from './components/MindMapErrorBoundary';
import { Button, LoadingState, EmptyState } from '../../components/ui';
import { IconMindmap, IconPlus, IconSparkles } from '../../lib/icons';

/**
 * The mind-map sub-application. The only component the host app mounts.
 */
export function MindMapWorkspace({ projectId }: { projectId: string; sessionId?: string }) {
  const maps = useMindMapStore((s) => s.maps);
  const tree = useMindMapStore((s) => s.tree);
  const loading = useMindMapStore((s) => s.loading);
  const error = useMindMapStore((s) => s.error);
  const selectedNodeId = useMindMapStore((s) => s.selectedNodeId);

  const loadMaps = useMindMapStore((s) => s.loadMaps);
  const createMap = useMindMapStore((s) => s.createMap);
  const addNode = useMindMapStore((s) => s.addNode);
  const deleteNode = useMindMapStore((s) => s.deleteNode);
  const aiGenerate = useMindMapStore((s) => s.aiGenerate);
  const refresh = useMindMapStore((s) => s.refresh);
  const undo = useMindMapStore((s) => s.undo);
  const redo = useMindMapStore((s) => s.redo);

  const [panelOpen, setPanelOpen] = useState(false);

  useEffect(() => {
    loadMaps(projectId);
  }, [projectId, loadMaps]);

  // Keyboard: Tab adds a child, Enter adds a sibling, Delete removes, ⌘Z undo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
        return;
      }
      if (!selectedNodeId) return;
      const selected = useMindMapStore.getState().tree?.flat.find((n) => n.id === selectedNodeId);
      if (e.key === 'Tab') {
        e.preventDefault();
        addNode(selectedNodeId);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        addNode(selected?.parent_id ?? null);
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        if (selected?.parent_id && window.confirm(`Delete “${selected.title}”?`)) {
          deleteNode(selectedNodeId);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedNodeId, addNode, deleteNode, undo, redo]);

  if (loading && !tree) return <LoadingState label="Loading mind map…" />;

  if (!maps.length) {
    return (
      <EmptyState
        icon={<IconMindmap size={22} />}
        title="No mind maps yet"
        description="Create a map to organize this project's ideas visually — drag to re-parent, collapse branches, and build out the tree."
        action={
          <div className="flex gap-2">
            <Button
              variant="primary"
              icon={<IconPlus size={16} />}
              onClick={() => createMap(projectId, 'Untitled map')}
            >
              Create a mind map
            </Button>
            <Button
              variant="secondary"
              icon={<IconSparkles size={16} />}
              onClick={() => {
                const topic = window.prompt('What should this mind map be about?');
                if (topic?.trim()) aiGenerate(projectId, topic.trim());
              }}
            >
              Generate with AI
            </Button>
          </div>
        }
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <MapToolbar
        projectId={projectId}
        panelOpen={panelOpen}
        onTogglePanel={() => setPanelOpen((v) => !v)}
      />
      {error && (
        <div role="alert" className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-xs text-danger">
          {error}
        </div>
      )}
      {/* Screen readers get told what changed without stealing focus. */}
      <p aria-live="polite" className="sr-only">
        {tree ? `${tree.flat.length} nodes. ${selectedNodeId ? 'A node is selected.' : ''}` : ''}
      </p>
      <div className="flex h-[calc(100vh-260px)] min-h-[420px]">
        <div className="relative flex-1">
          {tree && tree.flat.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <EmptyState
                icon={<IconMindmap size={22} />}
                title="This map is empty"
                description="Add a root node, or paste an outline in the side panel to build it from text."
                action={
                  <div className="flex gap-2">
                    <Button variant="primary" icon={<IconPlus size={16} />}
                            onClick={() => addNode(null)}>
                      Add root node
                    </Button>
                    <Button variant="secondary" onClick={() => setPanelOpen(true)}>
                      Paste an outline
                    </Button>
                  </div>
                }
              />
            </div>
          ) : (
            <MindMapErrorBoundary onReset={() => refresh()}>
              <MindMapCanvas />
            </MindMapErrorBoundary>
          )}
          <NodeInspector />
        </div>
        {panelOpen && (
          <OutlinePanel projectId={projectId} onClose={() => setPanelOpen(false)} />
        )}
      </div>
      <RegroupPreview />
    </div>
  );
}

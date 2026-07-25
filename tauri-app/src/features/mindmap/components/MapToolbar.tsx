import { useState } from 'react';
import { useMindMapStore } from '../store';
import { Button } from '../../../components/ui';
import {
  IconPlus, IconTrash, IconLayers, IconRefresh, IconCheck,
  IconZoomIn, IconZoomOut, IconArrowLeft,
} from '../../../lib/icons';

export function MapToolbar({ projectId }: { projectId: string }) {
  const maps = useMindMapStore((s) => s.maps);
  const activeMapId = useMindMapStore((s) => s.activeMapId);
  const tree = useMindMapStore((s) => s.tree);
  const saving = useMindMapStore((s) => s.saving);
  const selectedNodeId = useMindMapStore((s) => s.selectedNodeId);
  const undoStack = useMindMapStore((s) => s.undoStack);
  const redoStack = useMindMapStore((s) => s.redoStack);

  const selectMap = useMindMapStore((s) => s.selectMap);
  const createMap = useMindMapStore((s) => s.createMap);
  const deleteMap = useMindMapStore((s) => s.deleteMap);
  const duplicateMap = useMindMapStore((s) => s.duplicateMap);
  const renameMap = useMindMapStore((s) => s.renameMap);
  const addNode = useMindMapStore((s) => s.addNode);
  const expandAll = useMindMapStore((s) => s.expandAll);
  const collapseAll = useMindMapStore((s) => s.collapseAll);
  const undo = useMindMapStore((s) => s.undo);
  const redo = useMindMapStore((s) => s.redo);

  const [title, setTitle] = useState('');

  const nodeCount = tree?.flat.length ?? 0;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface/60 px-4 py-2">
      <select
        className="input w-auto py-1.5 text-[13px]"
        value={activeMapId ?? ''}
        onChange={(e) => selectMap(e.target.value)}
        aria-label="Select mind map"
      >
        {maps.map((m) => (
          <option key={m.id} value={m.id}>
            {m.title}
          </option>
        ))}
      </select>

      {tree && (
        <input
          className="input w-44 py-1.5 text-[13px]"
          value={title || tree.map.title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => {
            if (title.trim() && title.trim() !== tree.map.title) renameMap(title.trim());
            setTitle('');
          }}
          aria-label="Map title"
        />
      )}

      <span className="mx-1 h-5 w-px bg-line" />

      <Button
        variant="primary"
        icon={<IconPlus size={15} />}
        onClick={() => addNode(selectedNodeId ?? tree?.map.root_node_id ?? null)}
        title={selectedNodeId ? 'Add a child of the selected node' : 'Add a node to the root'}
      >
        Add node
      </Button>

      <Button variant="ghost" onClick={() => undo()} disabled={!undoStack.length}
              icon={<IconArrowLeft size={15} />} title="Undo (⌘Z)">
        Undo
      </Button>
      <Button variant="ghost" onClick={() => redo()} disabled={!redoStack.length}
              icon={<IconRefresh size={15} />} title="Redo (⌘⇧Z)">
        Redo
      </Button>

      <span className="mx-1 h-5 w-px bg-line" />

      <Button variant="ghost" icon={<IconZoomOut size={15} />} onClick={collapseAll}
              title="Collapse all branches">
        Collapse
      </Button>
      <Button variant="ghost" icon={<IconZoomIn size={15} />} onClick={expandAll}
              title="Expand all branches">
        Expand
      </Button>

      <span className="mx-1 h-5 w-px bg-line" />

      <Button variant="ghost" icon={<IconLayers size={15} />}
              onClick={() => activeMapId && duplicateMap(activeMapId, projectId)}>
        Duplicate
      </Button>
      <Button
        variant="ghost"
        icon={<IconTrash size={15} />}
        onClick={() => {
          if (activeMapId && window.confirm(`Delete “${tree?.map.title}” and all its nodes?`)) {
            deleteMap(activeMapId, projectId);
          }
        }}
      >
        Delete map
      </Button>
      <Button variant="ghost" icon={<IconPlus size={15} />}
              onClick={() => createMap(projectId, 'Untitled map')}>
        New map
      </Button>

      <div className="ml-auto flex items-center gap-2 text-[11px] text-ink-muted">
        <span>{nodeCount} node{nodeCount === 1 ? '' : 's'}</span>
        <span className="flex items-center gap-1">
          {saving ? (
            <>
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" /> Saving…
            </>
          ) : (
            <>
              <IconCheck size={12} className="text-success" /> Saved
            </>
          )}
        </span>
      </div>
    </div>
  );
}

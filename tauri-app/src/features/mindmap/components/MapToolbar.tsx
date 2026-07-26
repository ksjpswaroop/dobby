import { useRef, useState } from 'react';
import { useMindMapStore } from '../store';
import { Button } from '../../../components/ui';
import { exportPng, exportStructured, exportSvg } from '../export';
import { useToast } from '../../../lib/toast';
import {
  IconPlus, IconTrash, IconLayers, IconRefresh, IconCheck,
  IconZoomIn, IconZoomOut, IconArrowLeft, IconSparkles, IconFlow,
  IconDownload, IconMindmap, IconGraph,
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

  const aiBusy = useMindMapStore((s) => s.aiBusy);
  const aiGenerate = useMindMapStore((s) => s.aiGenerate);
  const aiExpand = useMindMapStore((s) => s.aiExpand);
  const aiRegroup = useMindMapStore((s) => s.aiRegroup);

  const layout = useMindMapStore((s) => s.layout);
  const setLayout = useMindMapStore((s) => s.setLayout);
  const importMap = useMindMapStore((s) => s.importMap);
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState('');
  const [exporting, setExporting] = useState(false);

  const doExport = async (format: 'json' | 'markdown' | 'mermaid' | 'png' | 'svg') => {
    if (!activeMapId || !tree) return;
    try {
      setExporting(true);
      if (format === 'png') await exportPng(tree.map.title);
      else if (format === 'svg') await exportSvg(tree.map.title);
      else await exportStructured(activeMapId, tree.map.title, format);
      toast(`Exported as ${format.toUpperCase()}`, 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Export failed', 'error');
    } finally {
      setExporting(false);
    }
  };

  const onPickFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      await importMap(projectId, JSON.parse(await file.text()));
      toast('Mind map imported', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not read that file', 'error');
    }
  };


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
        Collapse all
      </Button>
      <Button variant="ghost" icon={<IconZoomIn size={15} />} onClick={expandAll}
              title="Expand all branches">
        Expand all
      </Button>

      <span className="mx-1 h-5 w-px bg-line" />

      {/* AI actions */}
      <Button
        variant="secondary"
        icon={<IconSparkles size={15} />}
        loading={aiBusy === 'generate'}
        onClick={() => {
          const topic = window.prompt('What should this mind map be about?');
          if (topic?.trim()) aiGenerate(projectId, topic.trim());
        }}
        title="Generate a whole new map with AI"
      >
        AI map
      </Button>
      <Button
        variant="ghost"
        icon={<IconSparkles size={15} />}
        loading={aiBusy === 'expand'}
        disabled={!selectedNodeId}
        onClick={() => selectedNodeId && aiExpand(selectedNodeId)}
        title={selectedNodeId ? 'Add AI-generated children to the selected node' : 'Select a node first'}
      >
        AI expand
      </Button>
      <Button
        variant="ghost"
        icon={<IconFlow size={15} />}
        loading={aiBusy === 'regroup'}
        onClick={() => aiRegroup()}
        title="Propose a reorganization (preview before applying)"
      >
        AI regroup
      </Button>

      <span className="mx-1 h-5 w-px bg-line" />

      {/* Layout: radial reads better for wide maps, tree for deep ones. */}
      <div className="flex items-center gap-0.5 rounded-xl border border-line p-0.5" role="group"
           aria-label="Layout mode">
        <button
          onClick={() => setLayout('tree')}
          aria-pressed={layout === 'tree'}
          title="Tree layout (left to right)"
          className={'flex h-7 w-7 items-center justify-center rounded-lg transition-colors ' +
            (layout === 'tree' ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface2')}
        >
          <IconGraph size={15} />
        </button>
        <button
          onClick={() => setLayout('radial')}
          aria-pressed={layout === 'radial'}
          title="Radial layout (around the centre)"
          className={'flex h-7 w-7 items-center justify-center rounded-lg transition-colors ' +
            (layout === 'radial' ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface2')}
        >
          <IconMindmap size={15} />
        </button>
      </div>

      <select
        className="input w-auto py-1.5 text-[13px]"
        value=""
        disabled={exporting}
        aria-label="Export mind map"
        onChange={(e) => {
          const v = e.target.value as 'json' | 'markdown' | 'mermaid' | 'png' | 'svg';
          if (v) doExport(v);
          e.target.value = '';
        }}
      >
        <option value="">Export…</option>
        <option value="json">JSON (re-importable)</option>
        <option value="markdown">Markdown outline</option>
        <option value="mermaid">Mermaid</option>
        <option value="png">PNG image</option>
        <option value="svg">SVG image</option>
      </select>

      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(e) => {
          onPickFile(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
      <Button variant="ghost" icon={<IconDownload size={15} />}
              onClick={() => fileRef.current?.click()} title="Import a map from JSON">
        Import
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

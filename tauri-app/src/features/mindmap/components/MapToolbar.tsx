import { useRef, useState } from 'react';
import { useMindMapStore } from '../store';
import { Button } from '../../../components/ui';
import { exportPng, exportStructured, exportSvg } from '../export';
import { useToast } from '../../../lib/toast';
import {
  IconPlus, IconRefresh, IconCheck,
  IconZoomIn, IconZoomOut, IconArrowLeft, IconSparkles, IconFlow,
  IconMindmap, IconGraph, IconNotes,
} from '../../../lib/icons';

type ExportFormat = 'json' | 'markdown' | 'mermaid' | 'outline' | 'png' | 'svg';

interface Props {
  projectId: string;
  panelOpen: boolean;
  onTogglePanel: () => void;
}

export function MapToolbar({ projectId, panelOpen, onTogglePanel }: Props) {
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
  const importOutline = useMindMapStore((s) => s.importOutline);
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState('');
  const [exporting, setExporting] = useState(false);

  const doExport = async (format: ExportFormat) => {
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

  /**
   * Import a dropped file. JSON is the lossless round-trip format; anything else
   * is treated as an outline, so a `.md` written in another tool just works.
   */
  const onPickFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text().catch(() => null);
    if (text === null) {
      toast('Could not read that file', 'error');
      return;
    }
    try {
      if (/\.json$/i.test(file.name)) {
        await importMap(projectId, JSON.parse(text));
      } else {
        await importOutline(projectId, text, file.name.replace(/\.[^.]+$/, ''));
      }
      toast('Mind map imported', 'success');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not import that file', 'error');
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

      {/* Text view: paste an outline in, or ask for a change. */}
      <Button
        variant={panelOpen ? 'secondary' : 'ghost'}
        icon={<IconNotes size={15} />}
        onClick={onTogglePanel}
        aria-pressed={panelOpen}
        title="Edit as an outline, or ask AI to change the map"
      >
        Outline
      </Button>

      <select
        className="input w-auto py-1.5 text-[13px]"
        value=""
        disabled={exporting}
        aria-label="Export mind map"
        onChange={(e) => {
          const v = e.target.value as ExportFormat;
          if (v) doExport(v);
          e.target.value = '';
        }}
      >
        <option value="">Export…</option>
        <option value="outline">Markdown outline (portable)</option>
        <option value="json">JSON (re-importable)</option>
        <option value="markdown">Markdown document</option>
        <option value="mermaid">Mermaid</option>
        <option value="png">PNG image</option>
        <option value="svg">SVG image</option>
      </select>

      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json,text/markdown,.md,.markdown,.txt"
        className="hidden"
        onChange={(e) => {
          onPickFile(e.target.files?.[0]);
          e.target.value = '';
        }}
      />

      {/* Map-level actions collapse into one menu — as separate buttons they
          dominated a toolbar that is mostly about editing the current map. */}
      <select
        className="input w-auto py-1.5 text-[13px]"
        value=""
        aria-label="Mind map actions"
        onChange={(e) => {
          const v = e.target.value;
          e.target.value = '';
          if (v === 'new') createMap(projectId, 'Untitled map');
          else if (v === 'import') fileRef.current?.click();
          else if (v === 'duplicate' && activeMapId) duplicateMap(activeMapId, projectId);
          else if (v === 'delete' && activeMapId) {
            if (window.confirm(`Delete “${tree?.map.title}” and all its nodes?`)) {
              deleteMap(activeMapId, projectId);
            }
          }
        }}
      >
        <option value="">Map…</option>
        <option value="new">New map</option>
        <option value="import">Import a file…</option>
        <option value="duplicate">Duplicate this map</option>
        <option value="delete">Delete this map</option>
      </select>

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

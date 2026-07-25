import { useEffect, useState } from 'react';
import { useMindMapStore } from '../store';
import { NODE_TYPES, TYPE_COLOR } from '../types';
import { Button } from '../../../components/ui';
import { IconX, IconTrash, IconPlus, IconLayers } from '../../../lib/icons';

/** Right-hand panel for editing the selected node. Saves on blur. */
export function NodeInspector() {
  const tree = useMindMapStore((s) => s.tree);
  const selectedNodeId = useMindMapStore((s) => s.selectedNodeId);
  const selectNode = useMindMapStore((s) => s.selectNode);
  const updateNode = useMindMapStore((s) => s.updateNode);
  const deleteNode = useMindMapStore((s) => s.deleteNode);
  const duplicateNode = useMindMapStore((s) => s.duplicateNode);
  const addNode = useMindMapStore((s) => s.addNode);

  const node = tree?.flat.find((n) => n.id === selectedNodeId) ?? null;

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    setTitle(node?.title ?? '');
    setDescription(node?.description ?? '');
  }, [node?.id, node?.title, node?.description]);

  if (!node) return null;

  const isRoot = !node.parent_id;
  const childCount = tree?.flat.filter((n) => n.parent_id === node.id).length ?? 0;

  const commit = (field: 'title' | 'description', value: string) => {
    const current = field === 'title' ? node.title : node.description;
    if (value.trim() === (current ?? '').trim()) return;
    if (field === 'title' && !value.trim()) {
      setTitle(node.title);
      return;
    }
    updateNode(node.id, { [field]: value.trim() });
  };

  const confirmDelete = () => {
    const msg = childCount
      ? `Delete “${node.title}” and its ${childCount} child node${childCount === 1 ? '' : 'ren'}?`
      : `Delete “${node.title}”?`;
    if (window.confirm(msg)) deleteNode(node.id);
  };

  return (
    <aside className="absolute right-0 top-0 z-10 flex h-full w-[320px] flex-col border-l border-line bg-surface shadow-pop">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-sm font-semibold">Node</span>
        <button
          onClick={() => selectNode(null)}
          aria-label="Close inspector"
          className="rounded-lg p-1 text-ink-muted transition-colors hover:bg-surface2 hover:text-ink"
        >
          <IconX size={16} />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div>
          <label className="label">Title</label>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => commit('title', title)}
            onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
          />
        </div>

        <div>
          <label className="label">Description</label>
          <textarea
            className="input"
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => commit('description', description)}
            placeholder="What is this about?"
          />
        </div>

        <div>
          <label className="label">Type</label>
          <select
            className="input"
            value={node.node_type}
            onChange={(e) => updateNode(node.id, { node_type: e.target.value })}
          >
            {NODE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <div className="mt-2 flex items-center gap-2 text-[11px] text-ink-muted">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: TYPE_COLOR[node.node_type] ?? 'rgb(var(--brand))' }}
            />
            Colour follows the node type
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" icon={<IconPlus size={15} />} onClick={() => addNode(node.id)}>
            Add child
          </Button>
          <Button
            variant="secondary"
            icon={<IconLayers size={15} />}
            onClick={() => duplicateNode(node.id)}
          >
            Duplicate
          </Button>
        </div>

        <div className="rounded-xl bg-surface2 px-3 py-2 text-[11px] text-ink-muted">
          <div>{childCount} child node{childCount === 1 ? '' : 'ren'}</div>
          <div className="mt-0.5">{isRoot ? 'Root node' : 'Child node'}</div>
        </div>
      </div>

      <div className="border-t border-line p-3">
        <Button
          variant="danger"
          icon={<IconTrash size={15} />}
          onClick={confirmDelete}
          disabled={isRoot}
          className="w-full"
          title={isRoot ? 'Delete the map instead of its root node' : undefined}
        >
          Delete node
        </Button>
      </div>
    </aside>
  );
}

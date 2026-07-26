import { create } from 'zustand';
import { mindmapApi } from './api';
import type { MapTree, MindMap } from './types';
import type { ProposedTree } from './api';
import type { LayoutMode } from './layout';

const UNDO_DEPTH = 50;

interface MindMapState {
  maps: MindMap[];
  activeMapId: string | null;
  tree: MapTree | null;
  selectedNodeId: string | null;
  collapsed: Set<string>;

  undoStack: MapTree[];
  redoStack: MapTree[];

  loading: boolean;
  saving: boolean;
  error: string | null;

  loadMaps: (projectId: string) => Promise<void>;
  selectMap: (mapId: string) => Promise<void>;
  createMap: (projectId: string, title: string) => Promise<void>;
  deleteMap: (mapId: string, projectId: string) => Promise<void>;
  duplicateMap: (mapId: string, projectId: string) => Promise<void>;
  renameMap: (title: string) => Promise<void>;

  refresh: () => Promise<void>;
  selectNode: (id: string | null) => void;
  toggleCollapse: (id: string) => void;
  expandAll: () => void;
  collapseAll: () => void;

  addNode: (parentId: string | null, title?: string) => Promise<void>;
  updateNode: (nodeId: string, data: Record<string, any>) => Promise<void>;
  moveNode: (nodeId: string, newParentId: string | null) => Promise<void>;
  deleteNode: (nodeId: string) => Promise<void>;
  duplicateNode: (nodeId: string) => Promise<void>;

  undo: () => Promise<void>;
  redo: () => Promise<void>;

  // AI (Phase 2)
  aiBusy: null | 'generate' | 'expand' | 'regroup';
  proposal: { proposed: ProposedTree; summary: { current_nodes: number; proposed_nodes: number } } | null;
  aiGenerate: (projectId: string, topic?: string) => Promise<void>;
  aiExpand: (nodeId: string) => Promise<void>;
  aiRegroup: () => Promise<void>;
  aiApplyRegroup: () => Promise<void>;
  dismissProposal: () => void;

  // Phase 3
  layout: LayoutMode;
  setLayout: (m: LayoutMode) => void;
  importMap: (projectId: string, data: unknown) => Promise<void>;
}

export const useMindMapStore = create<MindMapState>((set, get) => {
  /** Snapshot the current tree before a mutation so undo can restore it. */
  const pushUndo = () => {
    const { tree, undoStack } = get();
    if (!tree) return;
    set({
      undoStack: [...undoStack, structuredClone(tree)].slice(-UNDO_DEPTH),
      redoStack: [],
    });
  };

  /** Re-fetch the authoritative tree from the backend. */
  const reload = async () => {
    const id = get().activeMapId;
    if (!id) return;
    const tree = await mindmapApi.getTree(id);
    set({ tree });
  };

  /**
   * Undo/redo replays a snapshot onto the server. The tree is small, so the
   * simplest correct approach is to diff nothing and just re-apply titles and
   * parents; anything structural the server rejects surfaces as an error.
   */
  const restore = async (snapshot: MapTree) => {
    const current = get().tree;
    if (!current) return;
    set({ saving: true });
    try {
      const before = new Map(current.flat.map((n) => [n.id, n]));
      for (const n of snapshot.flat) {
        const now = before.get(n.id);
        if (!now) continue; // node was deleted; recreating is out of scope for v1
        if (now.title !== n.title || now.description !== n.description ||
            now.node_type !== n.node_type) {
          await mindmapApi.updateNode(n.id, {
            title: n.title, description: n.description, node_type: n.node_type,
          });
        }
        if (now.parent_id !== n.parent_id) {
          await mindmapApi.moveNode(n.id, n.parent_id);
        }
      }
      await reload();
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Undo failed' });
    } finally {
      set({ saving: false });
    }
  };

  return {
    maps: [],
    activeMapId: null,
    tree: null,
    selectedNodeId: null,
    collapsed: new Set<string>(),
    undoStack: [],
    redoStack: [],
    loading: false,
    saving: false,
    error: null,
    aiBusy: null,
    proposal: null,
    layout: (localStorage.getItem('dobby-mindmap-layout') as LayoutMode) || 'tree',

    async loadMaps(projectId) {
      set({ loading: true, error: null });
      try {
        const maps = await mindmapApi.listMaps(projectId);
        set({ maps });
        const active = get().activeMapId;
        if (maps.length && (!active || !maps.some((m) => m.id === active))) {
          await get().selectMap(maps[0].id);
        } else if (!maps.length) {
          set({ activeMapId: null, tree: null });
        }
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to load maps' });
      } finally {
        set({ loading: false });
      }
    },

    async selectMap(mapId) {
      set({ loading: true, activeMapId: mapId, selectedNodeId: null,
            undoStack: [], redoStack: [] });
      try {
        const tree = await mindmapApi.getTree(mapId);
        set({ tree });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to load map' });
      } finally {
        set({ loading: false });
      }
    },

    async createMap(projectId, title) {
      const m = await mindmapApi.createMap(projectId, title);
      await get().loadMaps(projectId);
      await get().selectMap(m.id);
    },

    async deleteMap(mapId, projectId) {
      await mindmapApi.deleteMap(mapId);
      set({ activeMapId: null, tree: null });
      await get().loadMaps(projectId);
    },

    async duplicateMap(mapId, projectId) {
      const m = await mindmapApi.duplicateMap(mapId);
      await get().loadMaps(projectId);
      await get().selectMap(m.id);
    },

    async renameMap(title) {
      const id = get().activeMapId;
      if (!id) return;
      await mindmapApi.updateMap(id, { title });
      set({
        maps: get().maps.map((m) => (m.id === id ? { ...m, title } : m)),
        tree: get().tree ? { ...get().tree!, map: { ...get().tree!.map, title } } : null,
      });
    },

    refresh: reload,

    selectNode(id) {
      set({ selectedNodeId: id });
    },

    toggleCollapse(id) {
      const next = new Set(get().collapsed);
      next.has(id) ? next.delete(id) : next.add(id);
      set({ collapsed: next });
    },

    expandAll() {
      set({ collapsed: new Set() });
    },

    collapseAll() {
      const tree = get().tree;
      if (!tree) return;
      // Collapse every node that has children.
      const parents = new Set(tree.flat.filter((n) => n.parent_id).map((n) => n.parent_id!));
      set({ collapsed: parents });
    },

    async addNode(parentId, title = 'New idea') {
      const mapId = get().activeMapId;
      if (!mapId) return;
      pushUndo();
      set({ saving: true });
      try {
        const node = await mindmapApi.createNode(mapId, { title, parent_id: parentId });
        await reload();
        set({ selectedNodeId: node.id });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to add node' });
      } finally {
        set({ saving: false });
      }
    },

    async updateNode(nodeId, data) {
      pushUndo();
      set({ saving: true });
      try {
        await mindmapApi.updateNode(nodeId, data as any);
        await reload();
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to update node' });
      } finally {
        set({ saving: false });
      }
    },

    async moveNode(nodeId, newParentId) {
      pushUndo();
      set({ saving: true, error: null });
      try {
        await mindmapApi.moveNode(nodeId, newParentId);
        await reload();
      } catch (e) {
        // The backend rejected it (e.g. a cycle) — reload to revert the canvas.
        set({ error: e instanceof Error ? e.message : 'Move rejected' });
        await reload();
      } finally {
        set({ saving: false });
      }
    },

    async deleteNode(nodeId) {
      pushUndo();
      set({ saving: true });
      try {
        await mindmapApi.deleteNode(nodeId);
        set({ selectedNodeId: null });
        await reload();
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to delete node' });
      } finally {
        set({ saving: false });
      }
    },

    async duplicateNode(nodeId) {
      pushUndo();
      set({ saving: true });
      try {
        await mindmapApi.duplicateNode(nodeId);
        await reload();
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to duplicate node' });
      } finally {
        set({ saving: false });
      }
    },

    async aiGenerate(projectId, topic) {
      set({ aiBusy: 'generate', error: null });
      try {
        const r = await mindmapApi.aiGenerate(projectId, topic);
        await get().loadMaps(projectId);
        await get().selectMap(r.map_id);
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'AI generation failed' });
      } finally {
        set({ aiBusy: null });
      }
    },

    async aiExpand(nodeId) {
      set({ aiBusy: 'expand', error: null });
      pushUndo();
      try {
        await mindmapApi.aiExpand(nodeId);
        await reload();
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'AI expansion failed' });
      } finally {
        set({ aiBusy: null });
      }
    },

    async aiRegroup() {
      const id = get().activeMapId;
      if (!id) return;
      set({ aiBusy: 'regroup', error: null });
      try {
        // Only proposes — nothing is written until the user accepts.
        set({ proposal: await mindmapApi.aiRegroup(id) });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'AI regroup failed' });
      } finally {
        set({ aiBusy: null });
      }
    },

    async aiApplyRegroup() {
      const id = get().activeMapId;
      const proposal = get().proposal;
      if (!id || !proposal) return;
      set({ aiBusy: 'regroup', error: null });
      try {
        await mindmapApi.aiApplyRegroup(id, proposal.proposed);
        set({ proposal: null, undoStack: [], redoStack: [] });
        await reload();
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Failed to apply' });
      } finally {
        set({ aiBusy: null });
      }
    },

    dismissProposal() {
      set({ proposal: null });
    },

    setLayout(m) {
      localStorage.setItem('dobby-mindmap-layout', m);
      set({ layout: m });
    },

    async importMap(projectId, data) {
      set({ loading: true, error: null });
      try {
        const r = await mindmapApi.importMap(projectId, data);
        await get().loadMaps(projectId);
        await get().selectMap(r.map_id);
      } catch (e) {
        set({ error: e instanceof Error ? e.message : 'Import failed' });
      } finally {
        set({ loading: false });
      }
    },

    async undo() {
      const { undoStack, redoStack, tree } = get();
      if (!undoStack.length || !tree) return;
      const prev = undoStack[undoStack.length - 1];
      set({
        undoStack: undoStack.slice(0, -1),
        redoStack: [...redoStack, structuredClone(tree)].slice(-UNDO_DEPTH),
      });
      await restore(prev);
    },

    async redo() {
      const { redoStack, undoStack, tree } = get();
      if (!redoStack.length || !tree) return;
      const next = redoStack[redoStack.length - 1];
      set({
        redoStack: redoStack.slice(0, -1),
        undoStack: [...undoStack, structuredClone(tree)].slice(-UNDO_DEPTH),
      });
      await restore(next);
    },
  };
});

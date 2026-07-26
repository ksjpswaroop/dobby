import type { MapTree, TreeNode } from './types';

export type LayoutMode = 'radial' | 'tree';

export interface Positioned {
  id: string;
  x: number;
  y: number;
  node: TreeNode;
  depth: number;
}

/* -------------------------------------------------------------------------- */
/* Tree: tidy left-to-right                                                    */
/* -------------------------------------------------------------------------- */
const X_GAP = 260;
const Y_GAP = 74;

function layoutTreeMode(tree: MapTree, collapsed: Set<string>): Positioned[] {
  const out: Positioned[] = [];
  let row = 0;

  const walk = (node: TreeNode, depth: number): number => {
    const kids = collapsed.has(node.id) ? [] : node.children;
    let y: number;
    if (!kids.length) {
      y = row * Y_GAP;
      row += 1;
    } else {
      const ys = kids.map((c) => walk(c, depth + 1));
      y = (ys[0] + ys[ys.length - 1]) / 2; // centre on first..last child
    }
    out.push({ id: node.id, x: depth * X_GAP, y, node, depth });
    return y;
  };

  tree.nodes.forEach((root) => walk(root, 0));
  return out;
}

/* -------------------------------------------------------------------------- */
/* Radial: full circle around the root                                         */
/* -------------------------------------------------------------------------- */
// Radii follow the proportions in the mindmap-skill layout reference: branches
// sit well clear of the centre, and each level steps in by roughly half again.
const BRANCH_RADIUS = 300;
const SUB_RADIUS = 190;
const DETAIL_RADIUS = 130;
const SEMICIRCLE_THRESHOLD = 7; // beyond this a full circle gets crowded

function radiusForDepth(depth: number): number {
  if (depth === 1) return BRANCH_RADIUS;
  if (depth === 2) return SUB_RADIUS;
  return DETAIL_RADIUS;
}

function layoutRadialMode(tree: MapTree, collapsed: Set<string>): Positioned[] {
  const out: Positioned[] = [];

  /** Place a node's children in an arc centred on the parent's own angle. */
  const placeChildren = (
    parent: TreeNode,
    px: number,
    py: number,
    parentAngle: number,
    depth: number
  ) => {
    const kids = collapsed.has(parent.id) ? [] : parent.children;
    if (!kids.length) return;

    // Wider spread when there are more children, per the reference.
    const spread = Math.PI * (kids.length > 4 ? 0.65 : 0.52);
    const start = parentAngle - spread / 2;
    const radius = radiusForDepth(depth);

    kids.forEach((child, j) => {
      const angle =
        kids.length === 1 ? parentAngle : start + (j / (kids.length - 1)) * spread;
      const x = px + Math.cos(angle) * radius;
      const y = py + Math.sin(angle) * radius;
      out.push({ id: child.id, x, y, node: child, depth });
      placeChildren(child, x, y, angle, depth + 1);
    });
  };

  tree.nodes.forEach((root, rootIndex) => {
    // Multiple roots are rare; offset them so they don't overlap.
    const cx = rootIndex * (BRANCH_RADIUS * 3);
    const cy = 0;
    out.push({ id: root.id, x: cx, y: cy, node: root, depth: 0 });

    const branches = collapsed.has(root.id) ? [] : root.children;
    if (!branches.length) return;

    // 7+ branches would crowd a full circle, so fall back to a wide arc.
    const useSemicircle = branches.length >= SEMICIRCLE_THRESHOLD;
    const sweep = useSemicircle ? Math.PI * 1.15 : Math.PI * 2;
    const startAngle = useSemicircle ? -Math.PI * 1.08 : -Math.PI / 2;
    const step = sweep / (useSemicircle ? Math.max(branches.length - 1, 1) : branches.length);

    branches.forEach((branch, i) => {
      const angle = startAngle + i * step;
      const x = cx + Math.cos(angle) * BRANCH_RADIUS;
      const y = cy + Math.sin(angle) * BRANCH_RADIUS;
      out.push({ id: branch.id, x, y, node: branch, depth: 1 });
      placeChildren(branch, x, y, angle, 2);
    });
  });

  return out;
}

/* -------------------------------------------------------------------------- */

export function layoutTree(
  tree: MapTree,
  collapsed: Set<string>,
  mode: LayoutMode = 'tree'
): Positioned[] {
  return mode === 'radial'
    ? layoutRadialMode(tree, collapsed)
    : layoutTreeMode(tree, collapsed);
}

/** Ids hidden because an ancestor is collapsed. */
export function hiddenIds(tree: MapTree, collapsed: Set<string>): Set<string> {
  const hidden = new Set<string>();
  const walk = (node: TreeNode, underCollapsed: boolean) => {
    if (underCollapsed) hidden.add(node.id);
    const next = underCollapsed || collapsed.has(node.id);
    node.children.forEach((c) => walk(c, next));
  };
  tree.nodes.forEach((r) => walk(r, false));
  return hidden;
}

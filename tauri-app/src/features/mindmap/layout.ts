import type { MapTree, TreeNode } from './types';

export interface Positioned {
  id: string;
  x: number;
  y: number;
  node: TreeNode;
  depth: number;
}

const X_GAP = 260; // horizontal distance between depths
const Y_GAP = 74;  // vertical distance between leaves

/**
 * Tidy left-to-right tree layout.
 *
 * A simple post-order walk: leaves take the next row, parents centre on their
 * children. Deterministic and dependency-free — enough for a mind map, and it
 * avoids pulling in a graph-layout library for a strict hierarchy.
 */
export function layoutTree(tree: MapTree, collapsed: Set<string>): Positioned[] {
  const out: Positioned[] = [];
  let row = 0;

  const walk = (node: TreeNode, depth: number): number => {
    const hidden = collapsed.has(node.id);
    const kids = hidden ? [] : node.children;

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

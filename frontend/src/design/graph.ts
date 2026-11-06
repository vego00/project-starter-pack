import dagre from "@dagrejs/dagre";
import { MarkerType } from "@xyflow/react";
import type { Edge, Node } from "@xyflow/react";
import type { Issue } from "./check";
import type { Design, DesignNode } from "./types";

export const NODE_WIDTH = 230;
export const NODE_HEIGHT = 104;

export const SIDE_OUT = "side-out";
export const SIDE_IN = "side-in";

export type Point = { x: number; y: number };
export type NodeData = {
  node: DesignNode;
  isEntry: boolean;
  isExit: boolean;
  issues: number;
  highlighted: boolean;
  loopLimit: number | null;
};
export type FlowNode = Node<NodeData, "design">;

export const edgeId = (source: string, target: string) =>
  `${source}->${target}`;

/** Positions live here, outside the design, because they are a property of this screen only. */
export function autoLayout(design: Design): Map<string, Point> {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "TB", nodesep: 48, ranksep: 60 });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const node of design.nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  const known = new Set(design.nodes.map((node) => node.id));
  for (const edge of design.workflow.edges) {
    if (known.has(edge.source) && known.has(edge.target))
      graph.setEdge(edge.source, edge.target);
  }
  dagre.layout(graph);
  return new Map(
    design.nodes.map((node) => {
      const { x, y } = graph.node(node.id);
      return [node.id, { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 }];
    }),
  );
}

export function toFlowNodes(
  design: Design,
  moved: Map<string, Point>,
  issues: Issue[],
  selectedId: string | null,
  highlightedIds: string[],
): FlowNode[] {
  const layout = autoLayout(design);
  const { entry, exits, loop_limits } = design.workflow;
  return design.nodes.map((node) => ({
    id: node.id,
    type: "design",
    position: moved.get(node.id) ?? layout.get(node.id)!,
    selected: node.id === selectedId,
    data: {
      node,
      isEntry: node.id === entry,
      isExit: exits.includes(node.id),
      issues: issues.filter((issue) => issue.nodeIds.includes(node.id)).length,
      highlighted: highlightedIds.includes(node.id),
      loopLimit:
        loop_limits.find((limit) => limit.node_ids.includes(node.id))
          ?.max_iterations ?? null,
    },
  }));
}

/** Height that keeps node text readable; the page scrolls instead of the graph shrinking. */
export function canvasHeight(design: Design): number {
  const bottom = Math.max(
    0,
    ...[...autoLayout(design).values()].map((point) => point.y),
  );
  return Math.min(1500, Math.max(520, (bottom + NODE_HEIGHT) * 0.9 + 60));
}

export function toFlowEdges(design: Design, selected: string | null): Edge[] {
  const known = new Set(design.nodes.map((node) => node.id));
  const layout = autoLayout(design);
  return design.workflow.edges
    .filter((edge) => known.has(edge.source) && known.has(edge.target))
    .map((edge) => {
      const id = edgeId(edge.source, edge.target);
      const goesBack = layout.get(edge.target)!.y < layout.get(edge.source)!.y;
      const label = [edge.on_failure ? "실패 시" : "", edge.condition ?? ""]
        .filter(Boolean)
        .join(" · ");
      return {
        id,
        source: edge.source,
        target: edge.target,
        selected: id === selected,
        className: edge.on_failure ? "flow-edge failure" : "flow-edge",
        // Loops and failure paths skip over nodes, so they leave the straight line down the middle.
        ...(edge.on_failure || goesBack
          ? { sourceHandle: SIDE_OUT, targetHandle: SIDE_IN }
          : {}),
        markerEnd: { type: MarkerType.ArrowClosed },
        ...(label ? { label } : {}),
      };
    });
}

import type { Design, DesignEdge, DesignNode, NodeKind } from "./types";

const ID_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;

export function idProblem(
  design: Design,
  current: string,
  next: string,
): string | null {
  if (!ID_PATTERN.test(next)) {
    return "영문자로 시작하고 영문자, 숫자, -, _만 쓸 수 있어요.";
  }
  if (next !== current && design.nodes.some((node) => node.id === next)) {
    return "같은 이름의 노드가 이미 있어요.";
  }
  return null;
}

export function updateNode(
  design: Design,
  id: string,
  patch: Partial<Omit<DesignNode, "id" | "kind">>,
): Design {
  return {
    ...design,
    nodes: design.nodes.map((node) =>
      node.id === id ? { ...node, ...patch } : node,
    ),
  };
}

export function renameNode(design: Design, id: string, next: string): Design {
  const swap = (value: string) => (value === id ? next : value);
  const { workflow } = design;
  return {
    ...design,
    nodes: design.nodes.map((node) =>
      node.id === id ? { ...node, id: next } : node,
    ),
    requirements: design.requirements.map((r) => ({
      ...r,
      node_ids: r.node_ids.map(swap),
    })),
    workflow: {
      ...workflow,
      entry: swap(workflow.entry),
      exits: workflow.exits.map(swap),
      edges: workflow.edges.map((edge) => ({
        ...edge,
        source: swap(edge.source),
        target: swap(edge.target),
      })),
      loop_limits: workflow.loop_limits.map((limit) => ({
        ...limit,
        node_ids: limit.node_ids.map(swap),
        on_exceeded: swap(limit.on_exceeded),
      })),
    },
  };
}

/** Keeps first id -> latest id, so several renames in a row send one mapping. */
export function addRename(
  renames: Record<string, string>,
  from: string,
  to: string,
): Record<string, string> {
  const original = Object.keys(renames).find((key) => renames[key] === from);
  return { ...renames, [original ?? from]: to };
}

export function addNode(
  design: Design,
  kind: NodeKind,
): { design: Design; id: string } {
  const taken = new Set(design.nodes.map((node) => node.id));
  let index = 1;
  while (taken.has(`${kind}-${index}`)) index += 1;
  const id = `${kind}-${index}`;
  const node: DesignNode = {
    id,
    kind,
    responsibility: "이 노드가 맡을 일을 적어 주세요",
    inputs: [],
    outputs: [],
    tools: [],
    done_when: "끝났다고 볼 기준을 적어 주세요",
    on_failure: "실패하면 어떻게 할지 적어 주세요",
    ...(kind === "agent"
      ? {
          model: {
            capability: "필요한 모델 능력을 적어 주세요",
            provider_scope: "미정",
          },
        }
      : {}),
  };
  return { design: { ...design, nodes: [...design.nodes, node] }, id };
}

/** Removes the node and what points to it. A requirement it served stays and shows as unassigned. */
export function removeElements(
  design: Design,
  nodeIds: string[],
  edges: { source: string; target: string }[] = [],
): Design {
  const gone = new Set(nodeIds);
  const { workflow } = design;
  return {
    ...design,
    nodes: design.nodes.filter((node) => !gone.has(node.id)),
    requirements: design.requirements.map((r) => ({
      ...r,
      node_ids: r.node_ids.filter((id) => !gone.has(id)),
    })),
    workflow: {
      ...workflow,
      entry: gone.has(workflow.entry) ? "" : workflow.entry,
      exits: workflow.exits.filter((id) => !gone.has(id)),
      edges: workflow.edges.filter(
        (edge) =>
          !gone.has(edge.source) &&
          !gone.has(edge.target) &&
          !edges.some(
            (e) => e.source === edge.source && e.target === edge.target,
          ),
      ),
      loop_limits: workflow.loop_limits
        .map((limit) => ({
          ...limit,
          node_ids: limit.node_ids.filter((id) => !gone.has(id)),
        }))
        .filter(
          (limit) => limit.node_ids.length && !gone.has(limit.on_exceeded),
        ),
    },
  };
}

export function addEdge(
  design: Design,
  source: string,
  target: string,
): Design {
  const { workflow } = design;
  if (workflow.edges.some((e) => e.source === source && e.target === target))
    return design;
  const edge: DesignEdge = {
    source,
    target,
    condition: null,
    on_failure: false,
  };
  return {
    ...design,
    workflow: { ...workflow, edges: [...workflow.edges, edge] },
  };
}

export function updateEdge(
  design: Design,
  source: string,
  target: string,
  patch: Partial<Pick<DesignEdge, "condition" | "on_failure">>,
): Design {
  return {
    ...design,
    workflow: {
      ...design.workflow,
      edges: design.workflow.edges.map((edge) =>
        edge.source === source && edge.target === target
          ? { ...edge, ...patch }
          : edge,
      ),
    },
  };
}

export function setEntry(design: Design, id: string): Design {
  return { ...design, workflow: { ...design.workflow, entry: id } };
}

export function toggleExit(design: Design, id: string): Design {
  const { exits } = design.workflow;
  return {
    ...design,
    workflow: {
      ...design.workflow,
      exits: exits.includes(id)
        ? exits.filter((x) => x !== id)
        : [...exits, id],
    },
  };
}

export function parsePorts(text: string): DesignNode["inputs"] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const at = line.indexOf(":");
      return at < 0
        ? { name: line, type: "string" }
        : {
            name: line.slice(0, at).trim(),
            type: line.slice(at + 1).trim() || "string",
          };
    });
}

export function formatPorts(ports: DesignNode["inputs"]): string {
  return ports.map((port) => `${port.name}: ${port.type}`).join("\n");
}

const same = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b);
const edgeName = (edge: DesignEdge) => `${edge.source} → ${edge.target}`;

/** Compares by id, so a rename reads as one node removed and one added. */
export function summarizeChanges(before: Design, after: Design): string[] {
  const lines: string[] = [];
  const old = new Map(before.nodes.map((node) => [node.id, node]));
  const now = new Set(after.nodes.map((node) => node.id));
  for (const node of after.nodes) {
    if (!old.has(node.id)) lines.push(`노드 추가: ${node.id}`);
    else if (!same(old.get(node.id), node)) lines.push(`노드 수정: ${node.id}`);
  }
  for (const id of old.keys()) if (!now.has(id)) lines.push(`노드 삭제: ${id}`);
  const key = (edge: DesignEdge) => `${edge.source}\n${edge.target}`;
  const oldEdges = new Map(
    before.workflow.edges.map((edge) => [key(edge), edge]),
  );
  const nowEdges = new Set(after.workflow.edges.map(key));
  for (const edge of after.workflow.edges) {
    if (!oldEdges.has(key(edge))) lines.push(`연결 추가: ${edgeName(edge)}`);
    else if (!same(oldEdges.get(key(edge)), edge))
      lines.push(`연결 수정: ${edgeName(edge)}`);
  }
  for (const [k, edge] of oldEdges)
    if (!nowEdges.has(k)) lines.push(`연결 삭제: ${edgeName(edge)}`);
  if (before.workflow.entry !== after.workflow.entry) {
    lines.push(`시작 변경: ${after.workflow.entry || "없음"}`);
  }
  if (!same(before.workflow.exits, after.workflow.exits)) {
    lines.push(`끝 변경: ${after.workflow.exits.join(", ") || "없음"}`);
  }
  return lines;
}

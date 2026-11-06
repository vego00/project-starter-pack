import type { Design } from "./types";

export type Issue = {
  severity: "error" | "warning";
  message: string;
  nodeIds: string[];
};

function successors(design: Design): Map<string, Set<string>> {
  const graph = new Map(design.nodes.map((n) => [n.id, new Set<string>()]));
  const { edges, loop_limits } = design.workflow;
  for (const edge of edges) {
    if (graph.has(edge.target)) graph.get(edge.source)?.add(edge.target);
  }
  for (const limit of loop_limits) {
    for (const id of limit.node_ids) {
      if (graph.has(limit.on_exceeded)) graph.get(id)?.add(limit.on_exceeded);
    }
  }
  return graph;
}

function reach(start: string, graph: Map<string, Set<string>>): Set<string> {
  const seen = new Set<string>();
  const stack = [...(graph.get(start) ?? [])];
  while (stack.length) {
    const id = stack.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(graph.get(id) ?? []));
  }
  return seen;
}

/**
 * The structural rules of the backend validator that can run while editing.
 * A stopgap for mock data: once connected, the backend validator is the authority.
 */
export function checkDesign(design: Design): Issue[] {
  const issues: Issue[] = [];
  const add = (
    severity: Issue["severity"],
    message: string,
    ids: string[] = [],
  ) => issues.push({ severity, message, nodeIds: ids });
  const graph = successors(design);
  const { entry, exits, loop_limits, max_model_calls } = design.workflow;
  const allReach = new Map(
    [...graph.keys()].map((id) => [id, reach(id, graph)]),
  );

  const hasEntry = graph.has(entry);
  const liveExits = exits.filter((id) => graph.has(id));
  if (!hasEntry)
    add("error", "시작 노드가 없어요. 노드 하나를 시작으로 지정해 주세요.");
  if (!liveExits.length)
    add("error", "끝 노드가 없어요. 노드 하나를 끝으로 지정해 주세요.");

  const fromEntry = hasEntry ? new Set([entry, ...allReach.get(entry)!]) : null;
  for (const id of graph.keys()) {
    if (fromEntry && !fromEntry.has(id)) {
      add("error", `${id}: 시작에서 이 노드로 오는 길이 없어요.`, [id]);
    } else if (
      liveExits.length &&
      !liveExits.includes(id) &&
      !liveExits.some((exit) => allReach.get(id)!.has(exit))
    ) {
      add("error", `${id}: 이 노드에서 끝으로 가는 길이 없어요.`, [id]);
    }
  }

  const seen = new Set<string>();
  for (const id of graph.keys()) {
    if (seen.has(id) || !allReach.get(id)!.has(id)) continue;
    const cycle = [...allReach.get(id)!].filter((other) =>
      allReach.get(other)!.has(id),
    );
    cycle.forEach((member) => seen.add(member));
    const limits = loop_limits.filter((limit) =>
      limit.node_ids.some((member) => cycle.includes(member)),
    );
    if (!limits.length) {
      add(
        "error",
        `반복 횟수 한도가 없어요: ${cycle.sort().join(", ")}`,
        cycle,
      );
    } else if (limits.every((limit) => cycle.includes(limit.on_exceeded))) {
      add(
        "error",
        `한도를 넘어도 반복을 벗어나지 못해요: ${cycle.sort().join(", ")}`,
        cycle,
      );
    }
  }

  for (const node of design.nodes) {
    if (node.id === entry) continue;
    for (const port of node.inputs) {
      const made = design.nodes.some(
        (source) =>
          allReach.get(source.id)!.has(node.id) &&
          source.outputs.some((output) => output.name === port.name),
      );
      if (!made) {
        add(
          "error",
          `${node.id}: 입력 ${port.name}을 앞에서 만드는 노드가 없어요.`,
          [node.id],
        );
      }
    }
  }

  const humans = design.nodes.filter((node) => node.kind === "human");
  for (const node of design.nodes) {
    if (!node.tools.some((tool) => tool.access === "external_write")) continue;
    if (!humans.some((human) => allReach.get(human.id)!.has(node.id))) {
      add("warning", `${node.id}: 사람 확인 없이 외부에 써요.`, [node.id]);
    }
  }

  const hasAgent = design.nodes.some((node) => node.kind === "agent");
  if (hasAgent && !max_model_calls) {
    add("warning", "모델 호출 한도가 정해지지 않았어요.");
  }

  const known = new Set(graph.keys());
  for (const requirement of design.requirements) {
    if (requirement.core && !requirement.node_ids.some((id) => known.has(id))) {
      add("error", `${requirement.id}: 핵심 요구사항을 맡은 노드가 없어요.`);
    }
  }
  return issues;
}

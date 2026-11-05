import { describe, expect, it } from "vitest";
import { checkDesign } from "../src/design/check";
import {
  addEdge,
  addNode,
  idProblem,
  parsePorts,
  removeElements,
  renameNode,
  summarizeChanges,
  updateEdge,
} from "../src/design/edit";
import { autoLayout, toFlowEdges, toFlowNodes } from "../src/design/graph";
import { DESIGN_CASES } from "../src/design/mock";

const byId = (id: string) =>
  DESIGN_CASES.find((item) => item.id === id)!.design;
const messages = (design: Parameters<typeof checkDesign>[0]) =>
  checkDesign(design).map((issue) => issue.message);

describe("mock designs", () => {
  it("has no structural errors in the straight design", () => {
    expect(checkDesign(byId("straight"))).toEqual([]);
  });

  it("shows only the write warning in the branching design", () => {
    expect(messages(byId("branching"))).toEqual([
      "save-idea: 사람 확인 없이 외부에 써요.",
    ]);
  });

  it("finds each planted problem in the broken design", () => {
    const found = messages(byId("broken"));
    expect(found).toContain("archive: 시작에서 이 노드로 오는 길이 없어요.");
    expect(found).toContain("반복 횟수 한도가 없어요: checker, summarizer");
    expect(found).toContain(
      "writer: 입력 picked_idea을 앞에서 만드는 노드가 없어요.",
    );
    expect(found).toContain("req-2: 핵심 요구사항을 맡은 노드가 없어요.");
    expect(found).toContain("모델 호출 한도가 정해지지 않았어요.");
  });
});

describe("checkDesign", () => {
  it("accepts a loop only when a limit can leave it", () => {
    const design = byId("branching");
    const inside = {
      ...design,
      workflow: {
        ...design.workflow,
        loop_limits: [
          { node_ids: ["writer"], max_iterations: 2, on_exceeded: "review" },
        ],
      },
    };
    expect(messages(inside).some((m) => m.startsWith("한도를 넘어도"))).toBe(
      true,
    );
  });

  it("reports a missing entry and a dead end", () => {
    const design = byId("straight");
    const noEntry = removeElements(design, ["node-input"]);
    expect(messages(noEntry)[0]).toBe(
      "시작 노드가 없어요. 노드 하나를 시작으로 지정해 주세요.",
    );
    const deadEnd = addEdge(
      addNode(design, "code").design,
      "node-input",
      "code-1",
    );
    expect(messages(deadEnd)).toContain(
      "code-1: 이 노드에서 끝으로 가는 길이 없어요.",
    );
  });

  it("clears the write warning when a person checks first", () => {
    const design = byId("straight");
    const withTool = {
      ...design,
      nodes: design.nodes.map((node) =>
        node.id === "node-writer"
          ? {
              ...node,
              tools: [{ name: "t", access: "write" as const, reason: "r" }],
            }
          : node,
      ),
    };
    expect(messages(withTool)).toEqual([
      "node-writer: 사람 확인 없이 외부에 써요.",
    ]);
    const human = addNode(withTool, "human");
    const flow = addEdge(human.design, human.id, "node-writer");
    expect(messages(flow)).not.toContain(
      "node-writer: 사람 확인 없이 외부에 써요.",
    );
  });
});

describe("edits", () => {
  it("removes a node with everything that points to it", () => {
    const after = removeElements(byId("branching"), ["writer"]);
    expect(
      after.workflow.edges.some((e) => [e.source, e.target].includes("writer")),
    ).toBe(false);
    expect(after.workflow.loop_limits[0].node_ids).toEqual(["review"]);
    expect(after.requirements[2].node_ids).toEqual(["review"]);
  });

  it("renames a node everywhere it is referenced", () => {
    const after = renameNode(byId("branching"), "writer", "drafter");
    expect(JSON.stringify(after)).not.toContain('"writer"');
    expect(after.workflow.loop_limits[0].node_ids).toContain("drafter");
  });

  it("rejects an invalid or taken node name", () => {
    const design = byId("straight");
    expect(idProblem(design, "node-input", "1bad")).toMatch("영문자");
    expect(idProblem(design, "node-input", "node-writer")).toMatch("이미");
    expect(idProblem(design, "node-input", "ok_name")).toBeNull();
  });

  it("does not add the same connection twice", () => {
    const design = byId("straight");
    expect(addEdge(design, "node-input", "node-summarizer")).toBe(design);
  });

  it("parses ports and defaults the type", () => {
    expect(parsePorts("a: list\n\n b ")).toEqual([
      { name: "a", type: "list" },
      { name: "b", type: "string" },
    ]);
  });

  it("summarizes what differs from the original", () => {
    const design = byId("straight");
    const added = addNode(design, "agent");
    const after = updateEdge(
      addEdge(added.design, "node-input", added.id),
      "node-summarizer",
      "node-writer",
      { condition: "통과" },
    );
    expect(summarizeChanges(design, after)).toEqual([
      "노드 추가: agent-1",
      "연결 수정: node-summarizer → node-writer",
      "연결 추가: node-input → agent-1",
    ]);
    expect(summarizeChanges(design, design)).toEqual([]);
  });
});

describe("graph", () => {
  it("lays nodes top to bottom", () => {
    const layout = autoLayout(byId("straight"));
    expect(layout.get("node-input")!.y).toBeLessThan(
      layout.get("node-summarizer")!.y,
    );
    expect(layout.get("node-summarizer")!.y).toBeLessThan(
      layout.get("node-writer")!.y,
    );
  });

  it("keeps a moved node where the user put it", () => {
    const moved = new Map([["node-input", { x: 7, y: 9 }]]);
    const nodes = toFlowNodes(byId("straight"), moved, [], "node-writer", [
      "node-summarizer",
    ]);
    expect(nodes[0].position).toEqual({ x: 7, y: 9 });
    expect(nodes[0].data.isEntry).toBe(true);
    expect(nodes[1].data.highlighted).toBe(true);
    expect(nodes[2].selected).toBe(true);
    expect(nodes[2].data.isExit).toBe(true);
  });

  it("labels conditions and failure paths", () => {
    const edges = toFlowEdges(byId("branching"), null);
    const failure = edges.find((e) => e.id === "writer->finish")!;
    expect(failure.label).toBe("실패 시");
    expect(failure.className).toContain("failure");
    expect(edges.find((e) => e.id === "router->summarizer")!.label).toBe(
      "저장",
    );
  });

  it("routes loops and failure paths around the nodes", () => {
    const edges = toFlowEdges(byId("branching"), null);
    const side = (id: string) => edges.find((e) => e.id === id)!.sourceHandle;
    expect(side("review->writer")).toBe("side-out");
    expect(side("writer->finish")).toBe("side-out");
    expect(side("writer->review")).toBeUndefined();
  });

  it("carries the loop limit and issue count onto the node", () => {
    const design = byId("branching");
    const nodes = toFlowNodes(design, new Map(), checkDesign(design), null, []);
    expect(nodes.find((n) => n.id === "writer")!.data.loopLimit).toBe(3);
    expect(nodes.find((n) => n.id === "save-idea")!.data.issues).toBe(1);
  });
});

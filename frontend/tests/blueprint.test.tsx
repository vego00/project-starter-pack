// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  BlueprintPanel,
  layoutBlueprint,
  changedNodes,
  layoutSystem,
  mergeEdges,
  ServiceDiagram,
} from "../src/blueprint";
import { SERVICE_ICONS } from "../src/serviceIcons";
import type { BlueprintGraph, Journey } from "../src/api";
import { addRename } from "../src/design/edit";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const node = (
  id: string,
  kind: BlueprintGraph["nodes"][number]["kind"] = "code",
  card_id: string | null = null,
  icon: string | null = null,
  group: string | null = null,
) => ({ id, label: `${id} 이름`, kind, card_id, icon, group, rows: [] });
const edge = (source: string, target: string) => ({
  source,
  target,
  label: null,
  dashed: false,
});

function journey(overrides: Partial<Journey> = {}): Journey {
  return {
    journey_id: "e29a4ac6-f90c-4f97-91d6-d99acf27351f",
    revision: 1,
    status: "in_progress",
    idea: "아이디어",
    prompt: { type: "decision" } as Journey["prompt"],
    cards: [
      {
        card_id: "agent.topology",
        layer: "agent",
        stage: 4,
        needs_review: false,
        title: "Agent 구조",
        question: "구조는?",
        state: "pending",
        option_name: null,
        by: null,
        rationale: "",
      },
    ],
    warnings: [],
    notice: null,
    blueprint: {
      agent: {
        nodes: [
          node("input"),
          node("blank-agent.topology", "blank", "agent.topology"),
        ],
        edges: [edge("input", "blank-agent.topology")],
      },
      system: { nodes: [node("api", "sys")], edges: [] },
      notes: [],
      agent_is_draft: true,
    },
    can_reopen: false,
    ...overrides,
  };
}

describe("layoutBlueprint", () => {
  it("places each node after the longest path into it", () => {
    const points = layoutBlueprint({
      nodes: [node("a"), node("b"), node("c")],
      edges: [edge("a", "b"), edge("b", "c"), edge("a", "c")],
    });
    expect(points.a.x).toBeLessThan(points.b.x);
    expect(points.b.x).toBeLessThan(points.c.x);
  });

  it("gives every node a place when the graph loops", () => {
    const points = layoutBlueprint({
      nodes: [node("a"), node("b")],
      edges: [edge("a", "b"), edge("b", "a")],
    });
    expect(Object.keys(points).sort()).toEqual(["a", "b"]);
    expect(Number.isFinite(points.b.x)).toBe(true);
  });
});

describe("changedNodes", () => {
  it("names new and relabelled nodes and the targets of new edges", () => {
    const before: BlueprintGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("a", "b")],
    };
    const after: BlueprintGraph = {
      nodes: [node("a"), { ...node("b"), label: "바뀐 이름" }, node("c")],
      edges: [edge("a", "b"), edge("a", "c")],
    };

    expect([...changedNodes(before, after)].sort()).toEqual(["b", "c"]);
  });

  it("marks the target when only a connection was added", () => {
    const nodes = [node("a"), node("b")];

    expect([
      ...changedNodes({ nodes, edges: [] }, { nodes, edges: [edge("a", "b")] }),
    ]).toEqual(["b"]);
  });
});

describe("mergeEdges", () => {
  it("draws parallel edges once with every label", () => {
    const drawn = mergeEdges([
      { source: "a", target: "b", label: "저장", dashed: false },
      { source: "a", target: "b", label: "체크포인트", dashed: true },
      { source: "a", target: "b", label: "저장", dashed: true },
      { source: "b", target: "a", label: null, dashed: true },
    ]);

    expect(drawn).toEqual([
      {
        source: "a",
        target: "b",
        labels: ["저장", "체크포인트"],
        dashed: false,
      },
      { source: "b", target: "a", labels: [], dashed: true },
    ]);
  });
});

describe("ServiceDiagram", () => {
  const graph: BlueprintGraph = {
    nodes: [
      node("users", "sys", null, "person", "people"),
      node("api", "sys", null, "server", "app"),
      node("db", "sys", "data.primary_db", "postgresql", "data"),
      node("blank-model", "blank", "model.provider", null, "model"),
    ],
    edges: [edge("users", "api"), edge("api", "db")],
  };

  it("puts each group in its own column, left to right", () => {
    const points = layoutSystem(graph);
    expect(points.users.x).toBeLessThan(points.api.x);
    expect(points.api.x).toBeLessThan(points.db.x);
    expect(points["blank-model"].x).toBe(points.db.x);
    expect(points["blank-model"].y).toBeLessThan(points.db.y);
  });

  it("sends a line around the column it would otherwise cross", () => {
    const crossing: BlueprintGraph = {
      nodes: [
        node("api", "sys", null, "server", "app"),
        node("model", "sys", null, "agent", "model"),
        node("orchestration", "sys", null, "docker", "ops"),
      ],
      edges: [
        {
          source: "api",
          target: "orchestration",
          label: "실행 환경",
          dashed: true,
        },
      ],
    };
    const points = layoutSystem(crossing);
    const { container } = render(
      <svg>
        <ServiceDiagram graph={crossing} point={(id) => points[id]} />
      </svg>,
    );

    const label = container.querySelector(".bp-edge-label")!;
    const modelBox = container.querySelectorAll(".bp-box")[1];
    expect(Number(label.getAttribute("y"))).toBeLessThan(
      Number(modelBox.getAttribute("y")),
    );
  });

  it("shows a brand mark only for a chosen service, inside a titled box", () => {
    const points = layoutSystem(graph);
    const { container } = render(
      <svg>
        <ServiceDiagram graph={graph} point={(id) => points[id]} />
      </svg>,
    );

    const marks = [...container.querySelectorAll("path[fill^='#']")];
    expect(marks.map((mark) => mark.getAttribute("d"))).toEqual([
      SERVICE_ICONS.postgresql.path,
    ]);
    expect(container).toHaveTextContent("데이터");
    expect(container).toHaveTextContent("?");
  });
});

describe("BlueprintPanel", () => {
  function drawnGraph() {
    render(<BlueprintPanel journey={journey()} busy={false} act={vi.fn()} />);
    const svg = screen.getByRole("group", {
      name: "에이전트 흐름",
    }) as unknown as SVGSVGElement;
    return { svg, width: Number(svg.getAttribute("viewBox")!.split(" ")[2]) };
  }

  it("scales with the panel between readable and enlarged limits", () => {
    const { svg, width } = drawnGraph();
    expect(Number(svg.getAttribute("width"))).toBeCloseTo(width * 1.5);
    expect(parseFloat(svg.style.minWidth)).toBeCloseTo(width * 0.65);
  });

  it("follows the pointer when the graph is drawn smaller", () => {
    const { svg, width } = drawnGraph();
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({
      width: width / 2,
    } as DOMRect);
    const moved = screen.getByRole("button", { name: "코드 input 이름" });
    const before = moved.getAttribute("transform")!;
    const x = Number(before.match(/translate\(([\d.]+)/)![1]);

    // jsdom's pointer events carry no coordinates; React only reads the event type.
    const pointer = (type: string, clientX: number) =>
      fireEvent(
        moved,
        new MouseEvent(type, { bubbles: true, clientX, clientY: 100 }),
      );
    pointer("pointerdown", 100);
    pointer("pointermove", 150);
    pointer("pointerup", 150);

    expect(moved.getAttribute("transform")).toContain(`translate(${x + 100} `);
  });

  it("opens a decided card for change without removing it", async () => {
    const user = userEvent.setup();
    const act = vi.fn();
    const decided = journey();
    decided.cards = [{ ...decided.cards[0], state: "decided" }];
    render(<BlueprintPanel journey={decided} busy={false} act={act} />);

    await user.click(
      screen.getByRole("button", {
        name: "미정 blank-agent.topology 이름 다시 고르기",
      }),
    );

    expect(act).toHaveBeenCalledWith({
      action: "revise",
      card_id: "agent.topology",
    });
  });

  it("does not offer a change once the screen is not on a decision", async () => {
    const user = userEvent.setup();
    const act = vi.fn();
    const decided = journey({ prompt: null, can_reopen: false });
    decided.cards = [{ ...decided.cards[0], state: "decided" }];
    render(<BlueprintPanel journey={decided} busy={false} act={act} />);

    await user.click(screen.getByRole("button", { name: "에이전트 흐름" }));
    await user.click(
      screen.getByRole("button", { name: "미정 blank-agent.topology 이름" }),
    );

    expect(act).not.toHaveBeenCalled();
  });

  it("zooms with buttons and returns to fitting the panel", async () => {
    const user = userEvent.setup();
    const { svg, width } = drawnGraph();
    const fit = screen.getByRole("button", { name: "화면 맞춤" });
    expect(fit).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "확대" }));
    expect(Number(svg.getAttribute("width"))).toBeCloseTo(width * 1.25);
    expect(screen.getByText("125%")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "축소" }));
    expect(Number(svg.getAttribute("width"))).toBeCloseTo(width);

    await user.click(fit);
    expect(Number(svg.getAttribute("width"))).toBeCloseTo(width * 1.5);
    expect(fit).toBeDisabled();
  });

  it("zooms with ctrl and the wheel, and leaves a plain wheel to scroll", () => {
    const { svg } = drawnGraph();
    const canvas = svg.parentElement!;

    fireEvent.wheel(canvas, { deltaY: -100 });
    expect(screen.getByText("맞춤")).toBeVisible();

    fireEvent.wheel(canvas, { deltaY: -100, ctrlKey: true });
    expect(screen.getByText("125%")).toBeVisible();
  });

  describe("decisions that share or lack a service", () => {
    const decidedCard = (card_id: string) => ({
      ...journey().cards[0],
      card_id,
      state: "decided" as const,
    });
    const shared = () =>
      journey({
        cards: [
          decidedCard("data.primary_db"),
          decidedCard("data.vector_store"),
          decidedCard("data.checkpointer"),
        ],
        blueprint: {
          agent: { nodes: [], edges: [] },
          system: {
            nodes: [
              {
                ...node("database", "sys", null, "postgresql", "data"),
                rows: [
                  {
                    role: "데이터 저장",
                    label: "PostgreSQL",
                    card_id: "data.primary_db",
                  },
                  {
                    role: "벡터 검색",
                    label: "pgvector",
                    card_id: "data.vector_store",
                  },
                ],
              },
            ],
            edges: [],
          },
          notes: [
            {
              group: "data",
              label: "상태 저장: 메모리",
              card_id: "data.checkpointer",
            },
          ],
          agent_is_draft: true,
        },
      });

    async function openSystem(act = vi.fn()) {
      const user = userEvent.setup();
      render(<BlueprintPanel journey={shared()} busy={false} act={act} />);
      await user.click(screen.getByRole("button", { name: "시스템 구성" }));
      return { user, act };
    }

    it("opens each decision from its own line", async () => {
      const { user, act } = await openSystem();

      await user.click(
        screen.getByRole("button", {
          name: "시스템 벡터 검색: pgvector 다시 고르기",
        }),
      );

      expect(act).toHaveBeenCalledWith({
        action: "revise",
        card_id: "data.vector_store",
      });
    });

    it("moves the whole service from any of its lines", async () => {
      await openSystem();
      const line = screen.getByRole("button", {
        name: "시스템 데이터 저장: PostgreSQL 다시 고르기",
      });
      const service = line.parentElement!;
      const before = service.getAttribute("transform");

      fireEvent.keyDown(line, { key: "ArrowDown" });

      expect(service.getAttribute("transform")).not.toBe(before);
    });

    it("opens an answer that draws no service from below the graph", async () => {
      const { user, act } = await openSystem();

      await user.click(
        screen.getByRole("button", { name: "상태 저장: 메모리 다시 고르기" }),
      );

      expect(act).toHaveBeenCalledWith({
        action: "revise",
        card_id: "data.checkpointer",
      });
    });

    it("keeps those answers out of the agent graph", () => {
      render(<BlueprintPanel journey={shared()} busy={false} act={vi.fn()} />);

      expect(screen.queryByText("상태 저장: 메모리")).not.toBeInTheDocument();
    });

    it("gives a shared service room for every line", () => {
      const graph = shared().blueprint.system;
      const points = layoutSystem({
        ...graph,
        nodes: [
          ...graph.nodes,
          node("search", "sys", "data.vector_store", "search", "data"),
        ],
      });

      expect(points.search.y - points.database.y).toBeGreaterThanOrEqual(
        40 + 2 * 68,
      );
    });
  });

  it("moves a node with the arrow keys", () => {
    drawnGraph();
    const moved = screen.getByRole("button", { name: "코드 input 이름" });
    const x = Number(
      moved.getAttribute("transform")!.match(/translate\(([\d.]+)/)![1],
    );

    fireEvent.keyDown(moved, { key: "ArrowRight" });

    expect(moved.getAttribute("transform")).toContain(`translate(${x + 16} `);
  });

  it("says the examples are loading until they arrive", async () => {
    const user = userEvent.setup();
    let arrive = (_: Response) => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((done) => (arrive = done))),
    );
    render(<BlueprintPanel journey={journey()} busy={false} act={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "완성 예시" }));
    expect(
      screen.getByRole("button", { name: "예시를 불러오는 중…" }),
    ).toBeDisabled();

    arrive(Response.json([]));
    expect(
      await screen.findByRole("button", { name: "내 작업" }),
    ).toBeVisible();
  });

  it("moves to the card when a blank is pressed", async () => {
    const user = userEvent.setup();
    const act = vi.fn();
    render(<BlueprintPanel journey={journey()} busy={false} act={act} />);

    await user.click(
      screen.getByRole("button", {
        name: "미정 blank-agent.topology 이름",
      }),
    );

    expect(act).toHaveBeenCalledWith({
      action: "focus",
      card_id: "agent.topology",
    });
  });

  it("switches to the system graph", async () => {
    const user = userEvent.setup();
    render(<BlueprintPanel journey={journey()} busy={false} act={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "시스템 구성" }));

    expect(
      screen.getByRole("button", { name: "시스템 api 이름" }),
    ).toBeVisible();
  });

  it("shows a finished example without changing the journey", async () => {
    const user = userEvent.setup();
    const act = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json([
          {
            id: "basic",
            name: "웹 + 파이프라인",
            note: "기본형이에요.",
            blueprint: {
              agent: { nodes: [node("example-node")], edges: [] },
              system: { nodes: [], edges: [] },
              notes: [],
              agent_is_draft: true,
            },
          },
        ]),
      ),
    );
    render(<BlueprintPanel journey={journey()} busy={false} act={act} />);

    await user.click(screen.getByRole("button", { name: "완성 예시" }));
    await user.click(
      await screen.findByRole("button", { name: "웹 + 파이프라인" }),
    );

    expect(screen.getByText(/기본형이에요/)).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "코드 example-node 이름" }),
    );
    expect(act).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "내 작업" }));
    expect(
      screen.getByRole("button", { name: "코드 input 이름" }),
    ).toBeVisible();
  });

  it("offers the graph editor once a design exists", () => {
    const design = {
      status: "review_required",
      source: "mock",
      error: null,
      nodes: [],
      first_task: "",
      first_task_check: "",
      unknowns: [],
      warnings: [],
      files: [],
    };
    render(
      <BlueprintPanel
        journey={journey({ design })}
        busy={false}
        act={vi.fn()}
      />,
    );
    expect(screen.getByRole("link", { name: "그래프 편집" })).toHaveAttribute(
      "href",
      expect.stringContaining("design="),
    );
  });
});

describe("addRename", () => {
  it("keeps one mapping across renames in a row", () => {
    const once = addRename({}, "a", "b");
    expect(addRename(once, "b", "c")).toEqual({ a: "c" });
  });
});

// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  BlueprintPanel,
  layoutBlueprint,
  layoutSystem,
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
) => ({ id, label: `${id} 이름`, kind, card_id, icon, group });
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

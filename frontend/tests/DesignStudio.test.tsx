// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DesignStudio from "../src/design/DesignStudio";
import { DESIGN_CASES } from "../src/design/mock";

function stubGraphApis() {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "DOMMatrixReadOnly",
    class {
      m22 = 1;
    },
  );
}

beforeAll(stubGraphApis);
afterEach(cleanup);

async function openNode(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  await user.click(screen.getByText(/글로 보기/));
  const outline = screen.getByText(/글로 보기/).closest("details")!;
  await user.click(within(outline).getByRole("button", { name }));
}

const panel = () => screen.getByRole("complementary", { name: "선택한 항목" });

describe("DesignStudio", () => {
  it("says the data is an example and that edits are not saved", () => {
    render(<DesignStudio />);
    expect(screen.getByText("예시 데이터")).toBeVisible();
    expect(screen.getByText(/저장되지 않아요/)).toBeVisible();
  });

  it("selects a node by keyboard from the text outline", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    screen.getByText(/글로 보기/).focus();
    await user.keyboard("{Enter}");
    const outline = screen.getByText(/글로 보기/).closest("details")!;
    within(outline).getByRole("button", { name: "node-writer" }).focus();
    await user.keyboard("{Enter}");
    expect(
      within(panel()).getByRole("heading", { name: "node-writer" }),
    ).toBeVisible();
    expect(within(panel()).getByLabelText("하는 일")).toHaveValue(
      "요약을 바탕으로 기획서 초안을 써요",
    );
  });

  it("records an edit in the summary and undoes it", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    await openNode(user, "node-writer");
    const field = within(panel()).getByLabelText("하는 일");
    await user.clear(field);
    await user.type(field, "새로 고친 일");
    await user.tab();
    await user.click(
      within(panel()).getByRole("button", { name: "전체 보기" }),
    );
    expect(within(panel()).getByText("노드 수정: node-writer")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(within(panel()).getByText("처음 설계 그대로예요.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "다시 실행" }));
    expect(within(panel()).getByText("노드 수정: node-writer")).toBeVisible();
  });

  it("does not record an emptied required field", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    await openNode(user, "node-writer");
    await user.clear(within(panel()).getByLabelText("하는 일"));
    await user.tab();
    expect(screen.getByRole("button", { name: "되돌리기" })).toBeDisabled();
  });

  it("shows new problems after deleting a node", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    expect(
      within(panel()).getByText("구조에 막히는 곳이 없어요"),
    ).toBeVisible();
    await openNode(user, "node-writer");
    await user.click(
      within(panel()).getByRole("button", { name: "이 노드 삭제" }),
    );
    expect(within(panel()).getByText("고쳐야 할 점 2건")).toBeVisible();
    expect(
      within(panel()).getByText("req-2: 핵심 요구사항을 맡은 노드가 없어요."),
    ).toBeVisible();
    expect(within(panel()).getByText("맡은 노드가 없어요")).toBeVisible();
    expect(within(panel()).getByText("노드 삭제: node-writer")).toBeVisible();
  });

  it("connects nodes from the panel and adds a node", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    await user.click(screen.getByRole("button", { name: "사람 노드 추가" }));
    expect(
      within(panel()).getByRole("heading", { name: "human-1" }),
    ).toBeVisible();
    await user.selectOptions(
      within(panel()).getByLabelText("다음 노드 연결"),
      "node-writer",
    );
    await user.click(within(panel()).getByRole("button", { name: "연결" }));
    expect(
      within(panel()).getByRole("button", { name: "다음: node-writer" }),
    ).toBeVisible();
  });

  it("keeps the panel on a renamed node and refuses a taken name", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    await openNode(user, "node-writer");
    const name = within(panel()).getByLabelText("노드 이름");
    await user.clear(name);
    await user.type(name, "node-input");
    await user.tab();
    expect(within(panel()).getByRole("alert")).toHaveTextContent("이미 있어요");
    await user.clear(name);
    await user.type(name, "drafter");
    await user.tab();
    expect(
      within(panel()).getByRole("heading", { name: "drafter" }),
    ).toBeVisible();
  });

  it("marks requirement owners and resets edits when the example changes", async () => {
    const user = userEvent.setup();
    render(<DesignStudio />);
    await user.selectOptions(screen.getByLabelText("예시"), "broken");
    expect(within(panel()).getByText(/고쳐야 할 점 \d건/)).toBeVisible();
    const requirement = within(panel()).getByRole("button", {
      name: /메모를 정리하지 못해요/,
    });
    await user.click(requirement);
    expect(requirement).toHaveAttribute("aria-pressed", "true");
    await user.selectOptions(screen.getByLabelText("예시"), "straight");
    expect(within(panel()).getByText("처음 설계 그대로예요.")).toBeVisible();
  });
});

describe("DesignStudio for a journey", () => {
  const ID = "e29a4ac6-f90c-4f97-91d6-d99acf27351f";
  afterEach(() => {
    vi.unstubAllGlobals();
    stubGraphApis();
  });

  function serve(design: { status: number; body: unknown }) {
    const fetchMock = vi.fn(async (path: string) => {
      if (path.endsWith("/design"))
        return new Response(JSON.stringify(design.body), {
          status: design.status,
        });
      return new Response(
        JSON.stringify({
          journey_id: ID,
          revision: 1,
          status: "completed",
          idea: "실제 여정의 아이디어",
          prompt: null,
          cards: [],
          warnings: [],
          notice: null,
          blueprint: {
            agent: { nodes: [], edges: [] },
            system: { nodes: [], edges: [] },
            agent_is_draft: false,
          },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("shows the journey's own design, not the examples", async () => {
    const fetchMock = serve({ status: 200, body: DESIGN_CASES[1].design });
    render(<DesignStudio journeyId={ID} />);

    expect(await screen.findByText(/실제 여정의 아이디어/)).toBeVisible();
    expect(screen.queryByText("예시 데이터")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/journeys/${ID}/design`,
      expect.anything(),
    );
    await userEvent.setup().click(screen.getByText(/글로 보기/));
    const outline = screen.getByText(/글로 보기/).closest("details")!;
    const first = DESIGN_CASES[1].design.nodes[0].id;
    expect(within(outline).getByRole("button", { name: first })).toBeVisible();
  });

  function editFirstNode() {
    const user = userEvent.setup();
    return (async () => {
      await screen.findByText(/실제 여정의 아이디어/);
      await user.click(screen.getByText(/글로 보기/));
      const outline = screen.getByText(/글로 보기/).closest("details")!;
      const first = DESIGN_CASES[1].design.nodes[0].id;
      await user.click(within(outline).getByRole("button", { name: first }));
      const field = within(panel()).getByLabelText("하는 일");
      await user.clear(field);
      await user.type(field, "직접 고친 일");
      await user.tab();
      return user;
    })();
  }

  it("saves edits with the revision they were based on", async () => {
    const body = { ...DESIGN_CASES[1].design, design_revision: 3 };
    const fetchMock = serve({ status: 200, body });
    render(<DesignStudio journeyId={ID} />);

    const user = await editFirstNode();
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByText(/저장했어요/)).toBeVisible();
    const call = fetchMock.mock.calls.find(
      (args) => (args as unknown[])[1] && JSON.stringify(args).includes("POST"),
    ) as unknown as [string, RequestInit];
    const sent = JSON.parse(call[1].body as string);
    expect(sent.design_revision).toBe(3);
    expect(sent.nodes[0].responsibility).toBe("직접 고친 일");
  });

  it("shows why the server refused the edits", async () => {
    const body = { ...DESIGN_CASES[1].design, design_revision: 3 };
    const fetchMock = serve({ status: 200, body });
    render(<DesignStudio journeyId={ID} />);
    const user = await editFirstNode();
    fetchMock.mockImplementationOnce(async () =>
      Response.json(
        {
          error: {
            code: "design_has_errors",
            message: "노드 A의 입력을 만드는 곳이 없어요",
          },
        },
        { status: 422 },
      ),
    );

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "입력을 만드는 곳이 없어요",
    );
  });

  it("explains when the design is not ready", async () => {
    serve({
      status: 409,
      body: {
        error: {
          code: "design_unavailable",
          message: "결정을 모두 마치면 볼 수 있어요.",
        },
      },
    });
    render(<DesignStudio journeyId={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "결정을 모두 마치면 볼 수 있어요.",
    );
  });
});

// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";

const ID = "e29a4ac6-f90c-4f97-91d6-d99acf27351f";
const LAST_KEY = "starter-pack:last-journey:v1";

function optionView(id: string, name: string, extra = {}) {
  return {
    option: {
      id,
      name,
      summary: `${name} 설명`,
      pros: [`${name} 장점`],
      cons: [`${name} 단점`],
      learning_difficulty: "low",
      ops_burden: "medium",
      cost_nature: "추가 비용 없음",
    },
    note: `${name} 설명`,
    blocked_reason: null,
    implies: {},
    implied_messages: [],
    warnings: [],
    must_change: [],
    artifacts: [],
    ...extra,
  };
}

const recommendation = {
  status: "recommended",
  option_id: "none",
  confidence: 0.9,
  reason: "기본값 이유",
  decider: "mock",
};

function decisionPrompt(overrides = {}, cardOverrides = {}) {
  return {
    type: "decision",
    card: {
      card_id: "agent.hitl",
      version: 1,
      layer: "agent",
      question: "사람 확인이 필요한가요?",
      options: [
        optionView("none", "없음"),
        optionView("approval", "승인", {
          blocked_reason: "체크포인터가 필요합니다.",
        }),
      ],
      recommendation,
      evidence: [],
      advice_source: "mock",
      to_review: [],
      learning_refs: [],
      div_refs: ["P1"],
      ...cardOverrides,
    },
    qa: [],
    conflicts: [],
    progress: { total: 2, decided: 0, implied: 0, deferred: 0 },
    error: null,
    ...overrides,
  };
}

function cards(first = "current", second = "pending") {
  const status = (card_id: string, layer: string, state: string) => ({
    card_id,
    layer,
    stage: layer === "agent" ? 4 : 5,
    needs_review: false,
    title: `${card_id} 제목`,
    question: `${card_id} 질문`,
    state,
    option_id: state === "decided" ? "none" : null,
    option_name: state === "decided" ? "없음" : null,
    by: state === "decided" ? "user" : null,
    rationale: "",
  });
  return [
    status("agent.hitl", "agent", first),
    status("cloud.target", "cloud", second),
  ];
}

function journey(overrides = {}) {
  return {
    journey_id: ID,
    revision: 7,
    status: "in_progress",
    idea: "강의 자료를 찾아 답하는 서비스",
    prompt: decisionPrompt(),
    cards: cards(),
    warnings: [],
    notice: "모델 미연결 상태입니다.",
    blueprint: {
      agent: { nodes: [], edges: [] },
      system: { nodes: [], edges: [] },
      notes: [],
      agent_is_draft: true,
    },
    modules: [],
    ...overrides,
  };
}

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

type Handler = (
  url: string,
  init?: RequestInit,
) => Response | Promise<Response>;

function stubFetch(handler: Handler) {
  const mock = vi.fn(async (url: string, init?: RequestInit) =>
    handler(url, init),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

function bodyOf(call: unknown[]) {
  return JSON.parse((call[1] as RequestInit).body as string);
}

function stubStorage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  });
  return items;
}

async function startWith(view: unknown) {
  const user = userEvent.setup();
  const mock = stubFetch(() => Response.json(view, { status: 201 }));
  render(<App />);
  await user.type(
    screen.getByLabelText("프로젝트 아이디어"),
    "강의 자료를 찾아 답하는 서비스",
  );
  await user.click(screen.getByRole("button", { name: "보내기" }));
  return { user, mock };
}

async function openStage(
  user: ReturnType<typeof userEvent.setup>,
  name: RegExp,
) {
  await user.click(await screen.findByRole("button", { name }));
}

beforeEach(() => {
  stubStorage();
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("starting", () => {
  it("requires a meaningful idea and sends it trimmed", async () => {
    const user = userEvent.setup();
    const mock = stubFetch(() => Response.json(journey(), { status: 201 }));
    render(<App />);
    expect(
      screen.getByText(/개인정보나 회사 기밀은 적지 마세요/),
    ).toBeVisible();
    const submit = screen.getByRole("button", { name: "보내기" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("프로젝트 아이디어"), "  짧음  ");
    expect(submit).toBeDisabled();

    await user.clear(screen.getByLabelText("프로젝트 아이디어"));
    await user.click(
      screen.getAllByRole("button", { name: /부트캠프 강의/ })[0],
    );
    await user.click(submit);

    expect(bodyOf(mock.mock.calls[0]).idea).toMatch(/^부트캠프/);
    expect(
      await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" }),
    ).toBeInTheDocument();
  });

  it("shows the server's message when starting fails and keeps the input", async () => {
    const user = userEvent.setup();
    stubFetch(() =>
      errorResponse(
        503,
        "persistence_unavailable",
        "저장소가 연결되어 있지 않아요.",
      ),
    );
    render(<App />);
    const input = screen.getByLabelText("프로젝트 아이디어");
    await user.type(input, "강의 자료를 찾아 답하는 서비스");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("저장소가");
    expect(input).toHaveValue("강의 자료를 찾아 답하는 서비스");
  });

  it("explains a network failure", async () => {
    const user = userEvent.setup();
    stubFetch(() => {
      throw new TypeError("failed");
    });
    render(<App />);
    await user.type(
      screen.getByLabelText("프로젝트 아이디어"),
      "강의 자료를 찾아 답하는 서비스",
    );
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "서버에 연결할 수 없어요",
    );
  });

  it("rejects a response in an unexpected shape", async () => {
    const user = userEvent.setup();
    stubFetch(() => Response.json({ unexpected: true }, { status: 201 }));
    render(<App />);
    await user.type(
      screen.getByLabelText("프로젝트 아이디어"),
      "강의 자료를 찾아 답하는 서비스",
    );
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("결과 형식");
  });
});

describe("restoring", () => {
  it("reopens the journey in the address and remembers it", async () => {
    const items = stubStorage();
    window.history.replaceState(null, "", `/?journey=${ID}`);
    const mock = stubFetch(() => Response.json(journey()));
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" }),
    ).toBeVisible();
    expect(mock.mock.calls[0][0]).toBe(`/api/v1/journeys/${ID}`);
    expect(items.get(LAST_KEY)).toBe(ID);
  });

  it("reopens the last journey from storage", async () => {
    stubStorage({ [LAST_KEY]: ID });
    stubFetch(() => Response.json(journey()));
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" }),
    ).toBeVisible();
    expect(window.location.search).toContain(ID);
  });

  it("reopens a journey saved before the change preview existed", async () => {
    stubStorage({ [LAST_KEY]: ID });
    const saved: unknown = JSON.parse(
      JSON.stringify(journey()),
      (key: string, value: unknown) =>
        key === "must_change" || key === "to_review" ? undefined : value,
    );
    stubFetch(() => Response.json(saved));
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" }),
    ).toBeVisible();
  });

  it("falls back to a new project when the journey no longer exists", async () => {
    const items = stubStorage({ [LAST_KEY]: ID });
    stubFetch(() =>
      errorResponse(404, "journey_not_found", "여정을 찾을 수 없어요."),
    );
    render(<App />);

    expect(await screen.findByLabelText("프로젝트 아이디어")).toBeVisible();
    expect(items.has(LAST_KEY)).toBe(false);
  });

  it("keeps the saved journey when the server is only temporarily down", async () => {
    const items = stubStorage({ [LAST_KEY]: ID });
    stubFetch(() =>
      errorResponse(503, "journey_failed", "지금은 처리하지 못했어요."),
    );
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("지금은");
    expect(items.get(LAST_KEY)).toBe(ID);
  });

  it("works when browser storage is unavailable", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    });
    await startWith(journey());

    expect(
      await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" }),
    ).toBeVisible();
    expect(window.location.search).toContain(ID);
  });
});

describe("workspace tabs", () => {
  const press = (name: string) => screen.findByRole("button", { name });

  it("closes the card tab to give the graph the page", async () => {
    const { user } = await startWith(journey());

    await user.click(await press("카드 닫기"));
    expect(screen.getByRole("main")).toHaveClass("no-card");
    expect(await press("카드 열기")).toHaveAttribute("aria-expanded", "false");

    await user.click(await press("카드 열기"));
    expect(screen.getByRole("main")).not.toHaveClass("no-card");
  });

  it("asks before leaving a journey in progress", async () => {
    const { user } = await startWith(journey());

    await user.click(await press("새 프로젝트"));
    expect(screen.queryByLabelText("프로젝트 아이디어")).toBeNull();
    await user.click(await press("계속하기"));
    expect(screen.queryByLabelText("프로젝트 아이디어")).toBeNull();

    await user.click(await press("새 프로젝트"));
    await user.click(await press("나가기"));
    expect(screen.getByLabelText("프로젝트 아이디어")).toBeVisible();
  });

  it("shows the card tab when moving to another card", async () => {
    const { user } = await startWith(journey());

    await user.click(await press("카드 닫기"));
    await openStage(user, /^시스템 구성 \d/);
    await user.click(await press("cloud.target 제목 먼저 정하기"));

    expect(screen.getByRole("main")).not.toHaveClass("no-card");
  });

  it("opens one stage at a time from the strip", async () => {
    const { user } = await startWith(journey());
    const tab = await screen.findByRole("button", {
      name: /^에이전트 설계 \d/,
    });
    expect(tab).toHaveAttribute("aria-expanded", "false");

    await user.click(tab);
    expect(tab).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("agent.hitl 제목")).toBeVisible();

    await openStage(user, /^시스템 구성 \d/);
    expect(tab).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("agent.hitl 제목")).toBeNull();
  });
});

describe("theme", () => {
  it("switches between light and dark from the header", async () => {
    const { user } = await startWith(journey());
    const before = document.documentElement.dataset.theme;
    const name = before === "dark" ? "라이트 모드" : "다크 모드";

    await user.click(await screen.findByRole("button", { name }));

    expect(document.documentElement.dataset.theme).not.toBe(before);
  });
});

describe("decision card", () => {
  it("is honest that the recommendation is a mock default", async () => {
    await startWith(journey());

    expect(await screen.findByText("추천")).toBeVisible();
    expect(screen.queryByText(/확신도/)).not.toBeInTheDocument();
    expect(screen.queryByText(/AI가 내 프로젝트/)).not.toBeInTheDocument();
    expect(screen.getByText("모델 미연결 상태입니다.")).toBeVisible();
  });

  it("sends the current revision when the recommended option is taken", async () => {
    const { user, mock } = await startWith(journey());

    await user.click(await screen.findByRole("button", { name: "없음 선택" }));

    expect(bodyOf(mock.mock.calls[1])).toEqual({
      revision: 7,
      action: { action: "accept_recommendation" },
    });
  });

  it("disables a blocked option and explains why", async () => {
    await startWith(journey());

    expect(
      await screen.findByRole("button", { name: "승인 선택" }),
    ).toBeDisabled();
    expect(screen.getByText(/체크포인터가 필요합니다/)).toBeVisible();
  });

  it("offers no shortcut when comparison is needed", async () => {
    await startWith(
      journey({
        prompt: decisionPrompt(
          {},
          {
            recommendation: {
              status: "needs_comparison",
              option_id: null,
              confidence: null,
              reason: "",
              decider: "jev",
            },
          },
        ),
      }),
    );

    expect(await screen.findByText(/비교 필요/)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "추천대로 진행" }),
    ).not.toBeInTheDocument();
  });

  it("shows confidence only from a real decider", async () => {
    await startWith(
      journey({
        prompt: decisionPrompt(
          {},
          { recommendation: { ...recommendation, decider: "jev" } },
        ),
      }),
    );

    expect(await screen.findByText("판단 확신도 90%")).toBeVisible();
  });

  it.each([
    ["llm", /AI가 내 프로젝트를 기준으로/],
    ["card_text", /AI 설명을 만들지 못해/],
  ])("explains where %s option text came from", async (source, text) => {
    await startWith(
      journey({ prompt: decisionPrompt({}, { advice_source: source }) }),
    );

    expect(await screen.findByText(text)).toBeVisible();
  });

  it("labels linked notes as personal notes, not lecture originals", async () => {
    await startWith(
      journey({
        prompt: decisionPrompt(
          {},
          {
            evidence: [
              {
                source_id: "note-1",
                title: "AX Work",
                kind: "personal_note",
                location: "Ch. 2",
                why: "사람의 책임을 다룹니다.",
                url: "https://example.com/note",
              },
            ],
          },
        ),
      }),
    );

    const link = await screen.findByRole("link", { name: "AX Work" });
    expect(link).toHaveAttribute("href", "https://example.com/note");
    expect(
      screen.getByText(/개인 필기이며 강의 원문이 아니에요/),
    ).toBeVisible();
    expect(screen.queryByText(/연결된 강의 자료 없음/)).not.toBeInTheDocument();
  });

  it("shows what an option brings along", async () => {
    await startWith(
      journey({
        prompt: decisionPrompt(
          {},
          {
            options: [
              optionView("none", "없음", {
                implied_messages: ["서빙도 함께 정해집니다."],
                warnings: ["GPU를 확인하세요."],
              }),
              optionView("b", "비"),
            ],
          },
        ),
      }),
    );

    expect(await screen.findByText("서빙도 함께 정해집니다.")).toBeVisible();
    expect(screen.getByText("GPU를 확인하세요.")).toBeVisible();
  });

  it("renders text as text, not markup", async () => {
    await startWith(
      journey({
        prompt: decisionPrompt({ error: "<img src=x onerror=alert(1)>" }),
      }),
    );

    await screen.findByRole("alert");
    expect(document.querySelector("img")).toBeNull();
  });

  it("asks a question and shows the answer", async () => {
    const { user, mock } = await startWith(journey());
    mock.mockImplementation(async () =>
      Response.json(
        journey({
          revision: 9,
          prompt: decisionPrompt({
            qa: [
              {
                card_id: "agent.hitl",
                question: "뭐예요?",
                answer: "고정 응답",
                answered_by: "mock",
              },
            ],
          }),
        }),
      ),
    );

    await user.type(
      await screen.findByLabelText("이 카드에 대해 질문하기"),
      "뭐예요?",
    );
    await user.click(screen.getByRole("button", { name: "질문" }));

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "ask",
      question: "뭐예요?",
    });
    expect(await screen.findByText("고정 응답")).toBeVisible();
  });

  it("can defer and accept the recommendation", async () => {
    const { user, mock } = await startWith(journey());

    await user.click(
      await screen.findByRole("button", { name: "나중에 결정" }),
    );
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2));
    expect(bodyOf(mock.mock.calls[1]).action).toEqual({ action: "defer" });

    await user.click(screen.getByRole("button", { name: "없음 선택" }));
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(3));
    expect(bodyOf(mock.mock.calls[2]).action).toEqual({
      action: "accept_recommendation",
    });
  });

  it("ignores a second click while a request is in flight", async () => {
    const { user, mock } = await startWith(journey());
    const button = await screen.findByRole("button", { name: "없음 선택" });
    let release = (_: Response) => {};
    mock.mockImplementation(
      () => new Promise<Response>((resolve) => (release = resolve)),
    );

    await user.click(button);
    await user.click(button);
    expect(mock).toHaveBeenCalledTimes(2);
    expect(button).toBeDisabled();

    release(Response.json(journey({ revision: 8 })));
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("reloads the latest state after a stale submission", async () => {
    const { user, mock } = await startWith(journey());
    const newer = journey({
      revision: 12,
      prompt: decisionPrompt({}, { question: "최신 카드 질문" }),
    });
    mock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? errorResponse(409, "stale_revision", "화면이 최신 상태가 아니에요.")
        : Response.json(newer),
    );

    await user.click(await screen.findByRole("button", { name: "없음 선택" }));

    expect(
      await screen.findByRole("heading", { name: "최신 카드 질문" }),
    ).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("최신 상태가 아니에요");
  });
});

describe("start screen", () => {
  const field = (name: string, kind: string, extra = {}) => ({
    name,
    label: `${name} 이름`,
    kind,
    choices: [],
    free_text: false,
    rule_read: false,
    value: null,
    display: null,
    source: null,
    why: null,
    ...extra,
  });
  const startView = (overrides = {}) => ({
    mode: "model",
    fields: [
      field("goal", "text", {
        value: "답을 찾는 상태",
        display: "답을 찾는 상태",
        source: "said",
      }),
      field("has_gpu", "choice", {
        rule_read: true,
        asked_in: "모델 제공자",
        choices: [
          { value: "yes", label: "있어요" },
          { value: "no", label: "없어요" },
        ],
      }),
      field("data_traits", "multi", {
        rule_read: true,
        asked_in: "데이터 저장소",
        choices: [
          { value: "문서 검색 필요", label: "문서 검색 필요" },
          { value: "개인정보 포함", label: "개인정보 포함" },
        ],
        value: ["문서 검색 필요"],
        display: "문서 검색 필요",
        source: "said",
      }),
      field("budget", "choice", {
        free_text: true,
        asked_in: "모델 제공자",
        value: "무료로만",
        display: "무료로만",
        source: "default",
        why: "비용이 없는 선택지부터 보는 기준이에요.",
      }),
    ],
    chat: [
      { role: "user", text: "아이디어", changes: [], rejected: [] },
      {
        role: "assistant",
        text: "2칸을 채웠어요. GPU 장비가 있나요?",
        changes: ["목표", "다루는 데이터"],
        rejected: [],
      },
    ],
    revision: 4,
    missing: ["context"],
    submit: { action: "gcb", goal: "답을 찾는 상태", answers: {} },
    ...overrides,
  });
  /** The default fields with one of them changed. */
  const withField = (index: number, change: object) =>
    startView().fields.map((item, at) =>
      at === index ? { ...item, ...change } : item,
    );
  const atStart = (overrides = {}) =>
    journey({
      revision: 2,
      prompt: {
        type: "gcb",
        draft: { goal: "", context: "", boundary: "" },
        source: "llm",
        error: null,
      },
      start: startView(overrides),
    });

  async function open(view: unknown, reply: Handler) {
    const user = userEvent.setup();
    const mock = stubFetch((url, init) =>
      url.includes("/start/")
        ? reply(url, init)
        : Response.json(view, { status: 201 }),
    );
    render(<App />);
    await user.type(
      screen.getByLabelText("프로젝트 아이디어"),
      "강의 자료를 찾아 답하는 서비스",
    );
    await user.click(screen.getByRole("button", { name: "보내기" }));
    await screen.findByRole("log", { name: "시작 대화" });
    return { user, mock };
  }

  it("shows what was filled, from where, and what is left", async () => {
    await open(atStart(), () => Response.json(atStart()));

    expect(
      screen.getByText("2칸을 채웠어요. GPU 장비가 있나요?"),
    ).toBeVisible();
    const right = screen.getByRole("complementary", {
      name: "추천에 쓰는 정보",
    });
    expect(within(right).getByText("기본값")).toBeVisible();
    expect(
      within(right).getByText("비용이 없는 선택지부터 보는 기준이에요."),
    ).toBeVisible();
    expect(within(right).getByText("비어 있음")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "결정 시작하기" }),
    ).toBeDisabled();
    expect(screen.getByText(/필수 칸 1개가 비어 있어요/)).toBeVisible();
    expect(screen.queryByRole("region", { name: "설계 그래프" })).toBeNull();
  });

  it("marks the goal as required and groups the optional info by card", async () => {
    await open(atStart(), () => Response.json(atStart()));

    const left = screen.getByRole("complementary", { name: "프로젝트 목표" });
    expect(within(left).getByText("필수 · 1 / 1칸")).toBeVisible();
    const right = screen.getByRole("complementary", {
      name: "추천에 쓰는 정보",
    });
    expect(within(right).getByText("선택")).toBeVisible();
    const groups = within(right).getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "모델 제공자 카드",
      "데이터 저장소 카드",
    ]);
    expect(within(groups[0]).getByText("has_gpu 이름")).toBeVisible();
    expect(within(groups[0]).getByText("budget 이름")).toBeVisible();
    expect(
      screen.getByText("오른쪽 정보는 비워 둬도 결정을 시작할 수 있어요."),
    ).toBeVisible();
  });

  it("starts with the goal filled though info is blank", async () => {
    await open(atStart({ missing: [] }), () => Response.json(atStart()));

    expect(screen.getByRole("button", { name: "결정 시작하기" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "목표 빈칸은 알아서 채워 주세요" }),
    ).toBeDisabled();
  });

  it("sends a message about the field in focus and keeps it when it fails", async () => {
    const { user, mock } = await open(atStart(), () =>
      errorResponse(503, "start_reply_failed", "문장을 정리하지 못했어요."),
    );

    await user.click(
      screen.getByRole("button", { name: "has_gpu 이름 고치기" }),
    );
    expect(screen.getByText("has_gpu 이름 고치는 중")).toBeVisible();
    const box = screen.getByLabelText("더 알려 주기");
    await user.type(box, "GPU는 없어요{Enter}");

    const sent = mock.mock.calls.at(-1)!;
    expect(sent[0]).toContain("/start/messages");
    expect(bodyOf(sent)).toEqual({
      revision: 4,
      text: "GPU는 없어요",
      focus: "has_gpu",
    });
    expect(await screen.findByText("문장을 정리하지 못했어요.")).toBeVisible();
    expect(box).toHaveValue("GPU는 없어요");
  });

  describe("while the first idea is read", () => {
    function slowStart() {
      let answer: (response: Response) => void = () => {};
      stubFetch(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }),
      );
      return (response: Response) => answer(response);
    }

    async function sendIdea(user: ReturnType<typeof userEvent.setup>) {
      render(<App />);
      await user.type(
        screen.getByLabelText("프로젝트 아이디어"),
        "강의 자료를 찾아 답하는 서비스",
      );
      await user.click(screen.getByRole("button", { name: "보내기" }));
    }

    it("turns into the chat at once and says what it is doing", async () => {
      const user = userEvent.setup();
      const reply = slowStart();
      await sendIdea(user);

      const log = screen.getByRole("log", { name: "시작 대화" });
      expect(
        within(log).getByText("강의 자료를 찾아 답하는 서비스"),
      ).toBeVisible();
      expect(within(log).getByText("보낸 문장을 읽고 있어요")).toBeVisible();
      expect(within(log).getByText(/초 지났어요/)).toBeVisible();
      expect(screen.getByLabelText("더 알려 주기")).toBeDisabled();
      expect(
        screen.getAllByText("문장을 다 읽으면 여기에 채워져요."),
      ).toHaveLength(2);

      reply(Response.json(atStart(), { status: 201 }));
      expect(await screen.findByText(/초 걸렸어요/)).toBeVisible();
      expect(screen.getAllByText("방금 채움").length).toBeGreaterThan(0);
      expect(screen.queryByText("보낸 문장을 읽고 있어요")).toBeNull();
    });

    it("goes back to the start screen with the idea kept when it fails", async () => {
      const user = userEvent.setup();
      const reply = slowStart();
      await sendIdea(user);

      reply(
        errorResponse(503, "start_reply_failed", "잠시 후 다시 보내 주세요."),
      );
      expect(
        await screen.findByText("잠시 후 다시 보내 주세요."),
      ).toBeVisible();
      expect(screen.getByLabelText("프로젝트 아이디어")).toHaveValue(
        "강의 자료를 찾아 답하는 서비스",
      );
      expect(screen.queryByRole("log", { name: "시작 대화" })).toBeNull();
    });

    it("says what a reload would lose once it takes long", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const user = userEvent.setup({
          advanceTimers: vi.advanceTimersByTime,
        });
        slowStart();
        await sendIdea(user);
        expect(screen.queryByText(/새로고침하면/)).toBeNull();

        await act(async () => {
          vi.advanceTimersByTime(41_000);
        });
        expect(screen.getByText(/새로고침하면 처음부터/)).toBeVisible();
      } finally {
        vi.useRealTimers();
      }
    });
  });

  it("answers the asked question by tapping one of its choices", async () => {
    const asking = {
      role: "assistant",
      text: "2칸을 채웠어요. GPU 장비가 있나요?",
      changes: ["목표"],
      rejected: [],
      asks: "has_gpu",
    };
    const view = atStart({
      chat: [asking],
      fields: withField(1, { default: "no" }),
    });
    const { user, mock } = await open(view, () => Response.json(view));

    const answers = screen.getByRole("group", { name: "has_gpu 이름 고르기" });
    expect(
      within(answers).getByRole("button", { name: /없어요/ }),
    ).toHaveTextContent("기본값");
    const right = screen.getByRole("complementary", {
      name: "추천에 쓰는 정보",
    });
    expect(within(right).getByText("지금 묻는 칸")).toBeVisible();

    await user.click(within(answers).getByRole("button", { name: "있어요" }));
    const sent = mock.mock.calls.at(-1)!;
    expect(sent[0]).toContain("/start/answers");
    expect(bodyOf(sent)).toEqual({
      revision: 4,
      change: { field: "has_gpu", value: "yes" },
    });
  });

  it("answers a several-choice question only when confirmed", async () => {
    const view = atStart({
      chat: [
        {
          role: "assistant",
          text: "다루는 데이터를 골라 주세요.",
          changes: [],
          rejected: [],
          asks: "data_traits",
        },
      ],
      fields: withField(2, { value: null, display: null, source: null }),
    });
    const { user, mock } = await open(view, () => Response.json(view));
    const calls = mock.mock.calls.length;

    const answers = screen.getByRole("group", {
      name: "data_traits 이름 고르기, 여러 개 고를 수 있어요",
    });
    const confirm = within(answers).getByRole("button", {
      name: "골라서 정하기",
    });
    expect(confirm).toBeDisabled();
    await user.click(
      within(answers).getByRole("button", { name: "문서 검색 필요" }),
    );
    await user.click(
      within(answers).getByRole("button", { name: "개인정보 포함" }),
    );
    expect(mock.mock.calls).toHaveLength(calls);

    await user.click(
      within(answers).getByRole("button", { name: "고른 2개로 정하기" }),
    );
    expect(bodyOf(mock.mock.calls.at(-1)!)).toEqual({
      revision: 4,
      change: {
        field: "data_traits",
        values: ["문서 검색 필요", "개인정보 포함"],
      },
    });
  });

  it("shows a tapped answer as one and offers no choices once the field is set", async () => {
    const view = atStart({
      chat: [
        {
          role: "user",
          text: "있어요",
          changes: [],
          rejected: [],
          picked: true,
        },
        {
          role: "assistant",
          text: "GPU 장비를 정했어요.",
          changes: ["GPU 장비"],
          rejected: [],
          asks: "has_gpu",
        },
      ],
      fields: withField(1, {
        value: "yes",
        display: "있어요",
        source: "picked",
      }),
    });
    await open(view, () => Response.json(view));

    expect(screen.getByText("눌러서 고름")).toBeVisible();
    expect(
      screen.queryByRole("group", { name: "has_gpu 이름 고르기" }),
    ).toBeNull();
  });

  it("picks choices in a panel, one or several", async () => {
    const { user, mock } = await open(atStart(), () =>
      Response.json(atStart()),
    );

    await user.click(
      screen.getByRole("button", { name: "has_gpu 이름 고치기" }),
    );
    await user.click(screen.getByRole("button", { name: "없어요" }));
    expect(bodyOf(mock.mock.calls.at(-1)!)).toEqual({
      revision: 4,
      change: { field: "has_gpu", value: "no" },
    });

    await user.click(
      screen.getByRole("button", { name: "data_traits 이름 고치기" }),
    );
    await user.click(screen.getByRole("button", { name: "개인정보 포함" }));
    expect(bodyOf(mock.mock.calls.at(-1)!).change).toEqual({
      field: "data_traits",
      values: ["문서 검색 필요", "개인정보 포함"],
    });
  });

  it("fills the blanks, then starts the journey with the checked values", async () => {
    const filled = atStart({ missing: [] });
    const { user, mock } = await open(atStart(), (url) =>
      url.includes("/start/fill")
        ? Response.json(filled)
        : Response.json(atStart()),
    );

    await user.click(
      screen.getByRole("button", { name: "목표 빈칸은 알아서 채워 주세요" }),
    );
    expect(mock.mock.calls.at(-1)![0]).toContain("/start/fill");
    const begin = screen.getByRole("button", { name: "결정 시작하기" });
    await waitFor(() => expect(begin).toBeEnabled());

    await user.click(begin);
    expect(bodyOf(mock.mock.calls.at(-1)!)).toEqual({
      revision: 2,
      action: { action: "gcb", goal: "답을 찾는 상태", answers: {} },
    });
  });

  it("has no conversation without a model", async () => {
    const formOnly = atStart({
      mode: "form",
      chat: [{ role: "user", text: "아이디어", changes: [], rejected: [] }],
    });
    await open(formOnly, () => Response.json(formOnly));

    expect(
      screen.getByText(/모델이 연결되지 않아 대화로 채울 수 없어요/),
    ).toBeVisible();
    expect(screen.queryByLabelText("더 알려 주기")).toBeNull();
  });
});

describe("clarify", () => {
  const prompt = {
    type: "clarify",
    round: 1,
    questions: [
      { field: "deployment_target", question: "어디까지 배포하나요?" },
      { field: "expected_users", question: "몇 명이 쓰나요?" },
      { field: "data_traits", question: "데이터 특징은요?" },
    ],
  };

  it("converts answers to their types and leaves out blanks", async () => {
    const { user, mock } = await startWith(journey({ prompt, revision: 3 }));

    await user.selectOptions(
      await screen.findByLabelText("어디까지 배포하나요?"),
      "local_demo",
    );
    await user.type(screen.getByLabelText("몇 명이 쓰나요?"), "20");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(bodyOf(mock.mock.calls[1])).toEqual({
      revision: 3,
      action: {
        action: "clarify",
        answers: { deployment_target: "local_demo", expected_users: 20 },
      },
    });
  });

  it("sends a GPU answer as a boolean, including no", async () => {
    const { user, mock } = await startWith(
      journey({
        prompt: {
          ...prompt,
          questions: [{ field: "has_gpu", question: "GPU가 있나요?" }],
        },
      }),
    );

    await user.selectOptions(
      await screen.findByLabelText("GPU가 있나요?"),
      "false",
    );
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(bodyOf(mock.mock.calls[1]).action.answers).toEqual({
      has_gpu: false,
    });
  });

  it("splits traits and allows skipping everything", async () => {
    const { user, mock } = await startWith(journey({ prompt }));

    await user.type(
      await screen.findByLabelText("데이터 특징은요?"),
      "문서 검색, 개인정보,",
    );
    await user.click(screen.getByRole("button", { name: "다음" }));
    expect(bodyOf(mock.mock.calls[1]).action.answers).toEqual({
      data_traits: ["문서 검색", "개인정보"],
    });
  });
});

describe("issues and completion", () => {
  it("offers to reopen only cards the user decided", async () => {
    const view = journey({
      status: "needs_fix",
      cards: [
        ...cards("decided", "decided"),
        {
          ...cards()[0],
          card_id: "mlops.x",
          state: "implied",
          question: "자동 질문",
        },
      ],
      prompt: {
        type: "issues",
        issues: [
          {
            rule_id: "r",
            severity: "error",
            message: "함께 쓸 수 없어요",
            card_ids: ["agent.hitl", "mlops.x"],
          },
          {
            rule_id: "w",
            severity: "warning",
            message: "경고만",
            card_ids: ["cloud.target"],
          },
        ],
        error: null,
      },
    });
    const { user, mock } = await startWith(view);

    const reopen = await screen.findByRole("button", {
      name: "다시 고르기: agent.hitl 질문",
    });
    expect(
      screen.queryByRole("button", { name: /자동 질문/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("경고만")).not.toBeInTheDocument();

    await user.click(reopen);
    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "reopen",
      card_id: "agent.hitl",
    });
  });

  it("lists decisions and warnings, then starts over", async () => {
    const items = stubStorage();
    const { user } = await startWith(
      journey({
        status: "completed",
        prompt: null,
        cards: cards("decided", "decided"),
        warnings: ["GPU를 확인하세요."],
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "모든 결정을 마쳤어요" }),
    ).toBeVisible();
    expect(screen.getByText("GPU를 확인하세요.")).toBeVisible();
    expect(items.get(LAST_KEY)).toBe(ID);
    expect(
      screen.getByRole("link", { name: "결정 요약 다운로드" }),
    ).toHaveAttribute("href", `/api/v1/journeys/${ID}/summary.md`);

    await user.click(screen.getByRole("button", { name: "새 프로젝트 시작" }));

    expect(screen.getByLabelText("프로젝트 아이디어")).toBeVisible();
    expect(items.has(LAST_KEY)).toBe(false);
    expect(window.location.search).toBe("");
  });

  it("shows the design and offers the build package", async () => {
    await startWith(
      journey({
        status: "completed",
        prompt: null,
        cards: cards("decided", "decided"),
        design: {
          status: "failed",
          source: "template",
          error: "맞춤 설계를 만들지 못했어요.",
          nodes: [
            { id: "worker", kind: "agent", responsibility: "초안을 쓴다" },
          ],
          first_task: "뼈대 연결하기",
          first_task_check: "결과가 돌아온다",
          unknowns: ["아직 정하지 않은 결정: Agent 구조"],
          warnings: [],
          files: ["BUILD.md", "CLAUDE.md"],
        },
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "설계가 준비됐어요" }),
    ).toBeVisible();
    expect(screen.getByText("맞춤 설계를 만들지 못했어요.")).toBeVisible();
    expect(screen.getByText("초안을 쓴다")).toBeVisible();
    expect(screen.getByText("뼈대 연결하기")).toBeVisible();
    expect(screen.getByText("아직 정하지 않은 결정: Agent 구조")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "빌드 묶음 다운로드 (파일 2개)" }),
    ).toHaveAttribute("href", `/api/v1/journeys/${ID}/package.zip`);
  });

  it("tells apart two cards of the same layer in the progress rail", async () => {
    const twoInLayer = [
      { ...cards()[0], card_id: "agent.a", title: "Agent 구조" },
      {
        ...cards()[1],
        card_id: "agent.b",
        layer: "agent",
        stage: 4,
        title: "사람 확인",
      },
    ];
    const { user } = await startWith(journey({ cards: twoInLayer }));

    await openStage(user, /^에이전트 설계 \d/);
    const rail = await screen.findByRole("complementary");
    expect(rail).toHaveTextContent("Agent 구조");
    expect(rail).toHaveTextContent("사람 확인");
  });

  it("reopens a decided card from the progress rail", async () => {
    const { user, mock } = await startWith(
      journey({ cards: cards("decided", "current") }),
    );

    await openStage(user, /^에이전트 설계 \d/);
    await user.click(
      await screen.findByRole("button", {
        name: "agent.hitl 제목 다시 고르기",
      }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "revise",
      card_id: "agent.hitl",
    });
  });

  it("reopens a decided card by clicking anywhere on its row", async () => {
    const { user, mock } = await startWith(
      journey({ cards: cards("decided", "pending") }),
    );

    await openStage(user, /^에이전트 설계 \d/);
    await user.click(await screen.findByText("agent.hitl 제목"));

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "revise",
      card_id: "agent.hitl",
    });
  });

  it("moves to a card that is still open", async () => {
    const { user, mock } = await startWith(
      journey({ cards: cards("current", "pending") }),
    );

    await openStage(user, /^시스템 구성 \d/);
    await user.click(
      await screen.findByRole("button", {
        name: "cloud.target 제목 먼저 정하기",
      }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "focus",
      card_id: "cloud.target",
    });
  });

  it("asks to review a later decision and can keep it", async () => {
    const flagged = cards("decided", "current");
    flagged[0] = { ...flagged[0], needs_review: true };
    const { user, mock } = await startWith(journey({ cards: flagged }));

    await openStage(user, /^에이전트 설계 \d.*다시 확인 1/);
    expect(await screen.findByText(/앞 단계가 바뀌었어요/)).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "agent.hitl 제목 현재 결정 유지" }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "keep",
      card_id: "agent.hitl",
    });
  });

  it("shows the held option and offers to cancel while changing", async () => {
    const { user, mock } = await startWith(
      journey({
        cards: [{ ...cards("decided", "pending")[0], editing: true }],
        prompt: decisionPrompt({ current_option_id: "none" }),
      }),
    );

    expect(await screen.findByText(/지금 결정은 그대로예요/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "없음 그대로 두기" }));

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({ action: "defer" });
  });

  it("says what a change would affect before it is made", async () => {
    await startWith(
      journey({
        cards: [{ ...cards("decided", "pending")[0], editing: true }],
        prompt: decisionPrompt(
          { current_option_id: "none" },
          {
            to_review: ["Agent 구조: 단일", "실행 추적: 로그"],
            options: [
              optionView("none", "없음"),
              optionView("question", "질문", {
                must_change: ["상태 저장: 메모리"],
              }),
            ],
          },
        ),
      }),
    );

    expect(
      await screen.findByText("바꾸면 뒤 단계 결정 2개를 다시 확인하게 돼요"),
    ).toBeVisible();
    expect(
      screen.getByText("Agent 구조: 단일 · 실행 추적: 로그"),
    ).toBeVisible();
    expect(screen.getByText("바꿔야 할 가능성이 높아요")).toBeVisible();
    expect(screen.getByText("상태 저장: 메모리")).toBeVisible();
  });

  it("groups cards under the stages of the project", async () => {
    const { user } = await startWith(journey());

    await openStage(user, /^시스템 구성 \d/);
    const rail = await screen.findByRole("complementary");
    expect(rail).toHaveTextContent("에이전트 설계");
    expect(rail).toHaveTextContent(/팀 실행 단계는 아직 열리지 않았어요/);
    expect(
      within(rail).queryByRole("button", { name: /^팀 실행/ }),
    ).not.toBeInTheDocument();
  });

  it("puts the card first in the DOM when the panels stack", async () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    await startWith(journey());

    const graph = await screen.findByRole("region", { name: "설계 그래프" });
    const card = document.querySelector(".workspace-card")!;
    expect(
      card.compareDocumentPosition(graph) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("reopens a decision after the journey finished", async () => {
    const { user, mock } = await startWith(
      journey({
        status: "completed",
        prompt: null,
        cards: cards("decided", "decided"),
        can_reopen: true,
      }),
    );

    expect(await screen.findByText(/다시 만들어요/)).toBeVisible();
    await openStage(user, /^에이전트 설계 \d/);
    await user.click(
      screen.getByRole("button", { name: "agent.hitl 제목 다시 고르기" }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "revise",
      card_id: "agent.hitl",
    });
  });

  it("does not offer a reopen on a journey that cannot change", async () => {
    await startWith(
      journey({
        status: "completed",
        prompt: null,
        cards: cards("decided", "decided"),
      }),
    );

    await screen.findByRole("heading", { name: "모든 결정을 마쳤어요" });
    expect(screen.queryByRole("button", { name: /다시 고르기/ })).toBeNull();
  });

  it("shows a skipped card as not applying and puts it back", async () => {
    const [current, skipped] = cards("current", "skipped");
    const { user, mock } = await startWith(
      journey({ cards: [current, { ...skipped, skip_confidence: 0.92 }] }),
    );

    await openStage(user, /^시스템 구성 \d/);
    const rail = await screen.findByRole("complementary", {
      name: "결정 진행 상황",
    });
    expect(rail).toHaveTextContent("해당 없음 · 확신도 92%");
    expect(rail).toHaveTextContent("0 / 1");
    await user.click(
      screen.getByRole("button", { name: "cloud.target 제목 다시 넣기" }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "reopen",
      card_id: "cloud.target",
    });
  });

  it("puts a skipped card back after the journey finished", async () => {
    const { user, mock } = await startWith(
      journey({
        status: "completed",
        prompt: null,
        cards: cards("decided", "skipped"),
        can_reopen: true,
      }),
    );

    await screen.findByRole("heading", { name: "모든 결정을 마쳤어요" });
    await openStage(user, /^시스템 구성 \d/);
    await user.click(
      screen.getByRole("button", { name: "cloud.target 제목 다시 넣기" }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "reopen",
      card_id: "cloud.target",
    });
  });
});

describe("screen changes and the main action", () => {
  it("keeps typing in the box once the start conversation opens", async () => {
    await startWith(
      journey({
        prompt: {
          type: "gcb",
          draft: { goal: "", context: "", boundary: "" },
          source: "llm",
          error: null,
        },
        start: {
          mode: "model",
          fields: [],
          chat: [{ role: "user", text: "아이디어", changes: [], rejected: [] }],
          revision: 0,
          missing: [],
          submit: {},
        },
      }),
    );
    expect(await screen.findByLabelText("더 알려 주기")).toHaveFocus();
  });

  it("moves focus when the journey completes", async () => {
    await startWith(
      journey({
        status: "completed",
        prompt: null,
        cards: cards("decided", "decided"),
      }),
    );
    const heading = await screen.findByRole("heading", {
      name: "모든 결정을 마쳤어요",
    });
    expect(heading).toHaveFocus();
  });

  it("makes the recommended option the one primary action", async () => {
    await startWith(journey());
    const accept = await screen.findByRole("button", { name: "없음 선택" });

    expect(accept).toHaveClass("primary");
    expect(accept).toHaveTextContent("이걸로 정하기");
    expect(screen.getByRole("button", { name: "승인 선택" })).not.toHaveClass(
      "primary",
    );
  });

  it("does not show the internal problem codes", async () => {
    await startWith(journey());

    await screen.findByRole("button", { name: "없음 선택" });
    expect(screen.queryByText(/DiV/)).not.toBeInTheDocument();
  });
});

describe("module conversation", () => {
  const plan = (goal: string | null = null) => [
    {
      id: "agent",
      name: "에이전트 흐름",
      stack: [],
      cards: [],
      column: 0,
      after: [],
      goal: goal ? { text: goal, how: null, source: "chat" } : null,
      include: [],
      exclude: [],
      gates: [{ text: "평가 사례", how: null, source: "rule", why: "이유" }],
      criteria: [
        {
          text: "답변 응답 시간",
          how: "시간을 잰다",
          source: "open",
          kind: "quantitative",
          needs_target: true,
          target: null,
        },
      ],
      tasks: [],
    },
  ];
  const finished = (overrides = {}) =>
    journey({
      status: "completed",
      prompt: null,
      cards: cards("decided", "decided"),
      can_reopen: true,
      modules: plan(),
      module_mode: "model",
      module_revision: 3,
      ...overrides,
    });

  async function open(view: unknown, reply: Handler) {
    const user = userEvent.setup();
    const mock = stubFetch((url, init) =>
      url.includes("/modules/")
        ? reply(url, init)
        : Response.json(view, { status: 201 }),
    );
    render(<App />);
    await user.type(
      screen.getByLabelText("프로젝트 아이디어"),
      "강의 자료를 찾아 답하는 서비스",
    );
    await user.click(screen.getByRole("button", { name: "보내기" }));
    await screen.findByRole("heading", { name: "모든 결정을 마쳤어요" });
    return { user, mock };
  }

  it("opens the chat with the build order and fills the plan from a reply", async () => {
    const answered = finished({
      modules: plan("강의 자료로 답한다"),
      module_revision: 4,
      module_undo_count: 1,
      module_chat: [
        { role: "user", text: "강의 자료로 답해요", changes: [], rejected: [] },
        {
          role: "assistant",
          text: "목표를 채웠어요.",
          changes: ["에이전트 흐름 · 목표"],
          rejected: [],
        },
      ],
    });
    const { user, mock } = await open(finished(), () =>
      Response.json(answered),
    );

    expect(
      screen.getByRole("complementary", { name: "결과 요약" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "만드는 순서" }));
    const side = screen.getByRole("complementary", { name: "모듈 대화" });
    await user.type(
      within(side).getByLabelText("모듈에 대해 말하기"),
      "강의 자료로 답해요{Enter}",
    );

    const sent = mock.mock.calls.find(([url]) => url.includes("/modules/"))!;
    expect(sent[0]).toContain("/modules/messages");
    expect(bodyOf(sent)).toEqual({ revision: 3, text: "강의 자료로 답해요" });
    expect(await within(side).findByText("목표를 채웠어요.")).toBeVisible();
    expect(within(side).getByText("에이전트 흐름 · 목표")).toBeVisible();

    await user.click(within(side).getByRole("button", { name: /되돌리기/ }));
    expect(mock.mock.calls.at(-1)![0]).toContain("/modules/undo");

    await user.click(within(side).getByRole("button", { name: "결과 요약" }));
    expect(
      screen.getByRole("complementary", { name: "결과 요약" }),
    ).toBeVisible();
  });

  it("puts the sentence back when no reply could be made", async () => {
    const { user } = await open(finished(), () =>
      errorResponse(503, "module_reply_failed", "답을 만들지 못했어요."),
    );

    await user.click(screen.getByRole("button", { name: "만드는 순서" }));
    const box = screen.getByLabelText("모듈에 대해 말하기");
    await user.type(box, "목표는 이거예요{Enter}");

    expect(await screen.findByText("답을 만들지 못했어요.")).toBeVisible();
    expect(box).toHaveValue("목표는 이거예요");
  });

  it("fills a target with a form when there is no model", async () => {
    const { user, mock } = await open(finished({ module_mode: "form" }), () =>
      errorResponse(422, "module_edit_rejected", "정할 값으로 남겨 뒀어요."),
    );

    await user.click(screen.getByRole("button", { name: "만드는 순서" }));
    expect(screen.queryByLabelText("모듈에 대해 말하기")).toBeNull();
    expect(screen.getByText(/대화 대신 직접 채워요/)).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "1단계 에이전트 흐름, 정할 값 1개" }),
    );
    await user.click(
      screen.getByRole("button", { name: "답변 응답 시간 목표치 고치기" }),
    );
    await user.type(screen.getByLabelText("답변 응답 시간 목표치"), "빨리");
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(bodyOf(mock.mock.calls.at(-1)!)).toEqual({
      revision: 3,
      change: {
        module: "agent",
        field: "target",
        criterion: "답변 응답 시간",
        value: "빨리",
      },
    });
    expect(await screen.findByText("정할 값으로 남겨 뒀어요.")).toBeVisible();
    expect(screen.getByLabelText("답변 응답 시간 목표치")).toHaveValue("빨리");
  });
});

describe("project list", () => {
  const PROJECTS_KEY = "starter-pack:projects:v1";
  const OTHER = "7b1f3c2a-1111-4222-8333-944455556666";
  const saved = (extra = {}) => ({
    id: ID,
    idea: "강의 자료를 찾아 답하는 서비스",
    name: null,
    state: "deciding",
    where: "에이전트 설계 단계",
    usedAt: Date.now(),
    ...extra,
  });

  it("lists an opened project with where it stopped", async () => {
    const items = stubStorage();
    const { user } = await startWith(journey());
    await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" });

    const list = JSON.parse(items.get(PROJECTS_KEY)!);
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({
      id: ID,
      state: "deciding",
      where: "에이전트 설계 단계",
    });

    await user.click(screen.getByRole("button", { name: "내 프로젝트" }));
    expect(screen.getByRole("heading", { name: "내 프로젝트" })).toBeVisible();
    const link = screen.getByRole("link", {
      name: /강의 자료를 찾아 답하는 서비스/,
    });
    expect(link).toHaveAttribute("href", `?journey=${ID}`);
    expect(screen.getByText("결정 중 · 에이전트 설계 단계")).toBeVisible();
  });

  it("opens a recent project from the start screen", async () => {
    stubStorage({ [PROJECTS_KEY]: JSON.stringify([saved()]) });
    const mock = stubFetch(() => Response.json(journey()));
    const user = userEvent.setup();
    render(<App />);

    const recent = screen.getByRole("region", { name: "이어서 하기" });
    await user.click(within(recent).getByRole("link", { name: /강의 자료/ }));

    expect(mock.mock.calls[0][0]).toContain(`/journeys/${ID}`);
    expect(
      await screen.findByRole("heading", { name: "사람 확인이 필요한가요?" }),
    ).toBeVisible();
  });

  it("drops a project the server no longer has", async () => {
    const items = stubStorage({ [PROJECTS_KEY]: JSON.stringify([saved()]) });
    stubFetch(() => errorResponse(404, "journey_not_found", "없어요"));
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("link", { name: /강의 자료/ }));
    expect(
      await screen.findByText("이 프로젝트를 찾지 못해 목록에서 뺐어요."),
    ).toBeVisible();
    expect(JSON.parse(items.get(PROJECTS_KEY)!)).toEqual([]);
  });

  it("renames, filters and removes projects on the list page", async () => {
    stubStorage({
      [PROJECTS_KEY]: JSON.stringify([
        saved(),
        saved({
          id: OTHER,
          idea: "회의록 요약 서비스",
          state: "done",
          where: "",
        }),
      ]),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "모두 보기 · 2개" }));

    await user.click(screen.getByRole("button", { name: "완료 1" }));
    expect(screen.queryByRole("link", { name: /강의 자료/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "전체 2" }));

    await user.click(
      screen.getByRole("button", { name: "회의록 요약 서비스 더 보기" }),
    );
    await user.click(screen.getByRole("button", { name: "이름 바꾸기" }));
    const name = screen.getByLabelText("새 이름");
    await user.clear(name);
    await user.type(name, "회의록 정리{Enter}");
    expect(screen.getByRole("link", { name: "회의록 정리" })).toBeVisible();

    const more = screen.getByRole("button", { name: "회의록 정리 더 보기" });
    await user.click(more);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "이름 바꾸기" })).toBeNull();
    expect(more).toHaveFocus();

    await user.click(more);
    await user.click(screen.getByRole("button", { name: "목록에서 지우기" }));
    await user.click(screen.getByRole("button", { name: "지우기" }));
    expect(screen.queryByRole("link", { name: "회의록 정리" })).toBeNull();
    expect(screen.getByRole("link", { name: /강의 자료/ })).toBeVisible();
  });

  it("switches to another project from the top bar", async () => {
    stubStorage({
      [PROJECTS_KEY]: JSON.stringify([
        saved({
          id: OTHER,
          idea: "회의록 요약 서비스",
          state: "done",
          where: "",
        }),
      ]),
    });
    const other = journey({ journey_id: OTHER, idea: "회의록 요약 서비스" });
    const mock = stubFetch((url) =>
      url.includes(OTHER)
        ? Response.json(other)
        : Response.json(journey(), { status: 201 }),
    );
    const user = userEvent.setup();
    render(<App />);
    await user.type(
      screen.getByLabelText("프로젝트 아이디어"),
      "강의 자료를 찾아 답하는 서비스",
    );
    await user.click(screen.getByRole("button", { name: "보내기" }));

    const toggle = await screen.findByRole("button", {
      name: /프로젝트 바꾸기, 지금: 강의 자료/,
    });
    await user.click(toggle);
    await user.keyboard("{Escape}");
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    await user.click(screen.getByRole("link", { name: /회의록 요약 서비스/ }));
    expect(mock.mock.calls.at(-1)![0]).toContain(`/journeys/${OTHER}`);
    expect(
      await screen.findByRole("button", {
        name: /프로젝트 바꾸기, 지금: 회의록 요약 서비스/,
      }),
    ).toBeVisible();
  });
});

// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
  await user.click(screen.getByRole("button", { name: "결정 시작하기" }));
  return { user, mock };
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
    const submit = screen.getByRole("button", { name: "결정 시작하기" });
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
    await user.click(screen.getByRole("button", { name: "결정 시작하기" }));

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
    await user.click(screen.getByRole("button", { name: "결정 시작하기" }));

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
    await user.click(screen.getByRole("button", { name: "결정 시작하기" }));

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

describe("decision card", () => {
  it("is honest that the recommendation is a mock default", async () => {
    await startWith(journey());

    expect(await screen.findByText("추천: 없음")).toBeVisible();
    expect(
      screen.getByText(/내 프로젝트를 분석한 결과는 아니에요/),
    ).toBeVisible();
    expect(screen.queryByText(/확신도/)).not.toBeInTheDocument();
    expect(screen.queryByText(/AI가 내 프로젝트/)).not.toBeInTheDocument();
    expect(screen.getByText(/연결된 강의 자료 없음/)).toBeVisible();
    expect(screen.getByText("모델 미연결 상태입니다.")).toBeVisible();
  });

  it("sends the current revision with a selection", async () => {
    const { user, mock } = await startWith(journey());

    await user.click(await screen.findByRole("button", { name: "없음 선택" }));

    expect(bodyOf(mock.mock.calls[1])).toEqual({
      revision: 7,
      action: { action: "select", option_id: "none" },
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

    await user.click(screen.getByRole("button", { name: "추천대로 진행" }));
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

describe("gcb", () => {
  const prompt = {
    type: "gcb",
    draft: { goal: "", context: "", boundary: "" },
    source: "none",
    error: null,
  };

  it("sends what the user wrote, trimmed", async () => {
    const { user, mock } = await startWith(journey({ prompt, revision: 2 }));

    await user.type(await screen.findByLabelText(/^Goal:/), "  달성된 상태  ");
    await user.type(screen.getByLabelText(/^Boundary:/), "출처 표시");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(bodyOf(mock.mock.calls[1])).toEqual({
      revision: 2,
      action: {
        action: "gcb",
        goal: "달성된 상태",
        context: "",
        boundary: "출처 표시",
      },
    });
  });

  it("prefills an AI draft, says so, and sends the user's edits", async () => {
    const { user, mock } = await startWith(
      journey({
        prompt: {
          ...prompt,
          source: "llm",
          draft: { goal: "초안 목표", context: "초안 상황", boundary: "" },
        },
      }),
    );

    expect(
      await screen.findByText(/AI가 아이디어를 읽고 쓴 초안/),
    ).toBeVisible();
    const goal = screen.getByLabelText(/^Goal:/);
    expect(goal).toHaveValue("초안 목표");

    await user.clear(goal);
    await user.type(goal, "고친 목표");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(bodyOf(mock.mock.calls[1]).action.goal).toBe("고친 목표");
    expect(bodyOf(mock.mock.calls[1]).action.context).toBe("초안 상황");
  });

  it("explains an unavailable draft and shows the error", async () => {
    await startWith(
      journey({
        prompt: { ...prompt, source: "unavailable", error: "확인해 주세요" },
      }),
    );

    expect(await screen.findByText(/AI 초안을 만들지 못했어요/)).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("확인해 주세요");
  });

  it("guides toward a state, not a command or a method", async () => {
    await startWith(journey({ prompt }));

    expect(await screen.findByText(/달성된 상태로 적어요/)).toBeVisible();
    expect(screen.getByText(/처리 순서나 방법은 적지 않아요/)).toBeVisible();
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
          nodes: [{ id: "worker", kind: "agent", responsibility: "초안을 쓴다" }],
          first_task: "뼈대 연결하기",
          first_task_check: "결과가 돌아온다",
          unknowns: ["아직 정하지 않은 결정: Agent 구조"],
          warnings: [],
          files: ["BUILD.md", "CLAUDE.md"],
        },
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "빌드 묶음을 만들었어요" }),
    ).toBeVisible();
    expect(screen.getByText("맞춤 설계를 만들지 못했어요.")).toBeVisible();
    expect(screen.getByText("초안을 쓴다")).toBeVisible();
    expect(screen.getByText("뼈대 연결하기")).toBeVisible();
    expect(screen.getByText("아직 정하지 않은 결정: Agent 구조")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "빌드 묶음 다운로드" }),
    ).toHaveAttribute("href", `/api/v1/journeys/${ID}/package.zip`);
  });

  it("tells apart two cards of the same layer in the progress rail", async () => {
    const twoInLayer = [
      { ...cards()[0], card_id: "agent.a", title: "Agent 구조" },
      { ...cards()[1], card_id: "agent.b", layer: "agent", title: "사람 확인" },
    ];
    await startWith(journey({ cards: twoInLayer }));

    const rail = await screen.findByRole("complementary");
    expect(rail).toHaveTextContent("Agent 구조");
    expect(rail).toHaveTextContent("사람 확인");
  });

  it("reopens a decided card from the progress rail", async () => {
    const { user, mock } = await startWith(
      journey({ cards: cards("decided", "current") }),
    );

    await user.click(
      await screen.findByRole("button", {
        name: "agent.hitl 제목 다시 고르기",
      }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "reopen",
      card_id: "agent.hitl",
    });
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
    await user.click(
      screen.getByRole("button", { name: "agent.hitl 제목 다시 고르기" }),
    );

    expect(bodyOf(mock.mock.calls[1]).action).toEqual({
      action: "reopen",
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
});

describe("screen changes and the main action", () => {
  it("moves focus to the heading of a new screen", async () => {
    await startWith(
      journey({
        prompt: {
          type: "gcb",
          draft: { goal: "", context: "", boundary: "" },
          source: "none",
          error: null,
        },
      }),
    );
    const heading = await screen.findByRole("heading", {
      name: "프로젝트의 목표와 기준을 정리해요",
    });
    expect(heading).toHaveFocus();
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

  it("makes accepting the recommendation the one primary action", async () => {
    await startWith(journey());
    const accept = await screen.findByRole("button", { name: "추천대로 진행" });

    expect(accept).toHaveClass("primary");
    expect(screen.getByRole("button", { name: "없음 선택" })).not.toHaveClass(
      "primary",
    );
  });

  it("does not show the internal problem codes", async () => {
    await startWith(journey());

    await screen.findByRole("button", { name: "추천대로 진행" });
    expect(screen.queryByText(/DiV/)).not.toBeInTheDocument();
  });
});

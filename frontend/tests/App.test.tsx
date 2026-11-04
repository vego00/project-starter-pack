// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import { DRAFT_KEY } from "../src/document";

const result = {
  request_id: "e29a4ac6-f90c-4f97-91d6-d99acf27351f",
  provider: "mock",
  is_mock: true,
  notice: "모델 미연결 · 고정 템플릿 예시이며 실제 분석 결과가 아닙니다.",
  starter_pack: {
    pain_point: "<img src=x onerror=alert(1)> 입력한 문제",
    goal: "예시 프로젝트 목표",
    assumptions: ["확인이 필요한 가정"],
    agent_recommended: null,
    agent_blueprint: {
      architecture: "undetermined",
      roles: ["요구사항 정리 (예시)"],
      workflow: ["문제 확인", "검증"],
      tools: [],
    },
    next_steps: ["성공 기준을 정하세요."],
  },
};

function mockApi(
  generate: () => Promise<Response> = async () => Response.json(result),
) {
  return vi.fn((url: string) =>
    url === "/health"
      ? Promise.resolve(Response.json({ status: "ok" }))
      : generate(),
  );
}

beforeEach(() => {
  // Node 26 exposes its own storage global; isolate browser storage in component tests.
  const items = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => {
      items.set(key, value);
    },
    removeItem: (key: string) => {
      items.delete(key);
    },
    clear: () => items.clear(),
  });
  vi.stubGlobal("fetch", mockApi());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("studio workflow", () => {
  it("requires a meaningful input and renders API results safely", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const submit = screen.getByRole("button", { name: /예시 스타터팩 만들기/ });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /회의 후속 작업/ }));
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(await screen.findByText("예시 프로젝트 목표")).toBeInTheDocument();
    expect(screen.getByText(result.notice)).toBeInTheDocument();
    expect(
      screen.getByText(result.starter_pack.pain_point),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/starter-packs/generate",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("prevents duplicate submissions while waiting", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = mockApi(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    fireEvent.change(screen.getByLabelText(/해결하고 싶은 문제/), {
      target: { value: "반복적인 팀 회의 작업을 줄이고 싶어요." },
    });
    const form = screen
      .getByRole("button", { name: /예시 스타터팩 만들기/ })
      .closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(
      screen.getByRole("button", { name: /예시 결과를 불러오는 중/ }),
    ).toBeDisabled();
    expect(
      fetcher.mock.calls.filter(([url]) => url !== "/health"),
    ).toHaveLength(1);
    resolve(Response.json(result));
    expect(await screen.findByText("예시 프로젝트 목표")).toBeInTheDocument();
  });

  it("preserves input on failure and supports retry", async () => {
    let failed = true;
    vi.stubGlobal(
      "fetch",
      mockApi(async () =>
        failed ? new Response("", { status: 503 }) : Response.json(result),
      ),
    );
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /학습 자료 정리/ }));
    const input = screen.getByLabelText(
      /해결하고 싶은 문제/,
    ) as HTMLTextAreaElement;
    const before = input.value;
    await user.click(
      screen.getByRole("button", { name: /예시 스타터팩 만들기/ }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "서버에 연결할 수 없어요",
    );
    expect(input.value).toBe(before);
    failed = false;
    await user.click(
      screen.getByRole("button", { name: /예시 스타터팩 만들기/ }),
    );
    expect(await screen.findByText("예시 프로젝트 목표")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("rejects a malformed API response", async () => {
    vi.stubGlobal(
      "fetch",
      mockApi(async () => Response.json({ message: "not a starter pack" })),
    );
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /반복 업무 줄이기/ }));
    fireEvent.click(
      screen.getByRole("button", { name: /예시 스타터팩 만들기/ }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "결과 형식을 확인하지 못했어요",
    );
  });

  it("saves and restores a draft, and appends results without replacing it", async () => {
    localStorage.setItem(DRAFT_KEY, "# 내가 쓴 초안");
    render(<App />);
    expect(screen.getByLabelText(/Markdown 초안/)).toHaveValue(
      "# 내가 쓴 초안",
    );
    fireEvent.click(screen.getByRole("button", { name: /회의 후속 작업/ }));
    fireEvent.click(
      screen.getByRole("button", { name: /예시 스타터팩 만들기/ }),
    );
    await screen.findByText("예시 프로젝트 목표");
    fireEvent.click(
      screen.getByRole("button", { name: /결과를 내 초안에 추가/ }),
    );
    const merged = (
      screen.getByLabelText(/Markdown 초안/) as HTMLTextAreaElement
    ).value;
    expect(merged).toContain("# 내가 쓴 초안");
    expect(merged).toContain(result.notice);
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() =>
      expect(localStorage.getItem(DRAFT_KEY)).toContain(result.notice),
    );
    cleanup();
    render(<App />);
    expect(screen.getByLabelText(/Markdown 초안/)).toHaveValue(
      localStorage.getItem(DRAFT_KEY),
    );
  });

  it("keeps the draft when storage is unavailable", async () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "내 초안" }));
    fireEvent.change(screen.getByLabelText(/Markdown 초안/), {
      target: { value: "보존할 내용" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    expect(
      screen.getByText("저장하지 못했습니다. 초안을 다운로드해 주세요."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Markdown 초안/)).toHaveValue("보존할 내용");
  });
});

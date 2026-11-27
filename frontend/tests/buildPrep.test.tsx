// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Action, BuildItem, Journey } from "../src/api";
import { BuildPrepPanel } from "../src/buildPrep";

function item(overrides: Partial<BuildItem>): BuildItem {
  return {
    id: "model_ids",
    title: "역할별 모델 ID",
    question: "에이전트 노드마다 쓸 모델 ID를 무엇으로 할까요?",
    recommendation: "주 모델 gemini-4",
    options: [],
    status: "open",
    value: null,
    by: null,
    previous: null,
    reason: null,
    ...overrides,
  };
}

const ITEMS = [
  item({}),
  item({
    id: "data_scope",
    title: "데이터 사용 범위",
    question: "써도 되는 데이터 범위는?",
    recommendation: "가상 예시 데이터로 한다",
  }),
  item({
    id: "unknown-1a2b",
    title: "설계의 미확인 사항",
    question: "기획서 양식은?",
    recommendation: null,
  }),
];

function journey(items: BuildItem[] = ITEMS, prompt = "build"): Journey {
  const remaining = items.filter((i) => i.status !== "answered").length;
  return {
    prompt: prompt ? { type: prompt, error: null } : null,
    build: {
      remaining,
      items,
      human_tasks: ["모델 제공자의 API 키를 .env에 넣는다."],
    },
  } as unknown as Journey;
}

function setup(view: Journey, result = "") {
  const send = vi.fn(async (_action: Action) => result);
  const user = userEvent.setup();
  render(<BuildPrepPanel journey={view} send={send} />);
  return { send, user };
}

afterEach(cleanup);

describe("build preparation panel", () => {
  it("lists what is left with each recommendation and the hands-on work", () => {
    setup(journey());

    expect(screen.getByRole("status")).toHaveTextContent("남은 결정 3개");
    expect(screen.getByText("추천: 주 모델 gemini-4")).toBeVisible();
    expect(screen.getByText(/직접 누른 것만 결정으로 기록돼요/)).toBeVisible();
    expect(
      screen.getByText("모델 제공자의 API 키를 .env에 넣는다."),
    ).toBeVisible();
    // An item without a recommendation offers no "by recommendation" button.
    expect(
      screen.queryByRole("button", {
        name: "설계의 미확인 사항 추천대로 정하기",
      }),
    ).not.toBeInTheDocument();
  });

  it("records one item by its recommendation", async () => {
    const { send, user } = setup(journey());

    await user.click(
      screen.getByRole("button", { name: "역할별 모델 ID 추천대로 정하기" }),
    );

    expect(send).toHaveBeenCalledWith({
      action: "build_accept",
      key: "model_ids",
    });
  });

  it("takes every recommendation at once, counting only items that have one", async () => {
    const { send, user } = setup(journey());

    await user.click(
      screen.getByRole("button", {
        name: "추천 있는 항목 2개를 추천대로 정하기",
      }),
    );

    expect(send).toHaveBeenCalledWith({ action: "build_accept_all" });
  });

  it("writes an answer in a labelled field that gets the focus", async () => {
    const { send, user } = setup(journey());

    await user.click(
      screen.getByRole("button", { name: "설계의 미확인 사항 직접 쓰기" }),
    );
    const field = screen.getByLabelText("설계의 미확인 사항: 내 답");
    expect(field).toHaveFocus();
    await user.type(field, "문제, 해결, 기대 효과");
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(send).toHaveBeenCalledWith({
      action: "build_answer",
      key: "unknown-1a2b",
      value: "문제, 해결, 기대 효과",
    });
  });

  it("holds an item for the builder to ask", async () => {
    const { send, user } = setup(journey());

    await user.click(
      screen.getByRole("button", { name: "데이터 사용 범위 보류" }),
    );

    expect(send).toHaveBeenCalledWith({
      action: "build_hold",
      key: "data_scope",
    });
  });

  it("offers fixed choices next to writing one", async () => {
    const choices = item({ id: "n8n_trigger", title: "n8n 시작 방식",
      options: ["Webhook", "Schedule Trigger"] }); // prettier-ignore
    const { send, user } = setup(journey([choices]));

    await user.click(
      screen.getByRole("button", {
        name: "n8n 시작 방식: Schedule Trigger 고르기",
      }),
    );

    expect(send).toHaveBeenCalledWith({
      action: "build_answer",
      key: "n8n_trigger",
      value: "Schedule Trigger",
    });
    expect(
      screen.getByRole("button", { name: "n8n 시작 방식 직접 쓰기" }),
    ).toBeVisible();
  });

  it("shows why an answer needs another look and keeps it on request", async () => {
    const recheck = item({ status: "recheck", reason: "모델 제공자 결정이 바뀌었어요",
      previous: "주 모델 gpt-6" }); // prettier-ignore
    const { send, user } = setup(journey([recheck]));

    const row = screen.getAllByRole("listitem")[0];
    expect(within(row).getByText("다시 확인")).toBeVisible();
    expect(row).toHaveTextContent("모델 제공자 결정이 바뀌었어요");
    expect(row).toHaveTextContent("전에 정한 답: 주 모델 gpt-6");
    await user.click(
      screen.getByRole("button", { name: "역할별 모델 ID 그대로 두기" }),
    );

    expect(send).toHaveBeenCalledWith({
      action: "build_keep",
      key: "model_ids",
    });
  });

  it("says what failed under the item and keeps the written answer open", async () => {
    const { user } = setup(journey(), "서버에 연결할 수 없어요.");

    await user.click(
      screen.getByRole("button", { name: "설계의 미확인 사항 직접 쓰기" }),
    );
    await user.type(screen.getByLabelText("설계의 미확인 사항: 내 답"), "양식");
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "저장하지 못했어요. 서버에 연결할 수 없어요. 다시 눌러 주세요.",
    );
    expect(screen.getByLabelText("설계의 미확인 사항: 내 답")).toHaveValue(
      "양식",
    );
  });

  it("moves answered items under what was set, each with how it was set", () => {
    const set = item({
      status: "answered",
      value: "주 모델 gemini-4",
      by: "recommended",
    });
    setup(journey([set, ITEMS[1]]));

    expect(screen.getByRole("status")).toHaveTextContent("남은 결정 1개");
    expect(screen.getByText("정한 것 1개")).toBeVisible();
    expect(screen.getByText("추천대로")).toBeInTheDocument();
  });

  it("after finishing, offers to go back instead of answering in place", async () => {
    const { send, user } = setup(journey(ITEMS, ""));

    expect(
      screen.queryByRole("button", { name: "역할별 모델 ID 추천대로 정하기" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "남은 결정에 답하기" }),
    );

    expect(send).toHaveBeenCalledWith({ action: "build_prep" });
  });

  it("says so when there is nothing to ask", () => {
    setup(journey([]));

    expect(screen.getByRole("status")).toHaveTextContent(
      "빌더에게 물을 결정이 없어요.",
    );
  });
});

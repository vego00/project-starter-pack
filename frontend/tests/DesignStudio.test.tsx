// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DesignStudio from "../src/design/DesignStudio";

beforeAll(() => {
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
});
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

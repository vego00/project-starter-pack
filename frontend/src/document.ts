import type { GenerateResponse } from "./api";

export const DRAFT_KEY = "starter-pack:draft:v1";
export const MAX_DRAFT = 50000;

export function toMarkdown(result: GenerateResponse): string {
  const pack = result.starter_pack;
  return [
    "# 프로젝트 스타터팩",
    "",
    `> ${result.notice}`,
    "",
    "## 입력한 문제",
    pack.pain_point,
    "",
    "## 목표",
    pack.goal,
    "",
    "## 가정과 확인할 점",
    ...pack.assumptions.map((item) => `- ${item}`),
    "",
    "## 에이전트 구성",
    "에이전트 필요성: 미정 (모델 연결 후 검토)",
    ...pack.agent_blueprint.roles.map((item) => `- ${item}`),
    "",
    "## 작업 흐름",
    ...pack.agent_blueprint.workflow.map((item, i) => `${i + 1}. ${item}`),
    "",
    "## 다음 행동",
    ...pack.next_steps.map((item, i) => `${i + 1}. ${item}`),
    "",
  ].join("\n");
}

export function downloadMarkdown(content: string, filename: string) {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/markdown;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

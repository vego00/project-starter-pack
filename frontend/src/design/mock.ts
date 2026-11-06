import { designSchema } from "./types";
import type { Design } from "./types";

export type DesignCase = {
  id: string;
  title: string;
  idea: string;
  design: Design;
};

const NOTE = { name: "raw_note", type: "string" };
const SUMMARY = { name: "idea_summary", type: "string" };
const MODEL = { capability: "text-generation", provider_scope: "gemini" };

// Example designs for building this screen. None came from a model or a real user.
const RAW_CASES: {
  id: string;
  title: string;
  idea: string;
  design: unknown;
}[] = [
  {
    id: "straight",
    title: "메모 → 요약 → 기획서",
    idea: "메모를 넣으면 요약하고 기획서 초안을 만들어요.",
    design: {
      requirements: [
        {
          id: "req-1",
          problem: "메모의 핵심을 정리하지 못해요",
          success_example: "짧은 메모를 넣으면 핵심 키워드와 요약이 나와요",
          evidence: "적어 둔 아이디어의 핵심을 알아보고",
          core: true,
          node_ids: ["node-input", "node-summarizer"],
        },
        {
          id: "req-2",
          problem: "정리한 아이디어로 기획서를 만들지 못해요",
          success_example: "요약을 바탕으로 기획서 초안이 나와요",
          evidence: "다른 사람이 읽고 이해할 수 있는 기획서 초안",
          core: true,
          node_ids: ["node-writer"],
        },
      ],
      nodes: [
        {
          id: "node-input",
          kind: "code",
          responsibility: "입력한 메모를 받아 그대로 넘겨요",
          inputs: [NOTE],
          outputs: [NOTE],
          tools: [],
          done_when: "입력을 받았을 때",
          on_failure: "빈 문자열을 넘겨요",
        },
        {
          id: "node-summarizer",
          kind: "agent",
          responsibility: "메모의 핵심을 분석해 요약해요",
          inputs: [NOTE],
          outputs: [SUMMARY],
          tools: [],
          done_when: "핵심 요약이 나왔을 때",
          on_failure: "요약 실패 메시지를 돌려줘요",
          model: MODEL,
        },
        {
          id: "node-writer",
          kind: "agent",
          responsibility: "요약을 바탕으로 기획서 초안을 써요",
          inputs: [SUMMARY],
          outputs: [{ name: "draft_proposal", type: "string" }],
          tools: [],
          done_when: "구조를 갖춘 초안이 나왔을 때",
          on_failure: "기획서 작성 실패 메시지를 돌려줘요",
          model: MODEL,
        },
      ],
      workflow: {
        entry: "node-input",
        exits: ["node-writer"],
        edges: [
          { source: "node-input", target: "node-summarizer" },
          { source: "node-summarizer", target: "node-writer" },
        ],
        max_model_calls: 5,
      },
      unknowns: [],
      warnings: [],
    },
  },
  {
    id: "branching",
    title: "저장·찾기·고르기까지",
    idea: "메모를 쌓아 두고, 찾아서 하나 고른 뒤 기획서로 만들어요.",
    design: {
      requirements: [
        {
          id: "req-1",
          problem: "떠오른 아이디어를 남겨 둘 곳이 없어요",
          success_example: "메모를 넣으면 요약과 함께 저장돼요",
          evidence: "아이디어가 떠오를 때마다 자연어로 남기고 싶습니다",
          core: true,
          node_ids: ["summarizer", "save-idea"],
        },
        {
          id: "req-2",
          problem: "예전 아이디어를 다시 찾기 어려워요",
          success_example: "검색어를 넣으면 비슷한 아이디어가 나와요",
          evidence: "나중에 어떤 아이디어였는지 찾아서",
          core: true,
          node_ids: ["search-ideas", "pick-idea"],
        },
        {
          id: "req-3",
          problem: "고른 아이디어를 기획서로 발전시키기 어려워요",
          success_example: "고른 아이디어로 초안이 나오고 사람이 확인해요",
          evidence: "그중 하나를 골라",
          core: true,
          node_ids: ["writer", "review"],
        },
      ],
      nodes: [
        {
          id: "intake",
          kind: "code",
          responsibility: "입력을 받아요",
          inputs: [NOTE],
          outputs: [NOTE],
          tools: [],
          done_when: "입력을 받았을 때",
          on_failure: "다시 입력하라고 알려요",
        },
        {
          id: "router",
          kind: "code",
          responsibility: "사용자가 누른 버튼에 따라 저장과 찾기로 나눠요",
          inputs: [NOTE],
          outputs: [NOTE],
          tools: [],
          done_when: "다음 단계를 정했을 때",
          on_failure: "처음 화면으로 돌아가요",
        },
        {
          id: "summarizer",
          kind: "agent",
          responsibility: "메모의 핵심을 요약해요",
          inputs: [NOTE],
          outputs: [SUMMARY],
          tools: [],
          done_when: "요약이 나왔을 때",
          on_failure: "요약 없이 원문만 저장해요",
          model: MODEL,
        },
        {
          id: "save-idea",
          kind: "code",
          responsibility: "요약과 원문을 저장해요",
          inputs: [SUMMARY],
          outputs: [{ name: "idea_id", type: "string" }],
          tools: [
            {
              name: "idea_store",
              access: "write",
              reason: "아이디어를 남겨요",
            },
          ],
          done_when: "저장을 확인했을 때",
          on_failure: "저장하지 못했다고 알려요",
        },
        {
          id: "search-ideas",
          kind: "code",
          responsibility: "저장한 아이디어를 찾아요",
          inputs: [NOTE],
          outputs: [{ name: "candidates", type: "list" }],
          tools: [
            { name: "idea_store", access: "read", reason: "아이디어를 찾아요" },
          ],
          done_when: "후보 목록이 나왔을 때",
          on_failure: "찾지 못했다고 알려요",
        },
        {
          id: "pick-idea",
          kind: "human",
          responsibility: "사람이 후보 중 하나를 골라요",
          inputs: [{ name: "candidates", type: "list" }],
          outputs: [{ name: "picked_idea", type: "string" }],
          tools: [],
          done_when: "하나를 골랐을 때",
          on_failure: "고르지 않으면 멈춰요",
        },
        {
          id: "writer",
          kind: "agent",
          responsibility: "고른 아이디어로 기획서 초안을 써요",
          inputs: [{ name: "picked_idea", type: "string" }],
          outputs: [{ name: "draft", type: "string" }],
          tools: [],
          done_when: "초안이 나왔을 때",
          on_failure: "실패했다고 알려요",
          model: MODEL,
        },
        {
          id: "review",
          kind: "human",
          responsibility: "사람이 초안을 확인하고 고칠 점을 적어요",
          inputs: [{ name: "draft", type: "string" }],
          outputs: [{ name: "approved_draft", type: "string" }],
          tools: [],
          done_when: "승인했을 때",
          on_failure: "초안을 그대로 둬요",
        },
        {
          id: "finish",
          kind: "code",
          responsibility: "결과를 사용자에게 보여 줘요",
          inputs: [],
          outputs: [{ name: "result", type: "string" }],
          tools: [],
          done_when: "결과를 보여 줬을 때",
          on_failure: "오류를 알려요",
        },
      ],
      workflow: {
        entry: "intake",
        exits: ["finish"],
        edges: [
          { source: "intake", target: "router" },
          { source: "router", target: "summarizer", condition: "저장" },
          { source: "router", target: "search-ideas", condition: "찾기" },
          { source: "summarizer", target: "save-idea" },
          { source: "save-idea", target: "finish" },
          { source: "search-ideas", target: "pick-idea" },
          { source: "pick-idea", target: "writer" },
          { source: "writer", target: "review" },
          { source: "writer", target: "finish", on_failure: true },
          { source: "review", target: "finish", condition: "승인" },
          { source: "review", target: "writer", condition: "다시 쓰기" },
        ],
        loop_limits: [
          {
            node_ids: ["writer", "review"],
            max_iterations: 3,
            on_exceeded: "finish",
          },
        ],
        max_model_calls: 8,
      },
      unknowns: [
        {
          text: "메모를 어디에 저장할지 정해지지 않았어요",
          blocks_confirmation: true,
        },
        {
          text: "기획서 양식과 읽는 사람이 정해지지 않았어요",
          blocks_confirmation: false,
        },
      ],
      warnings: ["메모리 저장을 고르면 재시작할 때 아이디어가 사라져요"],
    },
  },
  {
    id: "broken",
    title: "문제가 있는 설계",
    idea: "검사 결과가 어떻게 보이는지 확인하는 예시예요.",
    design: {
      requirements: [
        {
          id: "req-1",
          problem: "메모를 정리하지 못해요",
          success_example: "메모를 넣으면 요약이 나와요",
          evidence: null,
          core: true,
          node_ids: ["summarizer"],
        },
        {
          id: "req-2",
          problem: "아이디어를 저장하지 못해요",
          success_example: "저장한 아이디어를 다시 볼 수 있어요",
          evidence: null,
          core: true,
          node_ids: [],
        },
      ],
      nodes: [
        {
          id: "intake",
          kind: "code",
          responsibility: "입력을 받아요",
          inputs: [NOTE],
          outputs: [NOTE],
          tools: [],
          done_when: "입력을 받았을 때",
          on_failure: "다시 입력하라고 알려요",
        },
        {
          id: "summarizer",
          kind: "agent",
          responsibility: "메모를 요약해요",
          inputs: [NOTE],
          outputs: [SUMMARY],
          tools: [],
          done_when: "요약이 나왔을 때",
          on_failure: "실패했다고 알려요",
          model: MODEL,
        },
        {
          id: "checker",
          kind: "agent",
          responsibility: "요약을 점검하고 다시 요약하게 해요",
          inputs: [SUMMARY],
          outputs: [NOTE],
          tools: [],
          done_when: "점검을 통과했을 때",
          on_failure: "실패했다고 알려요",
          model: MODEL,
        },
        {
          id: "writer",
          kind: "agent",
          responsibility: "기획서 초안을 써요",
          inputs: [{ name: "picked_idea", type: "string" }],
          outputs: [{ name: "draft", type: "string" }],
          tools: [],
          done_when: "초안이 나왔을 때",
          on_failure: "실패했다고 알려요",
          model: MODEL,
        },
        {
          id: "archive",
          kind: "code",
          responsibility: "결과를 보관해요",
          inputs: [{ name: "draft", type: "string" }],
          outputs: [],
          tools: [
            { name: "doc_store", access: "write", reason: "결과를 남겨요" },
          ],
          done_when: "보관했을 때",
          on_failure: "실패했다고 알려요",
        },
      ],
      workflow: {
        entry: "intake",
        exits: ["writer"],
        edges: [
          { source: "intake", target: "summarizer" },
          { source: "summarizer", target: "checker" },
          { source: "checker", target: "summarizer", condition: "다시" },
          { source: "checker", target: "writer", condition: "통과" },
        ],
      },
      unknowns: [
        { text: "저장 방법이 정해지지 않았어요", blocks_confirmation: true },
      ],
      warnings: [],
    },
  },
];

export const DESIGN_CASES: DesignCase[] = RAW_CASES.map((item) => ({
  ...item,
  design: designSchema.parse(item.design),
}));

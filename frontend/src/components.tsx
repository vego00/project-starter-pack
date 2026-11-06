import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { designViewUrl, packageUrl, summaryUrl } from "./api";
import type {
  Action,
  CardStatus,
  ClarifyPrompt,
  DecisionPrompt,
  GcbPrompt,
  IssuesPrompt,
  Journey,
} from "./api";

const LAYER_NAMES: Record<string, string> = {
  agent: "Agent 설계",
  model: "모델",
  data: "데이터·검색",
  backend: "백엔드·실행",
  devops: "DevOps",
  mlops: "MLOps",
  cloud: "Cloud",
};
const LEVELS = { low: "낮음", medium: "보통", high: "높음" };
const BY_LABEL = {
  user: "직접 선택",
  recommended: "추천대로",
  implied: "자동 확정",
};
const STATE_LABEL = {
  deferred: "나중에",
  current: "지금 결정",
  pending: "대기",
};

const EXAMPLES = [
  "부트캠프 강의 자료를 찾아 질문에 답하고 출처를 알려주는 멀티 에이전트 서비스를 만들고 싶어요.",
  "회의록에서 담당자별 할 일을 뽑아 팀 메신저로 보내기 전에 사람이 확인하는 에이전트를 만들고 싶어요.",
];

export const MIN_IDEA = 10;
export const MAX_IDEA = 3000;

type Act = (action: Action) => void;

// The button that was pressed is gone after a screen change, so keyboard users need a new place.
function useFocusedHeading(screenKey?: string | number) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [screenKey]);
  return heading;
}

export function StartForm({
  busy,
  onStart,
}: {
  busy: boolean;
  onStart: (idea: string) => void;
}) {
  const [idea, setIdea] = useState("");
  const length = Array.from(idea.trim()).length;
  const valid = length >= MIN_IDEA && length <= MAX_IDEA;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid && !busy) onStart(idea);
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>어떤 프로젝트를 만들고 싶나요?</h2>
      <p className="muted">
        Agent 설계부터 배포까지 필요한 결정을 하나씩 비교하며 직접 골라요.
      </p>
      <label htmlFor="idea">프로젝트 아이디어</label>
      <textarea
        id="idea"
        rows={5}
        value={idea}
        onChange={(event) => setIdea(event.target.value)}
        placeholder="누가 어떤 문제를 겪고, 무엇을 만들고 싶은지 적어 주세요."
      />
      <div className="row between">
        <span className="muted">
          {length.toLocaleString()} / {MAX_IDEA.toLocaleString()}자 (최소{" "}
          {MIN_IDEA}자)
        </span>
        <button className="primary" disabled={!valid || busy}>
          {busy ? "시작하는 중…" : "결정 시작하기"}
        </button>
      </div>
      <p className="muted privacy">
        개인정보나 회사 기밀은 적지 마세요. 입력한 내용은 저장되고, 모델이
        연결된 경우 외부 모델 API로 전송돼요.
      </p>
      <p className="muted examples-label">예시로 시작하기</p>
      <div className="examples">
        {EXAMPLES.map((example) => (
          <button type="button" key={example} onClick={() => setIdea(example)}>
            {example}
          </button>
        ))}
      </div>
    </form>
  );
}

const MAX_GCB = 1000;
const GCB_FIELDS = [
  {
    name: "goal",
    label: "Goal: 끝났을 때 어떤 상태면 되나요?",
    hint: "'만들어줘' 같은 명령이 아니라 달성된 상태로 적어요. 기술이나 방법은 적지 않아요.",
    placeholder: "예: 수강생이 강의 내용을 출처와 함께 바로 찾을 수 있는 상태",
  },
  {
    name: "context",
    label: "Context: 판단에 필요한 상황은 무엇인가요?",
    hint: "왜 필요한지, 누가 쓰는지, 배경과 제약을 적어요. 관련 없는 정보는 빼요.",
    placeholder:
      "예: 부트캠프 수강생이 복습할 때 쓴다. 자료가 여러 곳에 흩어져 있다.",
  },
  {
    name: "boundary",
    label: "Boundary: 결과가 꼭 지켜야 할 기준은 무엇인가요?",
    hint: "결과가 갖춰야 할 조건을 적어요. 처리 순서나 방법은 적지 않아요.",
    placeholder:
      "예: 답변마다 출처를 표시한다. 개인정보를 외부로 보내지 않는다.",
  },
] as const;

export function GcbForm({
  prompt,
  busy,
  act,
}: {
  prompt: GcbPrompt;
  busy: boolean;
  act: Act;
}) {
  const heading = useFocusedHeading();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    act({
      action: "gcb",
      goal: value("goal"),
      context: value("context"),
      boundary: value("boundary"),
    });
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2 ref={heading} tabIndex={-1}>
        프로젝트의 목표와 기준을 정리해요
      </h2>
      {prompt.source === "llm" && (
        <p className="muted">
          AI가 아이디어를 읽고 쓴 초안이에요. 틀릴 수 있으니 직접 확인하고 고쳐
          주세요.
        </p>
      )}
      {prompt.source === "unavailable" && (
        <p className="muted">AI 초안을 만들지 못했어요. 직접 적어 주세요.</p>
      )}
      <p className="muted">
        뒤에 나오는 추천과 설명이 이 내용을 기준으로 해요. 모르면 비워도 돼요.
      </p>
      {prompt.error && (
        <p className="alert" role="alert">
          {prompt.error}
        </p>
      )}
      {GCB_FIELDS.map((field) => (
        <div className="field" key={field.name}>
          <label htmlFor={`gcb-${field.name}`}>{field.label}</label>
          <p className="muted hint">{field.hint}</p>
          <textarea
            id={`gcb-${field.name}`}
            name={field.name}
            rows={3}
            maxLength={MAX_GCB}
            defaultValue={prompt.draft[field.name]}
            placeholder={field.placeholder}
          />
        </div>
      ))}
      <button className="primary" disabled={busy}>
        다음
      </button>
    </form>
  );
}

function ClarifyField({ field, id }: { field: string; id: string }) {
  if (field === "deployment_target")
    return (
      <select id={id} name={field} defaultValue="">
        <option value="">아직 모르겠어요</option>
        <option value="local_demo">로컬 데모</option>
        <option value="small_group">소수 사용자</option>
        <option value="public_service">공개 서비스</option>
      </select>
    );
  if (field === "has_gpu")
    return (
      <select id={id} name={field} defaultValue="">
        <option value="">아직 모르겠어요</option>
        <option value="true">있어요</option>
        <option value="false">없어요</option>
      </select>
    );
  const numeric = [
    "expected_users",
    "team_size",
    "duration_weeks",
    "weekly_hours",
  ].includes(field);
  return numeric ? (
    <input id={id} name={field} type="number" min={0} inputMode="numeric" />
  ) : (
    <input id={id} name={field} type="text" maxLength={200} />
  );
}

function toAnswer(field: string, raw: string): unknown {
  if (field === "data_traits")
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  if (field === "has_gpu") return raw === "true";
  if (field === "budget" || field === "deployment_target") return raw;
  return Number(raw);
}

export function ClarifyForm({
  prompt,
  busy,
  act,
}: {
  prompt: ClarifyPrompt;
  busy: boolean;
  act: Act;
}) {
  const heading = useFocusedHeading(prompt.round);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const answers: Record<string, unknown> = {};
    for (const { field } of prompt.questions) {
      const raw = String(form.get(field) ?? "").trim();
      if (raw) answers[field] = toAnswer(field, raw);
    }
    act({ action: "clarify", answers });
  }

  return (
    // Fields are uncontrolled, so a new round must start from an empty form.
    <form className="panel" key={prompt.round} onSubmit={submit}>
      <h2 ref={heading} tabIndex={-1}>
        프로젝트를 조금 더 알려 주세요
      </h2>
      <p className="muted">
        결정에 영향을 주는 내용만 물어봐요. 모르면 비워 두어도 돼요. (질문{" "}
        {prompt.round}/2회)
      </p>
      {prompt.questions.map(({ field, question }) => (
        <div className="field" key={field}>
          <label htmlFor={`clarify-${field}`}>{question}</label>
          <ClarifyField field={field} id={`clarify-${field}`} />
        </div>
      ))}
      <button className="primary" disabled={busy}>
        다음
      </button>
    </form>
  );
}

function OptionCard({
  view,
  recommended,
  busy,
  act,
}: {
  view: DecisionPrompt["card"]["options"][number];
  recommended: boolean;
  busy: boolean;
  act: Act;
}) {
  const { option } = view;
  const blocked = view.blocked_reason !== null;
  return (
    <article
      className={`option${blocked ? " blocked" : ""}${recommended ? " recommended" : ""}`}
    >
      <header>
        <h3>{option.name}</h3>
        {recommended && <span className="badge">추천</span>}
      </header>
      <p>{view.note || option.summary}</p>
      <h4>장점</h4>
      <ul>
        {option.pros.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <h4>단점</h4>
      <ul>
        {option.cons.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <dl>
        <dt>학습 난이도</dt>
        <dd>{LEVELS[option.learning_difficulty]}</dd>
        <dt>운영 부담</dt>
        <dd>{LEVELS[option.ops_burden]}</dd>
        <dt>비용</dt>
        <dd>{option.cost_nature}</dd>
      </dl>
      {view.implied_messages.length > 0 && (
        <div className="note">
          <strong>선택하면 같이 바뀌는 것</strong>
          {view.implied_messages.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      )}
      {!blocked && view.warnings.length > 0 && (
        <div className="note warn">
          <strong>확인 필요</strong>
          {view.warnings.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      )}
      {blocked && (
        <p className="note warn">
          <strong>지금은 고를 수 없어요.</strong> {view.blocked_reason}
        </p>
      )}
      <button
        className="choose"
        disabled={blocked || busy}
        onClick={() => act({ action: "select", option_id: option.id })}
      >
        {option.name} 선택
      </button>
    </article>
  );
}

export function DecisionView({
  prompt,
  busy,
  act,
}: {
  prompt: DecisionPrompt;
  busy: boolean;
  act: Act;
}) {
  const { card } = prompt;
  const [question, setQuestion] = useState("");
  const heading = useFocusedHeading(card.card_id);
  const recommendation = card.recommendation;
  const recommended = card.options.find(
    (view) => view.option.id === recommendation.option_id,
  );

  useEffect(() => {
    setQuestion("");
  }, [card.card_id]);

  function ask(event: FormEvent) {
    event.preventDefault();
    if (question.trim() && !busy) {
      act({ action: "ask", question: question.trim() });
      setQuestion("");
    }
  }

  return (
    <section className="panel">
      <p className="eyebrow">{LAYER_NAMES[card.layer] ?? card.layer}</p>
      <h2 ref={heading} tabIndex={-1}>
        {card.question}
      </h2>
      {prompt.error && (
        <p className="alert" role="alert">
          {prompt.error}
        </p>
      )}
      <div className="recommendation">
        {recommended ? (
          <>
            <strong>추천: {recommended.option.name}</strong>
            {recommendation.reason && <p>{recommendation.reason}</p>}
            {recommendation.decider === "mock" ? (
              <p className="muted">
                카드 기본값이에요. 내 프로젝트를 분석한 결과는 아니에요.
              </p>
            ) : (
              recommendation.confidence !== null && (
                <p className="muted">
                  판단 확신도 {Math.round(recommendation.confidence * 100)}%
                </p>
              )
            )}
          </>
        ) : (
          <strong>비교 필요: 하나를 추천할 근거가 부족해요.</strong>
        )}
        {card.evidence.map((item) => (
          <p className="evidence" key={`${item.source_id}-${item.location}`}>
            <strong>내 강의 필기:</strong>{" "}
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.title}
              </a>
            ) : (
              item.title
            )}{" "}
            ({item.location}) · {item.why}
          </p>
        ))}
        <p className="muted">
          {card.evidence.length > 0
            ? "개인 필기이며 강의 원문이 아니에요."
            : "연결된 강의 자료 없음"}
        </p>
        {recommended && (
          <button
            className="primary accept"
            disabled={busy}
            onClick={() => act({ action: "accept_recommendation" })}
          >
            추천대로 진행
          </button>
        )}
      </div>
      {card.advice_source === "llm" && (
        <p className="muted">
          선택지 설명은 AI가 내 프로젝트를 기준으로 쓴 내용이에요. 틀릴 수
          있어요.
        </p>
      )}
      {card.advice_source === "card_text" && (
        <p className="muted">
          AI 설명을 만들지 못해 카드의 기본 설명을 보여드려요.
        </p>
      )}
      <div className="options">
        {card.options.map((view) => (
          <OptionCard
            key={view.option.id}
            view={view}
            recommended={view.option.id === recommendation.option_id}
            busy={busy}
            act={act}
          />
        ))}
      </div>
      <div className="row">
        <button disabled={busy} onClick={() => act({ action: "defer" })}>
          나중에 결정
        </button>
      </div>
      <form className="ask" onSubmit={ask}>
        <label htmlFor="card-question">이 카드에 대해 질문하기</label>
        {prompt.qa.map((item, index) => (
          <div className="qa" key={index}>
            <p>
              <strong>Q.</strong> {item.question}
            </p>
            <p>
              <strong>A.</strong> {item.answer}
            </p>
          </div>
        ))}
        <div className="row">
          <input
            id="card-question"
            value={question}
            maxLength={2000}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button disabled={busy || !question.trim()}>질문</button>
        </div>
      </form>
    </section>
  );
}

export function IssuesView({
  prompt,
  cards,
  busy,
  act,
}: {
  prompt: IssuesPrompt;
  cards: CardStatus[];
  busy: boolean;
  act: Act;
}) {
  const heading = useFocusedHeading();
  const errors = prompt.issues.filter((issue) => issue.severity === "error");
  return (
    <section className="panel">
      <h2 ref={heading} tabIndex={-1}>
        함께 쓸 수 없는 결정이 있어요
      </h2>
      <p className="muted">아래 결정 중 하나를 다시 골라 주세요.</p>
      {prompt.error && (
        <p className="alert" role="alert">
          {prompt.error}
        </p>
      )}
      {errors.map((issue) => (
        <article className="issue" key={issue.rule_id}>
          <p>{issue.message}</p>
          <div className="row">
            {issue.card_ids
              .map((id) => cards.find((card) => card.card_id === id))
              .filter((card) => card?.state === "decided")
              .map((card) => (
                <button
                  key={card!.card_id}
                  disabled={busy}
                  onClick={() =>
                    act({ action: "reopen", card_id: card!.card_id })
                  }
                >
                  다시 고르기: {card!.question}
                </button>
              ))}
          </div>
        </article>
      ))}
    </section>
  );
}

const NODE_KIND: Record<string, string> = {
  agent: "에이전트",
  code: "코드",
  human: "사람 확인",
};

export function CompletedView({
  journey,
  onRestart,
}: {
  journey: Journey;
  onRestart: () => void;
}) {
  const heading = useFocusedHeading();
  const design = journey.design;
  return (
    <section className="panel">
      <h2 ref={heading} tabIndex={-1}>
        {design ? "빌드 묶음을 만들었어요" : "모든 결정을 마쳤어요"}
      </h2>
      <p className="muted">{journey.idea}</p>
      {design && (
        <>
          {design.error && (
            <p className="note warn">
              <strong>참고용</strong> {design.error}
            </p>
          )}
          <h3>에이전트 구성</h3>
          <ol className="summary">
            {design.nodes.map((node) => (
              <li key={node.id}>
                <span className="eyebrow">{NODE_KIND[node.kind] ?? node.kind}</span>
                <strong>{node.id}</strong>
                <span>{node.responsibility}</span>
              </li>
            ))}
          </ol>
          <h3>첫 작업</h3>
          <p>{design.first_task}</p>
          <p className="muted">완료 확인: {design.first_task_check}</p>
          {design.unknowns.length > 0 && (
            <>
              <h3>먼저 확인할 것</h3>
              <ul>
                {design.unknowns.map((unknown) => (
                  <li key={unknown}>{unknown}</li>
                ))}
              </ul>
            </>
          )}
          {design.warnings.map((warning) => (
            <p className="note warn" key={warning}>
              <strong>확인 필요</strong> {warning}
            </p>
          ))}
          <p className="muted">
            압축을 풀고 Claude Code나 Codex에 <code>BUILD.md</code>대로
            만들어 달라고 요청하세요. 파일 {design.files.length}개가 들어
            있어요.
          </p>
          <div className="row">
            <a
              className="button primary"
              href={packageUrl(journey.journey_id)}
              download="starter-pack.zip"
            >
              빌드 묶음 다운로드
            </a>
            <a className="button" href={designViewUrl(journey.journey_id)}>
              설계 그래프로 보기
            </a>
          </div>
          <h3>내가 고른 기술</h3>
        </>
      )}
      {journey.warnings.map((warning) => (
        <p className="note warn" key={warning}>
          <strong>확인 필요</strong> {warning}
        </p>
      ))}
      <ol className="summary">
        {journey.cards.map((card) => (
          <li key={card.card_id}>
            <span className="eyebrow">
              {LAYER_NAMES[card.layer] ?? card.layer}
            </span>
            <span>{card.question}</span>
            <strong>{card.option_name}</strong>
            {card.by && <span className="badge">{BY_LABEL[card.by]}</span>}
            {card.by === "implied" && (
              <span className="muted">{card.rationale}</span>
            )}
          </li>
        ))}
      </ol>
      <p className="muted">
        요약 문서에는 결정 이유와 감수할 점, 먼저 확인할 일이 들어 있어요.
        팀원과 함께 읽어 보세요.
      </p>
      <div className="row">
        <a
          className={design ? "button" : "button primary"}
          href={summaryUrl(journey.journey_id)}
          download="decision-summary.md"
        >
          결정 요약 다운로드
        </a>
        <button onClick={onRestart}>새 프로젝트 시작</button>
      </div>
    </section>
  );
}

export function ProgressRail({
  journey,
  busy,
  act,
}: {
  journey: Journey;
  busy: boolean;
  act: Act;
}) {
  const done = journey.cards.filter(
    (card) => card.state === "decided" || card.state === "implied",
  ).length;
  const canReopen = journey.prompt?.type === "decision";
  return (
    <aside className="rail" aria-label="결정 진행 상황">
      <p className="rail-title">
        <strong>
          {done} / {journey.cards.length}
        </strong>{" "}
        결정 완료
      </p>
      <progress value={done} max={journey.cards.length} aria-hidden />
      <ol>
        {journey.cards.map((card) => (
          <li
            key={card.card_id}
            className={`step ${card.state}`}
            aria-current={card.state === "current" ? "step" : undefined}
          >
            <span className="step-layer">{card.title}</span>
            <span className="step-value">
              {card.option_name ??
                STATE_LABEL[card.state as keyof typeof STATE_LABEL]}
              {card.state === "implied" && " · 자동 확정"}
            </span>
            {canReopen && card.state === "decided" && (
              <button
                className="link"
                disabled={busy}
                aria-label={`${card.title} 다시 고르기`}
                onClick={() => act({ action: "reopen", card_id: card.card_id })}
              >
                다시 고르기
              </button>
            )}
          </li>
        ))}
      </ol>
    </aside>
  );
}

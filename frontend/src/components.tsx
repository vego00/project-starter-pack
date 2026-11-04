import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type {
  Action,
  CardStatus,
  ClarifyPrompt,
  DecisionPrompt,
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
      <h2 tabIndex={-1}>프로젝트를 조금 더 알려 주세요</h2>
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
    <article className={`option${blocked ? " blocked" : ""}`}>
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
  const heading = useRef<HTMLHeadingElement>(null);
  const recommendation = card.recommendation;
  const recommended = card.options.find(
    (view) => view.option.id === recommendation.option_id,
  );

  useEffect(() => {
    setQuestion("");
    heading.current?.focus();
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
                  신뢰도 {Math.round(recommendation.confidence * 100)}%
                </p>
              )
            )}
          </>
        ) : (
          <strong>비교 필요: 하나를 추천할 근거가 부족해요.</strong>
        )}
        <p className="muted">
          {card.evidence.length > 0
            ? `참고 자료: ${card.evidence.map((item) => item.title).join(", ")}`
            : "연결된 강의 자료 없음"}
          {card.div_refs.length > 0 &&
            ` · 근거가 된 DiV 문제: ${card.div_refs.join(", ")}`}
        </p>
      </div>
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
        {recommended && (
          <button
            disabled={busy}
            onClick={() => act({ action: "accept_recommendation" })}
          >
            추천대로 진행
          </button>
        )}
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
  const errors = prompt.issues.filter((issue) => issue.severity === "error");
  return (
    <section className="panel">
      <h2 tabIndex={-1}>함께 쓸 수 없는 결정이 있어요</h2>
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

export function CompletedView({
  journey,
  onRestart,
}: {
  journey: Journey;
  onRestart: () => void;
}) {
  return (
    <section className="panel">
      <h2 tabIndex={-1}>모든 결정을 마쳤어요</h2>
      <p className="muted">{journey.idea}</p>
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
      <button onClick={onRestart}>새 프로젝트 시작</button>
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
            <span className="step-layer">
              {LAYER_NAMES[card.layer] ?? card.layer}
            </span>
            <span className="step-value">
              {card.option_name ??
                STATE_LABEL[card.state as keyof typeof STATE_LABEL]}
              {card.state === "implied" && " · 자동 확정"}
            </span>
            {canReopen && card.state === "decided" && (
              <button
                className="link"
                disabled={busy}
                aria-label={`${LAYER_NAMES[card.layer] ?? card.layer} 다시 고르기`}
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

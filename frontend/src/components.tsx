import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import { packageUrl, summaryUrl } from "./api";
import type {
  Action,
  CardStatus,
  ClarifyPrompt,
  DecisionPrompt,
  ForkPrompt,
  GcbPrompt,
  IssuesPrompt,
  Journey,
} from "./api";
import { OptionIcon } from "./blueprint";

const LAYER_NAMES: Record<string, string> = {
  agent: "에이전트 설계",
  model: "모델",
  data: "데이터와 검색",
  backend: "백엔드 실행",
  devops: "실행 환경",
  mlops: "모델 서빙",
  cloud: "배포",
  product: "제품 형태",
  ops: "검증과 운영",
};
// ADR-021. Stages without a card yet are named once, so the whole path can still be seen.
export const STAGE_NAMES = [
  "제약 확인",
  "데이터 이해",
  "주제 확정",
  "제품 형태",
  "에이전트 설계",
  "시스템 구성",
  "검증·운영",
  "팀 실행",
];
const LEVELS = { low: "낮음", medium: "보통", high: "높음" };
const BY_LABEL = {
  user: "직접 선택",
  recommended: "추천대로",
  implied: "자동 확정",
};
// Rows a person can go back to; the whole row reopens the card.
const REOPEN_LABEL: Partial<Record<string, string>> = {
  decided: "다시 고르기",
  skipped: "다시 넣기",
};
const FOCUS_LABEL: Partial<Record<string, string>> = {
  pending: "먼저 정하기",
  deferred: "먼저 정하기",
};
const STATE_LABEL = {
  deferred: "나중에",
  current: "지금 결정",
  pending: "대기",
  skipped: "해당 없음",
  unplanned: "정하지 않음",
};

export const EXAMPLES = [
  "부트캠프 강의 자료를 찾아 질문에 답하고 출처를 알려주는 멀티 에이전트 서비스를 만들고 싶어요.",
  "회의록에서 담당자별 할 일을 뽑아 팀 메신저로 보내기 전에 사람이 확인하는 에이전트를 만들고 싶어요.",
];

export const MIN_IDEA = 10;
export const MAX_IDEA = 3000;

type Act = (action: Action) => void;
type CardSignal = DecisionPrompt["card"]["signals"][number];

/** Where a start field or card info value came from. */
export const SOURCE: Record<
  "said" | "picked" | "default" | "recommended",
  string
> = {
  said: "내 말에서",
  picked: "직접 고름",
  default: "기본값",
  recommended: "추천",
};

/** The info a card reads, above its options; changing one prepares the card again (ADR-024). */
function SignalStrip({
  signals,
  busy,
  act,
}: {
  signals: CardSignal[];
  busy: boolean;
  act: Act;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  function pick(signal: CardSignal, value: string) {
    if (signal.kind === "multi") {
      const held = Array.isArray(signal.value) ? signal.value : [];
      const values = held.includes(value)
        ? held.filter((item) => item !== value)
        : [...held, value];
      act({ action: "signal", field: signal.name, values });
    } else act({ action: "signal", field: signal.name, value });
  }

  function typed(event: FormEvent, signal: CardSignal) {
    event.preventDefault();
    if (draft.trim())
      act({ action: "signal", field: signal.name, value: draft.trim() });
  }

  return (
    <div className="signal-strip" role="group" aria-label="이 카드가 쓰는 정보">
      <p className="signal-strip-head">
        이 카드가 쓰는 정보 · <span>바꾸면 추천이 다시 정해져요</span>
      </p>
      <div className="signal-chips">
        {signals.map((signal) => (
          <button
            type="button"
            key={signal.name}
            className="signal-chip"
            aria-expanded={open === signal.name}
            onClick={() => {
              setDraft("");
              setOpen(open === signal.name ? null : signal.name);
            }}
          >
            {signal.label} <strong>{signal.display}</strong>
            {signal.source && (
              <span className="signal-source"> {SOURCE[signal.source]}</span>
            )}
          </button>
        ))}
      </div>
      {signals
        .filter((signal) => signal.name === open)
        .map((signal) => {
          const held = Array.isArray(signal.value)
            ? signal.value
            : [signal.value];
          return (
            <div key={signal.name} className="signal-edit">
              {signal.why && <p className="muted">{signal.why}</p>}
              <div className="start-choices">
                {signal.choices.map((choice) => (
                  <button
                    type="button"
                    key={choice.value}
                    className={held.includes(choice.value) ? "on" : ""}
                    aria-pressed={held.includes(choice.value)}
                    disabled={busy}
                    onClick={() => pick(signal, choice.value)}
                  >
                    {choice.label}
                  </button>
                ))}
              </div>
              {signal.free_text && (
                <form
                  className="start-type"
                  onSubmit={(event) => typed(event, signal)}
                >
                  <label htmlFor={`signal-${signal.name}`} className="sr-only">
                    {signal.label} 직접 적기
                  </label>
                  <input
                    id={`signal-${signal.name}`}
                    maxLength={40}
                    placeholder="직접 적기"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                  />
                  <button disabled={busy || !draft.trim()}>저장</button>
                </form>
              )}
            </div>
          );
        })}
    </div>
  );
}

// The button that was pressed is gone after a screen change, so keyboard users need a new place.
function useFocusedHeading(screenKey?: string | number) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [screenKey]);
  return heading;
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

function collectAnswers(
  form: FormData,
  questions: { field: string }[],
): Record<string, unknown> {
  const answers: Record<string, unknown> = {};
  for (const { field } of questions) {
    const raw = String(form.get(field) ?? "").trim();
    if (raw) answers[field] = toAnswer(field, raw);
  }
  return answers;
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
    act({
      action: "clarify",
      answers: collectAnswers(
        new FormData(event.currentTarget),
        prompt.questions,
      ),
    });
  }

  return (
    // Fields are uncontrolled, so a new round must start from an empty form.
    <form className="brief" key={prompt.round} onSubmit={submit}>
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
  reason,
  held,
  changing,
  busy,
  act,
}: {
  view: DecisionPrompt["card"]["options"][number];
  recommended: boolean;
  reason: ReactNode;
  held: boolean;
  changing: boolean;
  busy: boolean;
  act: Act;
}) {
  const { option } = view;
  const blocked = view.blocked_reason !== null;
  const primary = recommended && !changing;
  // Voice control users say the words they see, so the name has to contain them.
  const chooseLabel = primary ? "이걸로 정하기" : changing ? "바꾸기" : "선택";
  return (
    <article
      className={`option${blocked ? " blocked" : ""}${primary ? " recommended" : ""}${held ? " held" : ""}`}
    >
      <header>
        {view.icon && <OptionIcon icon={view.icon} />}
        <h3>{option.name}</h3>
        {recommended && <span className="badge">추천</span>}
        {held && <span className="badge">현재 선택</span>}
      </header>
      {recommended && reason}
      <p className="option-summary">{view.note || option.summary}</p>
      <ul className="tradeoffs">
        {option.pros.map((item) => (
          <li key={item}>
            <span className="sr-only">장점 </span>
            <span aria-hidden>+ </span>
            {item}
          </li>
        ))}
        {option.cons.map((item) => (
          <li key={item}>
            <span className="sr-only">단점 </span>
            <span aria-hidden>− </span>
            {item}
          </li>
        ))}
      </ul>
      <p className="option-meta">
        학습 {LEVELS[option.learning_difficulty]} · 운영{" "}
        {LEVELS[option.ops_burden]} · {option.cost_nature}
      </p>
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
      {view.must_change.length > 0 && (
        <div className="note warn">
          <strong>바꿔야 할 가능성이 높아요</strong>
          {view.must_change.map((answer) => (
            <p key={answer}>{answer}</p>
          ))}
        </div>
      )}
      {blocked && (
        <p className="note warn">
          <strong>지금은 고를 수 없어요.</strong> {view.blocked_reason}
        </p>
      )}
      {!held && (
        <button
          className={primary ? "primary choose" : "choose"}
          disabled={blocked || busy}
          aria-label={`${option.name} ${chooseLabel}`}
          onClick={() =>
            act(
              primary
                ? { action: "accept_recommendation" }
                : { action: "select", option_id: option.id },
            )
          }
        >
          {chooseLabel}
        </button>
      )}
    </article>
  );
}

/** Waiting for a card's recommendation: what the person can do meanwhile, and how long. */
function PreparingNote({
  failed,
  onRetry,
}: {
  failed: boolean;
  onRetry: () => void;
}) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (failed) return;
    const started = Date.now();
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [failed]);

  if (failed)
    return (
      <div className="note preparing">
        <p>
          <strong>추천을 받지 못했어요.</strong> 선택지는 지금 그대로 고를 수
          있어요.
        </p>
        <button onClick={onRetry}>추천 다시 받기</button>
      </div>
    );
  return (
    <p className="note preparing">
      <strong>
        추천을 준비하고 있어요{seconds >= 3 && ` (${seconds}초)`}.
      </strong>{" "}
      선택지별 설명도 함께 와요. 기다리지 않고 먼저 골라도 돼요.
    </p>
  );
}

export function DecisionView({
  prompt,
  busy,
  act,
  prepareFailed = false,
  onRetryPrepare = () => {},
}: {
  prompt: DecisionPrompt;
  busy: boolean;
  act: Act;
  prepareFailed?: boolean;
  onRetryPrepare?: () => void;
}) {
  const { card } = prompt;
  const [question, setQuestion] = useState("");
  const heading = useFocusedHeading(card.card_id);
  const recommendation = card.recommendation;
  const recommendedId = recommendation?.option_id ?? null;
  const heldId = prompt.current_option_id ?? null;
  const held = card.options.find((view) => view.option.id === heldId);
  const recommendedView = card.options.find(
    (view) => view.option.id === recommendedId,
  );
  // A card shown before its recommendation keeps its order, so nothing moves under the pointer.
  const firstSeen = useRef({ id: card.card_id, preparing: card.preparing });
  if (firstSeen.current.id !== card.card_id)
    firstSeen.current = { id: card.card_id, preparing: card.preparing };
  const arrived = firstSeen.current.preparing && !card.preparing;
  // Otherwise the recommended option leads, and carries its own reason.
  const ordered = firstSeen.current.preparing
    ? card.options
    : [...card.options].sort(
        (a, b) =>
          Number(b.option.id === recommendedId) -
          Number(a.option.id === recommendedId),
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

  const reason = recommendation && (
    <>
      {recommendation.reason && (
        <p className="option-reason">{recommendation.reason}</p>
      )}
      {recommendation.decider !== "mock" &&
        recommendation.confidence !== null && (
          <p className="option-reason">
            판단 확신도 {Math.round(recommendation.confidence * 100)}%
          </p>
        )}
    </>
  );

  return (
    <section className="decision">
      <div className="decision-body">
        <p className="eyebrow">{LAYER_NAMES[card.layer] ?? card.layer}</p>
        <h2 ref={heading} tabIndex={-1}>
          {card.question}
        </h2>
        {card.signals.length > 0 && (
          <SignalStrip
            key={card.card_id}
            signals={card.signals}
            busy={busy}
            act={act}
          />
        )}
        {prompt.error && (
          <p className="alert" role="alert">
            {prompt.error}
          </p>
        )}
        {held && (
          <p className="muted option-source">
            지금 결정은 그대로예요. 다른 선택지를 고를 때만 바뀌어요.
          </p>
        )}
        {card.to_review.length > 0 && (
          <div className="note">
            <strong>
              바꾸면 뒤 단계 결정 {card.to_review.length}개를 다시 확인하게 돼요
            </strong>
            <p>{card.to_review.join(" · ")}</p>
          </div>
        )}
        {card.preparing ? (
          <PreparingNote failed={prepareFailed} onRetry={onRetryPrepare} />
        ) : (
          !recommendedView && (
            <p className="note">
              <strong>비교 필요: 하나를 추천할 근거가 부족해요.</strong>
            </p>
          )
        )}
        <p className="sr-only" role="status">
          {arrived &&
            (recommendedView
              ? `추천이 왔어요: ${recommendedView.option.name}`
              : "추천할 근거가 부족해 직접 비교해야 해요.")}
        </p>
        {card.evidence.length > 0 && (
          <div className="note">
            {card.evidence.map((item) => (
              <p
                className="evidence"
                key={`${item.source_id}-${item.location}`}
              >
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
            <p className="muted">개인 필기이며 강의 원문이 아니에요.</p>
          </div>
        )}
        {card.advice_source === "llm" && (
          <p className="muted option-source">
            선택지 설명은 AI가 내 프로젝트를 기준으로 쓴 내용이에요. 틀릴 수
            있어요.
          </p>
        )}
        {card.advice_source === "card_text" && !card.preparing && (
          <p className="muted option-source">
            AI 설명을 만들지 못해 카드의 기본 설명을 보여드려요.
          </p>
        )}
        <div className="options">
          {ordered.map((view) => (
            <OptionCard
              key={view.option.id}
              view={view}
              recommended={view.option.id === recommendedId}
              reason={reason}
              held={view.option.id === heldId}
              changing={held !== undefined}
              busy={busy}
              act={act}
            />
          ))}
        </div>
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
      </div>
      {held ? (
        <div className="decision-foot">
          <button
            className="primary keep-held"
            disabled={busy}
            onClick={() => act({ action: "defer" })}
          >
            {held.option.name} 그대로 두기
          </button>
        </div>
      ) : (
        <form className="decision-foot" onSubmit={ask}>
          <label htmlFor="card-question">이 카드에 대해 질문하기</label>
          <div className="row">
            <input
              id="card-question"
              value={question}
              maxLength={2000}
              placeholder="헷갈리는 점을 물어보세요"
              onChange={(event) => setQuestion(event.target.value)}
            />
            <button disabled={busy || !question.trim()}>질문</button>
            <button
              type="button"
              className="quiet"
              disabled={busy}
              onClick={() => act({ action: "defer" })}
            >
              나중에 결정
            </button>
          </div>
        </form>
      )}
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

/** After the agent design: end with the system left undecided, or plan it (ADR-024). */
export function ForkView({
  prompt,
  busy,
  act,
}: {
  prompt: ForkPrompt;
  busy: boolean;
  act: Act;
}) {
  const heading = useFocusedHeading();
  const titles = prompt.remaining.map((card) => card.title).join(", ");
  return (
    <section className="panel fork">
      <h2 ref={heading} tabIndex={-1}>
        에이전트 설계를 마쳤어요
      </h2>
      <p className="muted">
        배포할 계획이 없다면 여기서 끝낼 수 있어요. 끝낸 뒤에도 완료 화면에서
        배포 계획을 이어서 세울 수 있어요.
      </p>
      {prompt.error && (
        <p className="alert" role="alert">
          {prompt.error}
        </p>
      )}
      <button
        className="fork-choice"
        disabled={busy}
        onClick={() => act({ action: "end_here" })}
      >
        <strong>여기서 끝내기</strong>
        <span className="muted">
          받는 것: 설계 문서, 에이전트 정의, 사람이 할 일을 적은 인프라 문서가
          든 빌드 묶음
        </span>
        <span className="muted">
          빠지는 것: {titles}. 묶음의 인프라 문서에는 ‘아직 정하지 않음’으로
          나가요.
        </span>
      </button>
      <button
        className="fork-choice"
        disabled={busy}
        onClick={() => act({ action: "plan_deploy" })}
      >
        <strong>배포 계획 세우기</strong>
        <span className="muted">
          카드 {prompt.remaining.length}장이 더 있어요. {titles}.
        </span>
        {prompt.asks.length > 0 && (
          <span className="muted">
            카드에서 물어볼 정보: {prompt.asks.join(", ")}
          </span>
        )}
      </button>
    </section>
  );
}

const NODE_KIND: Record<string, string> = {
  agent: "에이전트",
  code: "코드",
  human: "사람 확인",
};

export type SideView = "summary" | "chat";

/** The design is being made: what is ready now, how long it has taken, and what waits for it. */
function DesigningNote({
  stuck,
  onRetry,
}: {
  stuck: boolean;
  onRetry: () => void;
}) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (stuck) return;
    const started = Date.now();
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [stuck]);

  if (stuck)
    return (
      <div className="note designing" id="design-wait">
        <p>
          <strong>설계를 아직 받지 못했어요.</strong> 15분 넘게 기다렸지만
          끝났다는 응답이 없어요. 다시 시도하면 만들던 설계를 이어서 만들고,
          이미 끝났으면 바로 보여 드려요.
        </p>
        <button onClick={onRetry}>다시 시도</button>
      </div>
    );
  const minutes = Math.floor(seconds / 60);
  const elapsed =
    minutes > 0 ? `${minutes}분 ${seconds % 60}초` : `${seconds}초`;
  return (
    <p className="note designing" id="design-wait">
      <strong>설계를 만들고 있어요 ({elapsed}).</strong> 몇 분 걸릴 수 있어요.
      끝나면 이 자리에서 빌드 묶음을 받을 수 있고, 이 화면을 닫아도 설계는 계속
      만들어요. 설계를 만드는 동안에는 결정을 바꿀 수 없어요.
    </p>
  );
}

export function CompletedView({
  journey,
  graph,
  onRestart,
  moduleChat,
  side = "summary",
  onSide,
  onPlanDeploy,
  busy = false,
  designing,
}: {
  journey: Journey;
  graph: ReactNode;
  onRestart: () => void;
  onPlanDeploy?: () => void;
  busy?: boolean;
  moduleChat?: ReactNode;
  side?: SideView;
  onSide?: (side: SideView) => void;
  /** Set while the design is being made after the last decision. */
  designing?: { stuck: boolean; onRetry: () => void };
}) {
  const hasChat = moduleChat !== undefined && journey.module_mode !== "closed";
  const showChat = hasChat && side === "chat";
  const heading = useFocusedHeading();
  const design = journey.design;
  // Said once when the design arrives on this screen, not on every visit.
  const waited = useRef(false);
  if (designing) waited.current = true;
  const arrived = waited.current && !designing && Boolean(design);
  const count = journey.cards.filter((card) => card.option_name).length;
  const unplanned = journey.cards.filter((card) => card.state === "unplanned");
  return (
    <>
      <section className="done-band">
        <div className="done-title">
          <p className="muted">
            {unplanned.length > 0
              ? `에이전트 설계까지 결정 ${count}개를 마쳤어요`
              : `결정 ${count}개를 모두 마쳤어요`}
          </p>
          <h2 ref={heading} tabIndex={-1}>
            {design ? "설계가 준비됐어요" : "모든 결정을 마쳤어요"}
          </h2>
          <p>{journey.idea}</p>
          {designing && (
            <DesigningNote
              stuck={designing.stuck}
              onRetry={designing.onRetry}
            />
          )}
          <p className="sr-only" role="status">
            {arrived && "설계가 준비됐어요. 빌드 묶음을 받을 수 있어요."}
          </p>
          {design && (
            <p className="muted">
              압축을 풀고 Claude Code나 Codex에 <code>BUILD.md</code>대로 만들어
              달라고 요청하세요.
            </p>
          )}
        </div>
        <div className="done-actions">
          {designing && (
            <button disabled aria-describedby="design-wait">
              빌드 묶음 다운로드
            </button>
          )}
          {design && (
            <a
              className="button primary"
              href={packageUrl(journey.journey_id)}
              download="starter-pack.zip"
            >
              빌드 묶음 다운로드 (파일 {design.files.length}개)
            </a>
          )}
          {journey.can_plan_deploy && (
            <button
              className="wide"
              disabled={busy}
              onClick={() => onPlanDeploy?.()}
            >
              배포 계획 이어서 세우기 (카드 {unplanned.length}장)
            </button>
          )}
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
      {design?.error && (
        <p className="note warn">
          <strong>참고용</strong> {design.error}
        </p>
      )}
      {design?.warnings.map((warning) => (
        <p className="note warn" key={warning}>
          <strong>확인 필요</strong> {warning}
        </p>
      ))}
      {journey.warnings.map((warning) => (
        <p className="note warn" key={warning}>
          <strong>확인 필요</strong> {warning}
        </p>
      ))}
      <div className="done-grid">
        <div className="done-main">
          {graph}
          {design && (
            <>
              <h3>에이전트 구성</h3>
              <ol className="summary">
                {design.nodes.map((node) => (
                  <li key={node.id}>
                    <span className="eyebrow">
                      {NODE_KIND[node.kind] ?? node.kind}
                    </span>
                    <strong>{node.id}</strong>
                    <span>{node.responsibility}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
        <aside
          className="done-side"
          aria-label={showChat ? "모듈 대화" : "결과 요약"}
        >
          {hasChat && (
            <div className="segment" role="group" aria-label="오른쪽 내용">
              <button
                className={showChat ? "" : "on"}
                aria-pressed={!showChat}
                onClick={() => onSide?.("summary")}
              >
                결과 요약
              </button>
              <button
                className={showChat ? "on" : ""}
                aria-pressed={showChat}
                onClick={() => onSide?.("chat")}
              >
                {journey.module_mode === "form" ? "모듈 채우기" : "모듈 대화"}
              </button>
            </div>
          )}
          {showChat ? moduleChat : <ResultSummary journey={journey} />}
        </aside>
      </div>
    </>
  );
}

function ResultSummary({ journey }: { journey: Journey }) {
  const design = journey.design;
  return (
    <>
      {design && (
        <>
          <h3>가장 먼저 할 일</h3>
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
        </>
      )}
      <h3>내가 고른 기술</h3>
      <ol className="summary">
        {[...journey.cards]
          .sort((a, b) => a.stage - b.stage)
          .map((card) => (
            <li key={card.card_id}>
              <span className="eyebrow">{card.title}</span>
              <strong>
                {card.option_name ??
                  (card.state === "skipped" || card.state === "unplanned"
                    ? STATE_LABEL[card.state]
                    : null)}
              </strong>
              {card.by && <span className="badge">{BY_LABEL[card.by]}</span>}
              {card.by === "implied" && (
                <span className="muted">{card.rationale}</span>
              )}
            </li>
          ))}
      </ol>
      {journey.can_reopen && (
        <p className="muted">
          바꾸고 싶은 결정은 구성도의 아이콘이나 위쪽 단계에서 고칠 수 있어요.
          다른 선택지를 고르면 설계와 빌드 묶음을 다시 만들어요. 그래프에서 직접
          고친 내용은 새 설계에 다시 적용해요.
        </p>
      )}
    </>
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
  // Skipped cards are not asked, so they are not part of what is left to decide.
  const total = journey.cards.filter((card) => card.state !== "skipped").length;
  const atFork = journey.prompt?.type === "fork";
  const canReopen =
    journey.prompt?.type === "decision" || atFork || journey.can_reopen;
  const canFocus = journey.prompt?.type === "decision";
  const stages = STAGE_NAMES.map((name, stage) => ({
    name,
    cards: journey.cards.filter((card) => card.stage === stage),
  }));
  const unopened = stages.filter((stage) => stage.cards.length === 0);
  const opened = stages.filter((stage) => stage.cards.length > 0);
  const [picked, setPicked] = useState<string | null>(null);
  const shown = opened.find((stage) => stage.name === picked);
  const root = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!picked) return;
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setPicked(null);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [picked]);

  function closeOnEscape(event: KeyboardEvent) {
    if (event.key === "Escape") setPicked(null);
  }

  function row(card: CardStatus) {
    const reopen =
      canReopen && !card.editing ? REOPEN_LABEL[card.state] : undefined;
    const focus = canFocus ? FOCUS_LABEL[card.state] : undefined;
    const plan =
      journey.can_plan_deploy && card.state === "unplanned"
        ? "이어서 정하기"
        : undefined;
    const action = reopen ?? focus ?? plan;
    const value = (
      <span className="step-value">
        {card.option_name ??
          STATE_LABEL[card.state as keyof typeof STATE_LABEL]}
        {card.state === "implied" && " · 자동 확정"}
        {card.state === "skipped" &&
          card.skip_confidence != null &&
          ` · 확신도 ${Math.round(card.skip_confidence * 100)}%`}
      </span>
    );
    return (
      <li
        key={card.card_id}
        className={`step ${card.editing ? "current" : card.state}${action ? " clickable" : ""}${card.needs_review ? " review" : ""}`}
        aria-current={card.state === "current" ? "step" : undefined}
      >
        {action ? (
          <button
            className="step-button"
            disabled={busy}
            aria-label={`${card.title} ${action}`}
            onClick={() => {
              setPicked(null);
              act(
                reopen
                  ? {
                      action: card.state === "decided" ? "revise" : "reopen",
                      card_id: card.card_id,
                    }
                  : plan
                    ? { action: "plan_deploy", card_id: card.card_id }
                    : { action: "focus", card_id: card.card_id },
              );
            }}
          >
            <span className="step-head">
              <span className="step-layer">{card.title}</span>
              <span className="step-action" aria-hidden>
                {action}
              </span>
            </span>
            {value}
          </button>
        ) : (
          <>
            <span className="step-layer">{card.title}</span>
            {value}
          </>
        )}
        {card.needs_review && (
          <div className="step-review">
            <span>앞 단계가 바뀌었어요. 다시 확인해 주세요.</span>
            {canReopen && (
              <button
                disabled={busy}
                aria-label={`${card.title} 현재 결정 유지`}
                onClick={() => act({ action: "keep", card_id: card.card_id })}
              >
                현재 결정 유지
              </button>
            )}
          </div>
        )}
      </li>
    );
  }

  return (
    <aside
      className="rail"
      aria-label="결정 진행 상황"
      ref={root}
      onKeyDown={closeOnEscape}
    >
      <div className="rail-head">
        <div className="stage-strip">
          {opened.map((stage) => {
            const counted = stage.cards.filter((c) => c.state !== "skipped");
            const decided = counted.filter(
              (c) => c.state === "decided" || c.state === "implied",
            ).length;
            const reviews = stage.cards.filter((c) => c.needs_review).length;
            const isCurrent = stage.cards.some(
              (c) => c.state === "current" || c.editing,
            );
            return (
              <button
                key={stage.name}
                className={`stage-tab${isCurrent ? " current" : ""}`}
                aria-expanded={shown?.name === stage.name}
                aria-current={isCurrent ? "step" : undefined}
                aria-label={`${stage.name} ${decided}/${counted.length}${reviews > 0 ? ` 다시 확인 ${reviews}` : ""}`}
                onClick={() =>
                  setPicked(shown?.name === stage.name ? null : stage.name)
                }
              >
                {stage.name}
                <span className="ticks" aria-hidden>
                  {counted.map((c) => (
                    <span
                      key={c.card_id}
                      className={`tick${c.state === "current" || c.editing ? " now" : c.state === "decided" || c.state === "implied" ? " done" : ""}`}
                    />
                  ))}
                </span>
                {reviews > 0 && (
                  <span className="stage-review">다시 확인 {reviews}</span>
                )}
              </button>
            );
          })}
          {atFork && (
            <span className="stage-tab current" aria-current="step">
              여기서 끝낼까요?
            </span>
          )}
        </div>
        <p className="rail-title">
          <strong>
            {done} / {total}
          </strong>{" "}
          결정
        </p>
      </div>
      {shown && (
        <div className="stage-panel">
          <ol>{shown.cards.map(row)}</ol>
          {unopened.length > 0 && (
            <p className="muted stage-empty">
              {unopened.map((stage) => stage.name).join(", ")} 단계는 아직
              열리지 않았어요.
            </p>
          )}
        </div>
      )}
    </aside>
  );
}

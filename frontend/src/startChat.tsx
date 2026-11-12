import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import type { Journey, StartChange, StartField } from "./api";
import { EXAMPLES, MAX_IDEA, MIN_IDEA } from "./components";

// After this many seconds of reading, say what a reload would lose.
const LONG_WAIT = 40;

/** Each returns an error message, or "" when the server took it. */
type Send = (text: string, focus: string | null) => Promise<string>;
type Edit = (change: StartChange) => Promise<string>;

const SOURCE: Record<NonNullable<StartField["source"]>, string> = {
  said: "내 말에서",
  picked: "직접 고름",
  default: "기본값",
  recommended: "추천",
};

function PanelToggle({
  side,
  open,
  label,
  onToggle,
}: {
  side: "left" | "right";
  open: boolean;
  label: string;
  onToggle: () => void;
}) {
  const icon = (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line
        x1={side === "left" ? 9 : 15}
        y1="4"
        x2={side === "left" ? 9 : 15}
        y2="20"
      />
    </svg>
  );
  return (
    <button
      type="button"
      className={`start-toggle${open ? " on" : ""}`}
      aria-expanded={open}
      aria-controls={`start-panel-${side}`}
      onClick={onToggle}
    >
      {side === "left" && icon}
      {label}
      {side === "right" && icon}
    </button>
  );
}

/** The choices of the field the bot just asked about, so it can be answered by tapping. */
function AnswerChoices({
  field,
  busy,
  answer,
}: {
  field: StartField;
  busy: boolean;
  answer: Edit;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState("");
  const multi = field.kind === "multi";
  const defaults =
    field.default === null
      ? []
      : Array.isArray(field.default)
        ? field.default
        : [field.default];

  async function send(change: StartChange) {
    setError(await answer(change));
  }

  function tap(value: string) {
    if (!multi) void send({ field: field.name, value });
    else
      setPicked(
        picked.includes(value)
          ? picked.filter((item) => item !== value)
          : [...picked, value],
      );
  }

  return (
    <div
      className="chat-answers"
      role="group"
      aria-label={`${field.label} 고르기${multi ? ", 여러 개 고를 수 있어요" : ""}`}
    >
      <div className="start-choices">
        {field.choices.map((choice) => {
          const on = picked.includes(choice.value);
          return (
            <button
              type="button"
              key={choice.value}
              className={on ? "on" : ""}
              aria-pressed={multi ? on : undefined}
              disabled={busy}
              onClick={() => tap(choice.value)}
            >
              {on && (
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path d="M5 12l5 5 9-10" />
                </svg>
              )}
              {choice.label}
              {defaults.includes(choice.value) && (
                <span className="start-source default">기본값</span>
              )}
            </button>
          );
        })}
      </div>
      {multi && (
        <div className="chat-answers-confirm">
          <button
            type="button"
            disabled={busy || picked.length === 0}
            onClick={() => void send({ field: field.name, values: picked })}
          >
            {picked.length > 0
              ? `고른 ${picked.length}개로 정하기`
              : "골라서 정하기"}
          </button>
        </div>
      )}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      <p className="chat-answers-hint">
        누르면 {field.label} 칸에 바로 들어가요. 다르게 답하려면 아래 입력창에
        적어 주세요.
      </p>
    </div>
  );
}

/** Info fields grouped by the card that asks them, in the order the cards first appear. */
function byCard(fields: StartField[]): [string | null, StartField[]][] {
  const groups = new Map<string | null, StartField[]>();
  for (const field of fields) {
    const list = groups.get(field.asked_in) ?? [];
    list.push(field);
    groups.set(field.asked_in, list);
  }
  return [...groups.entries()];
}

function FieldRow({
  field,
  focused,
  asked,
  fresh,
  busy,
  onFocus,
  edit,
}: {
  field: StartField;
  focused: boolean;
  asked: boolean;
  fresh: boolean;
  busy: boolean;
  onFocus: () => void;
  edit: Edit;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const picked = Array.isArray(field.value)
    ? field.value
    : field.value
      ? [field.value]
      : [];

  useEffect(() => {
    if (focused) {
      setDraft(typeof field.value === "string" ? field.value : "");
      setError("");
    }
  }, [focused, field.value]);

  async function save(change: StartChange) {
    setError(await edit(change));
  }

  function toggle(value: string) {
    if (field.kind === "multi") {
      const next = picked.includes(value)
        ? picked.filter((item) => item !== value)
        : [...picked, value];
      void save({ field: field.name, values: next });
    } else void save({ field: field.name, value });
  }

  function submitText(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) void save({ field: field.name, value: draft });
  }

  return (
    <div
      className={`start-field${field.rule_read ? " rule" : ""}${focused ? " focused" : ""}${asked && !focused ? " asked" : ""}${fresh ? " fresh" : ""}`}
    >
      <div className="start-field-head">
        <span className="start-field-label">{field.label}</span>
        {fresh && <span className="start-fresh">방금 채움</span>}
        {asked && !focused && <span className="start-asked">지금 묻는 칸</span>}
        {field.source && (
          <span className={`start-source ${field.source}`}>
            {SOURCE[field.source]}
          </span>
        )}
        <button
          type="button"
          className="quiet"
          aria-pressed={focused}
          aria-label={`${field.label} ${focused ? "고치기 닫기" : "고치기"}`}
          onClick={onFocus}
        >
          {focused ? "닫기" : "고치기"}
        </button>
      </div>
      <p className={field.display ? "start-value" : "start-value empty"}>
        {field.display ?? "비어 있음"}
      </p>
      {field.why && <p className="start-why">{field.why}</p>}
      {focused && (
        <div
          className="start-edit"
          role="group"
          aria-label={`${field.label} 고르기`}
        >
          {field.choices.length > 0 && (
            <div className="start-choices">
              {field.choices.map((choice) => {
                const on = picked.includes(choice.value);
                return (
                  <button
                    type="button"
                    key={choice.value}
                    className={on ? "on" : ""}
                    aria-pressed={on}
                    disabled={busy}
                    onClick={() => toggle(choice.value)}
                  >
                    {choice.label}
                  </button>
                );
              })}
            </div>
          )}
          {(field.kind === "text" || field.free_text) && (
            <form className="start-type" onSubmit={submitText}>
              <label htmlFor={`start-type-${field.name}`} className="sr-only">
                {field.label} 직접 적기
              </label>
              {field.kind === "text" ? (
                <textarea
                  id={`start-type-${field.name}`}
                  rows={3}
                  maxLength={1000}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
              ) : (
                <input
                  id={`start-type-${field.name}`}
                  maxLength={40}
                  placeholder="직접 적기"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
              )}
              <button disabled={busy || !draft.trim()}>저장</button>
            </form>
          )}
          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function StartChat({
  journey,
  busy,
  preview,
  recent,
  onIdea,
  onSend,
  onEdit,
  onAnswer,
  onFill,
  onBegin,
}: {
  journey: Journey | null;
  busy: boolean;
  preview?: ReactNode;
  recent?: ReactNode;
  onIdea: (idea: string) => void;
  onSend: Send;
  onEdit: Edit;
  onAnswer: Edit;
  onFill: () => Promise<string>;
  onBegin: () => void;
}) {
  const start = journey?.start ?? null;
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  const [left, setLeft] = useState(start !== null);
  const [right, setRight] = useState(start !== null);
  // The first idea on its way: the screen turns into the chat before the model answers.
  const [sent, setSent] = useState<{ idea: string; at: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [took, setTook] = useState<number | null>(null);
  const [fresh, setFresh] = useState<string[]>([]);
  const thread = useRef<HTMLDivElement>(null);
  const opened = useRef(start !== null);
  const box = useRef<HTMLTextAreaElement>(null);
  const composer = useRef<HTMLFormElement>(null);
  const boxTop = useRef<number | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const reading = sent !== null && start === null;
  const started = start !== null;
  const shown = started || reading;
  const formOnly = start?.mode === "form";
  const waited = sent ? Math.max(0, Math.floor((now - sent.at) / 1000)) : 0;

  useEffect(() => {
    // The conversation goes on in the box; without a model the screen starts at its heading.
    if (started) (formOnly ? heading : box).current?.focus();
  }, [started, formOnly]);

  useEffect(() => {
    if (!reading) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [reading]);

  useEffect(() => {
    // A failed start goes back to the start screen with the idea still in the box.
    if (reading && !busy) setSent(null);
  }, [reading, busy]);

  useLayoutEffect(() => {
    // The box slides from the middle to the bottom instead of jumping there.
    const form = composer.current;
    const from = boxTop.current;
    boxTop.current = null;
    if (!reading || !form || from === null) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const shift = from - form.getBoundingClientRect().top;
    if (shift !== 0 && form.animate)
      form.animate(
        [{ transform: `translateY(${shift}px)` }, { transform: "none" }],
        { duration: 250, easing: "ease-out" },
      );
  }, [reading]);

  useEffect(() => {
    // The panels open once, when the first sentence has filled them.
    if (start && !opened.current) {
      opened.current = true;
      setLeft(true);
      setRight(true);
      // The first sentence is now the first message; a failed start keeps it in the box.
      setText("");
      if (sent) {
        setTook(Math.max(1, Math.round((Date.now() - sent.at) / 1000)));
        setFresh(
          start.fields.filter((f) => f.value !== null).map((f) => f.name),
        );
        setSent(null);
      }
    }
  }, [start, sent]);

  useEffect(() => {
    if (fresh.length === 0) return;
    const fade = window.setTimeout(() => setFresh([]), 6000);
    return () => window.clearTimeout(fade);
  }, [fresh]);

  useEffect(() => {
    const box = thread.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [start?.chat.length, pending]);

  const isForm = start?.mode === "form";
  const length = Array.from(text.trim()).length;
  const canSend = start
    ? !isForm && length > 0
    : length >= MIN_IDEA && length <= MAX_IDEA;
  const fields = start?.fields ?? [];
  const goal = fields.filter((field) => field.kind === "text");
  const info = fields.filter((field) => field.kind !== "text");
  const focusField = fields.find((field) => field.name === focus);
  const blanks = start?.missing.length ?? 0;
  // The last reply's question, while its field is still blank and nothing is on the way.
  const lastTurn = start?.chat[start.chat.length - 1];
  const asked =
    !isForm && !pending && lastTurn?.role === "assistant" && lastTurn.asks
      ? fields.find(
          (field) => field.name === lastTurn.asks && field.value === null,
        )
      : undefined;

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!canSend || busy) return;
    if (!start) {
      boxTop.current = composer.current?.getBoundingClientRect().top ?? null;
      setSent({ idea: message, at: Date.now() });
      setNow(Date.now());
      setLeft(true);
      setRight(true);
      onIdea(message);
      return;
    }
    setText("");
    setPending(message);
    setError("");
    const failure = await onSend(message, focus);
    setPending("");
    if (failure) {
      setText(message);
      setError(failure);
    } else setFocus(null);
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  }

  async function fill() {
    setError(await onFill());
  }

  function focusOn(name: string, side: "left" | "right") {
    const next = focus === name ? null : name;
    setFocus(next);
    if (next) (side === "left" ? setLeft : setRight)(true);
  }

  const rows = (list: StartField[], side: "left" | "right") =>
    list.map((field) => (
      <FieldRow
        key={field.name}
        field={field}
        focused={focus === field.name}
        asked={asked?.name === field.name}
        fresh={fresh.includes(field.name)}
        busy={busy}
        onFocus={() => focusOn(field.name, side)}
        edit={onEdit}
      />
    ));

  return (
    <div
      className={`start-chat${shown ? " started" : ""}${reading ? " reading" : ""}`}
    >
      {shown && (
        <div className="start-bar">
          <PanelToggle
            side="left"
            open={left}
            label="프로젝트 목표"
            onToggle={() => setLeft(!left)}
          />
          <PanelToggle
            side="right"
            open={right}
            label="추천에 쓰는 정보"
            onToggle={() => setRight(!right)}
          />
        </div>
      )}
      <div className="start-body">
        <section className="start-center" aria-label="대화">
          {reading && (
            <div
              className="chat-thread"
              role="log"
              aria-label="시작 대화"
              aria-busy="true"
            >
              <div className="chat-msg user">
                <p>{sent?.idea}</p>
              </div>
              <div className="chat-msg bot chat-reading">
                <div role="status">
                  <p className="chat-reading-title">보낸 문장을 읽고 있어요</p>
                  <p>
                    문장에서 프로젝트 목표와, 추천에 쓸 정보 중 알 수 있는 칸을
                    찾아 양옆에 채워요.
                  </p>
                  <p className="chat-reading-why">
                    모델이 답을 쓰기 전에 생각하는 단계가 있어서 1분 가까이
                    걸리기도 해요.
                  </p>
                  {waited >= LONG_WAIT && (
                    <p className="chat-reading-long">
                      아직 읽고 있어요. 이 화면을 닫거나 새로고침하면 처음부터
                      다시 보내야 해요.
                    </p>
                  )}
                </div>
                <p className="chat-reading-time" aria-hidden="true">
                  {waited}초 지났어요
                </p>
              </div>
            </div>
          )}
          {!shown && (
            <div className="start-intro">
              <h2>어떤 서비스를 만들고 싶은지 말로 적어 주세요</h2>
              <p className="muted">
                적은 문장으로 목표와 추천에 쓸 정보를 채워요. 모르는 칸은 나중에
                기본값과 추천으로 채울 수 있어요.
              </p>
            </div>
          )}
          {start && (
            <h2 className="sr-only" ref={heading} tabIndex={-1}>
              시작 정보 채우기
            </h2>
          )}
          {start && (
            <div
              className="chat-thread"
              ref={thread}
              role="log"
              aria-live="polite"
              aria-relevant="additions"
              aria-label="시작 대화"
            >
              {start.chat.map((turn, index) => (
                <div
                  key={index}
                  className={`chat-msg ${turn.role === "user" ? "user" : "bot"}`}
                >
                  <p>{turn.text}</p>
                  {turn.picked && (
                    <span className="chat-picked">눌러서 고름</span>
                  )}
                  {turn.changes.length > 0 && (
                    <div className="chat-changes">
                      <strong>채운 곳</strong>
                      {turn.changes.map((change) => (
                        <span key={change}>{change}</span>
                      ))}
                    </div>
                  )}
                  {turn.rejected.map((reason) => (
                    <p key={reason} className="chat-refused">
                      {reason}
                    </p>
                  ))}
                  {took !== null &&
                    index === 1 &&
                    turn.role === "assistant" && (
                      <p className="chat-took">{took}초 걸렸어요</p>
                    )}
                  {turn === lastTurn && asked && asked.choices.length > 0 && (
                    <AnswerChoices
                      key={start.revision}
                      field={asked}
                      busy={busy}
                      answer={onAnswer}
                    />
                  )}
                </div>
              ))}
              {isForm && start.chat.length === 1 && (
                <div className="chat-msg bot">
                  <p>
                    모델이 연결되지 않아 대화로 채울 수 없어요. 양옆 칸을 눌러
                    고르거나 적고, 남은 칸은 아래 버튼으로 채워 주세요.
                  </p>
                </div>
              )}
              {pending && (
                <>
                  <div className="chat-msg user">
                    <p>{pending}</p>
                  </div>
                  <div className="chat-msg bot">
                    <p className="muted">보낸 문장을 정리하는 중이에요…</p>
                  </div>
                </>
              )}
            </div>
          )}
          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}
          {start && (
            <div className="start-actions">
              <p className="muted" role="status">
                {blanks > 0
                  ? `필수 칸 ${blanks}개가 비어 있어요.`
                  : "목표를 모두 채웠어요. 결정을 시작하면 카드를 하나씩 정해요."}
              </p>
              <p className="muted">
                오른쪽 정보는 비워 둬도 결정을 시작할 수 있어요.
              </p>
              <div className="row">
                <button
                  type="button"
                  disabled={busy || blanks === 0}
                  onClick={() => void fill()}
                >
                  목표 빈칸은 알아서 채워 주세요
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={busy || blanks > 0}
                  onClick={onBegin}
                >
                  결정 시작하기
                </button>
              </div>
            </div>
          )}
          {!isForm && (
            <form
              ref={composer}
              className="start-composer"
              onSubmit={(event) => void send(event)}
            >
              {focusField && (
                <div className="start-focus">
                  <span>{focusField.label} 고치는 중</span>
                  <button
                    type="button"
                    className="quiet"
                    aria-label="집중 해제"
                    onClick={() => setFocus(null)}
                  >
                    해제
                  </button>
                </div>
              )}
              <label htmlFor="idea" className="sr-only">
                {shown ? "더 알려 주기" : "프로젝트 아이디어"}
              </label>
              <textarea
                ref={box}
                id="idea"
                rows={3}
                maxLength={MAX_IDEA}
                // While the idea is read, the box stays empty; a failure brings the idea back.
                value={reading ? "" : text}
                disabled={reading}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={onKey}
                placeholder={
                  reading
                    ? "문장을 다 읽으면 이어서 적을 수 있어요."
                    : focusField
                      ? `${focusField.label}에 대해 말해 주세요. 이 칸에만 반영해요.`
                      : start
                        ? "더 알려 주실 것이 있으면 적어 주세요. 예: GPU는 없어요."
                        : "누가 어떤 문제를 겪고, 무엇을 만들고 싶은지 적어 주세요."
                }
              />
              <div className="start-composer-foot">
                {!shown && (
                  <span className="muted">
                    {length.toLocaleString()} / {MAX_IDEA.toLocaleString()}자
                    (최소 {MIN_IDEA}자)
                  </span>
                )}
                <button className="primary" disabled={!canSend || busy}>
                  보내기
                </button>
              </div>
            </form>
          )}
          {!shown && (
            <>
              {/* Someone coming back sees their projects; examples are for a first visit. */}
              {recent ?? (
                <>
                  <p className="muted examples-label">이런 걸 만들 수 있어요</p>
                  <div className="examples">
                    {EXAMPLES.map((example) => (
                      <button
                        type="button"
                        key={example}
                        onClick={() => setText(example)}
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                </>
              )}
              <p className="muted privacy">
                개인정보나 회사 기밀은 적지 마세요. 입력한 내용은 저장되고,
                모델이 연결된 경우 외부 모델 API로 전송돼요.
              </p>
            </>
          )}
        </section>
        {reading && left && (
          <aside
            id="start-panel-left"
            className="start-panel left"
            aria-label="프로젝트 목표"
          >
            <h2>프로젝트 목표</h2>
            <p className="muted">문장을 다 읽으면 여기에 채워져요.</p>
          </aside>
        )}
        {reading && right && (
          <aside
            id="start-panel-right"
            className="start-panel right"
            aria-label="추천에 쓰는 정보"
          >
            <h2>추천에 쓰는 정보</h2>
            <p className="muted">문장을 다 읽으면 여기에 채워져요.</p>
          </aside>
        )}
        {start && left && (
          <aside
            id="start-panel-left"
            className="start-panel left"
            aria-label="프로젝트 목표"
          >
            <div className="start-panel-head">
              <h2>프로젝트 목표</h2>
              <span className="start-need required">
                필수 ·{" "}
                {goal.length - goal.filter((f) => f.value === null).length} /{" "}
                {goal.length}칸
              </span>
            </div>
            <p className="muted">설계 초안이 이 내용을 기준으로 해요.</p>
            {rows(goal, "left")}
          </aside>
        )}
        {start && right && (
          <aside
            id="start-panel-right"
            className="start-panel right"
            aria-label="추천에 쓰는 정보"
          >
            <div className="start-panel-head">
              <h2>추천에 쓰는 정보</h2>
              <span className="start-need">선택</span>
            </div>
            <p className="muted">
              적어 두면 카드에서 다시 묻지 않아요. 비워 둔 칸은 그 카드에서
              물어요.
            </p>
            {byCard(info).map(([card, list]) =>
              card ? (
                <div
                  key={card}
                  className="start-group"
                  role="group"
                  aria-label={`${card} 카드`}
                >
                  <p className="start-group-label">{card} 카드</p>
                  {rows(list, "right")}
                </div>
              ) : (
                rows(list, "right")
              ),
            )}
          </aside>
        )}
      </div>
      {!shown && preview && (
        <section className="start-preview" aria-label="끝나면 받는 것">
          <h2>끝나면 이런 구성도를 받아요</h2>
          <p className="muted">
            고른 서비스로 그려지고, 결정을 바꾸면 함께 바뀌어요.
          </p>
          {preview}
          <p>
            <strong>빌드 묶음:</strong> 결정과 설계를 담은 파일을 내려받아
            Claude Code나 Codex에 그대로 맡길 수 있어요.
          </p>
        </section>
      )}
    </div>
  );
}

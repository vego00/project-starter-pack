import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import type { Journey, StartChange, StartField } from "./api";
import { EXAMPLES, MAX_IDEA, MIN_IDEA } from "./components";

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

function FieldRow({
  field,
  focused,
  busy,
  onFocus,
  edit,
}: {
  field: StartField;
  focused: boolean;
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
      className={`start-field${field.rule_read ? " rule" : ""}${focused ? " focused" : ""}`}
    >
      <div className="start-field-head">
        <span className="start-field-label">{field.label}</span>
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
  onIdea,
  onSend,
  onEdit,
  onFill,
  onBegin,
}: {
  journey: Journey | null;
  busy: boolean;
  preview?: ReactNode;
  onIdea: (idea: string) => void;
  onSend: Send;
  onEdit: Edit;
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
  const thread = useRef<HTMLDivElement>(null);
  const opened = useRef(start !== null);
  const box = useRef<HTMLTextAreaElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const started = start !== null;
  const formOnly = start?.mode === "form";

  useEffect(() => {
    // The conversation goes on in the box; without a model the screen starts at its heading.
    if (started) (formOnly ? heading : box).current?.focus();
  }, [started, formOnly]);

  useEffect(() => {
    // The panels open once, when the first sentence has filled them.
    if (start && !opened.current) {
      opened.current = true;
      setLeft(true);
      setRight(true);
      // The first sentence is now the first message; a failed start keeps it in the box.
      setText("");
    }
  }, [start]);

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

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!canSend || busy) return;
    if (!start) {
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
        busy={busy}
        onFocus={() => focusOn(field.name, side)}
        edit={onEdit}
      />
    ));

  return (
    <div className={`start-chat${start ? " started" : ""}`}>
      {start && (
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
          {!start && (
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
                  ? `빈칸 ${blanks}개가 남았어요. 모두 채우면 결정을 시작할 수 있어요.`
                  : "모두 채웠어요. 결정을 시작하면 카드를 하나씩 정해요."}
              </p>
              <div className="row">
                <button
                  type="button"
                  disabled={busy || blanks === 0}
                  onClick={() => void fill()}
                >
                  빈칸은 알아서 채워 주세요
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
                {start ? "더 알려 주기" : "프로젝트 아이디어"}
              </label>
              <textarea
                ref={box}
                id="idea"
                rows={3}
                maxLength={MAX_IDEA}
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={onKey}
                placeholder={
                  focusField
                    ? `${focusField.label}에 대해 말해 주세요. 이 칸에만 반영해요.`
                    : start
                      ? "더 알려 주실 것이 있으면 적어 주세요. 예: GPU는 없어요."
                      : "누가 어떤 문제를 겪고, 무엇을 만들고 싶은지 적어 주세요."
                }
              />
              <div className="start-composer-foot">
                {!start && (
                  <span className="muted">
                    {length.toLocaleString()} / {MAX_IDEA.toLocaleString()}자
                    (최소 {MIN_IDEA}자)
                  </span>
                )}
                <button className="primary" disabled={!canSend || busy}>
                  {busy && !start ? "시작하는 중…" : "보내기"}
                </button>
              </div>
            </form>
          )}
          {!start && (
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
              <p className="muted privacy">
                개인정보나 회사 기밀은 적지 마세요. 입력한 내용은 저장되고,
                모델이 연결된 경우 외부 모델 API로 전송돼요.
              </p>
            </>
          )}
        </section>
        {start && left && (
          <aside
            id="start-panel-left"
            className="start-panel left"
            aria-label="프로젝트 목표"
          >
            <h2>프로젝트 목표</h2>
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
            <h2>추천에 쓰는 정보</h2>
            <p className="muted">
              앞의 세 줄은 카드 규칙이 직접 읽어요. 모두 채워야 결정을 시작할 수
              있어요.
            </p>
            {rows(info, "right")}
          </aside>
        )}
      </div>
      {!start && preview && (
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

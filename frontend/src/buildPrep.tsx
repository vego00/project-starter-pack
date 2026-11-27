import { useEffect, useRef, useState } from "react";

import type { Action, BuildItem, Journey } from "./api";

const BY_LABEL = { user: "직접 정함", recommended: "추천대로" } as const;

/** Names in a recommendation come in backticks; shown as code, not as raw marks. */
function Words({ text }: { text: string }) {
  return (
    <>
      {text
        .split("`")
        .map((part, index) =>
          index % 2 ? <code key={index}>{part}</code> : part,
        )}
    </>
  );
}

/** Sends one build preparation action; resolves to an error message, or "" when it worked. */
export type BuildSend = (action: Action) => Promise<string>;

/**
 * Build preparation (ADR-026 ③): what the bundle would leave for the builder to ask. A list
 * to scan and settle at once, since in the build trials every question took its recommendation.
 * Nothing is recorded until the user presses a button for it.
 */
export function BuildPrepPanel({
  journey,
  send,
}: {
  journey: Journey;
  send: BuildSend;
}) {
  const build = journey.build;
  const editable = journey.prompt?.type === "build";
  const [pending, setPending] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const list = useRef<HTMLUListElement>(null);
  const count = useRef<HTMLParagraphElement>(null);

  // After an answer, the next question to settle gets the focus, or the count when none is left.
  useEffect(() => {
    if (focusIndex === null) return;
    const headings = list.current?.querySelectorAll<HTMLElement>("h4");
    (
      headings?.[focusIndex] ??
      headings?.[focusIndex - 1] ??
      count.current
    )?.focus();
    setFocusIndex(null);
  }, [journey, focusIndex]);

  if (!build) return null;
  const open = build.items.filter((item) => item.status !== "answered");
  const answered = build.items.filter((item) => item.status === "answered");
  const acceptable = open.filter(
    (item) => item.recommendation && item.status !== "held",
  );

  async function run(key: string, action: Action, index: number | null) {
    setPending(key);
    const failed = await send(action);
    setPending(null);
    setErrors((now) => ({ ...now, [key]: failed }));
    if (!failed && index !== null) setFocusIndex(index);
    return failed;
  }

  return (
    <section className="build-prep" aria-labelledby="build-prep-title">
      <h3 id="build-prep-title">빌드 준비</h3>
      <p className="muted">
        빌더(코딩 에이전트)가 만들기 전에 물어볼 것들이에요. 여기서 정한 답은
        빌드 묶음에 적혀서 빌더가 다시 묻지 않아요. 추천은 이 서비스가 정해 둔
        기본안이고, 직접 누른 것만 결정으로 기록돼요.
      </p>
      <p className="build-count" role="status" ref={count} tabIndex={-1}>
        {build.items.length === 0
          ? "빌더에게 물을 결정이 없어요."
          : open.length > 0
            ? `남은 결정 ${open.length}개`
            : "남은 결정 없음"}
      </p>
      {editable && acceptable.length > 0 && (
        <button
          disabled={pending !== null}
          aria-busy={pending === "all"}
          onClick={() => void run("all", { action: "build_accept_all" }, 0)}
        >
          추천 있는 항목 {acceptable.length}개를 추천대로 정하기
        </button>
      )}
      {errors.all && (
        <p className="alert" role="alert">
          저장하지 못했어요. {errors.all} 다시 눌러 주세요.
        </p>
      )}
      {!editable && open.length > 0 && (
        <button
          disabled={pending !== null}
          onClick={() => void run("prep", { action: "build_prep" }, 0)}
        >
          남은 결정에 답하기
        </button>
      )}
      {errors.prep && (
        <p className="alert" role="alert">
          열지 못했어요. {errors.prep} 다시 눌러 주세요.
        </p>
      )}
      {open.length > 0 && (
        <ul className="build-list" ref={list}>
          {open.map((item, index) => (
            <BuildRow
              key={item.id}
              item={item}
              editable={editable}
              busy={pending === item.id}
              blocked={pending !== null}
              error={errors[item.id]}
              send={(action) => run(item.id, action, index)}
            />
          ))}
        </ul>
      )}
      {answered.length > 0 && (
        <details className="build-done" open={open.length === 0}>
          <summary>정한 것 {answered.length}개</summary>
          <ul className="build-list">
            {answered.map((item) => (
              <BuildRow
                key={item.id}
                item={item}
                editable={editable}
                busy={pending === item.id}
                blocked={pending !== null}
                error={errors[item.id]}
                send={(action) => run(item.id, action, null)}
              />
            ))}
          </ul>
        </details>
      )}
      <h3>직접 할 일</h3>
      <p className="muted">
        빌드 준비로 대신할 수 없는, 사람이 해야 하는 일이에요.
      </p>
      <ul>
        {build.human_tasks.map((task) => (
          <li key={task}>
            <Words text={task} />
          </li>
        ))}
      </ul>
      {editable && (
        <button
          className="quiet"
          disabled={pending !== null}
          onClick={() => void run("finish", { action: "build_finish" }, null)}
        >
          빌드 준비 마치기
        </button>
      )}
      {errors.finish && (
        <p className="alert" role="alert">
          마치지 못했어요. {errors.finish} 다시 눌러 주세요.
        </p>
      )}
    </section>
  );
}

function BuildRow({
  item,
  editable,
  busy,
  blocked,
  error,
  send,
}: {
  item: BuildItem;
  editable: boolean;
  busy: boolean;
  blocked: boolean;
  error?: string;
  send: (action: Action) => Promise<string>;
}) {
  const [writing, setWriting] = useState(false);
  const [draft, setDraft] = useState(item.value ?? "");
  const field = useRef<HTMLTextAreaElement>(null);
  const id = `build-${item.id}`;

  useEffect(() => {
    if (writing) field.current?.focus();
  }, [writing]);

  const key = item.id;
  const answer = (value: string) =>
    void send({ action: "build_answer", key, value }).then((failed) => {
      if (!failed) setWriting(false);
    });
  return (
    <li className="build-item" aria-busy={busy}>
      <h4 id={`${id}-title`} tabIndex={-1}>
        {item.title}
        {item.status === "held" && <span className="badge">보류</span>}
        {item.status === "answered" && item.by && (
          <span className="badge">{BY_LABEL[item.by]}</span>
        )}
      </h4>
      <p>{item.question}</p>
      {item.status === "answered" && (
        <p>
          <strong>정한 답</strong> {item.value}
        </p>
      )}
      {item.status === "held" && (
        <p className="muted">보류했어요. 빌더가 만들기 전에 물어봐요.</p>
      )}
      {item.status === "recheck" && (
        <p className="note warn">
          <strong>다시 확인</strong> {item.reason}.
          {item.previous && ` 전에 정한 답: ${item.previous}`}
        </p>
      )}
      {item.recommendation && item.status !== "answered" && (
        <p className="muted">
          추천: <Words text={item.recommendation} />
        </p>
      )}
      {editable && !writing && (
        <div className="build-actions">
          {item.status === "recheck" && (
            <button
              className="quiet"
              disabled={blocked}
              aria-label={`${item.title} 그대로 두기`}
              onClick={() => void send({ action: "build_keep", key })}
            >
              그대로 두기
            </button>
          )}
          {item.recommendation && item.status !== "answered" && (
            <button
              className="quiet"
              disabled={blocked}
              aria-label={`${item.title} 추천대로 정하기`}
              onClick={() => void send({ action: "build_accept", key })}
            >
              추천대로 정하기
            </button>
          )}
          {item.status !== "answered" &&
            item.options.map((option) => (
              <button
                key={option}
                className="quiet"
                disabled={blocked}
                aria-label={`${item.title}: ${option} 고르기`}
                onClick={() => answer(option)}
              >
                {option}
              </button>
            ))}
          <button
            className="quiet"
            disabled={blocked}
            aria-label={`${item.title} ${item.status === "answered" ? "바꾸기" : "직접 쓰기"}`}
            onClick={() => setWriting(true)}
          >
            {item.status === "answered" ? "바꾸기" : "직접 쓰기"}
          </button>
          {item.status === "open" && (
            <button
              className="quiet"
              disabled={blocked}
              aria-label={`${item.title} 보류`}
              onClick={() => void send({ action: "build_hold", key })}
            >
              보류
            </button>
          )}
        </div>
      )}
      {editable && writing && (
        <form
          className="build-write"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim()) answer(draft.trim());
          }}
        >
          <label htmlFor={`${id}-answer`}>{item.title}: 내 답</label>
          <textarea
            id={`${id}-answer`}
            ref={field}
            value={draft}
            maxLength={2000}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="build-actions">
            <button type="submit" disabled={blocked || !draft.trim()}>
              저장
            </button>
            <button
              type="button"
              className="quiet"
              onClick={() => setWriting(false)}
            >
              취소
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="alert" role="alert">
          저장하지 못했어요. {error} 다시 눌러 주세요.
        </p>
      )}
    </li>
  );
}
